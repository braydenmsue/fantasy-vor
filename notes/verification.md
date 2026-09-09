# Verification

How to confirm the system is behaving, with the values observed on 2026-08-20 against 2025
stats / 2026 ADP. If you re-run after an ADP refresh the exact names will move; the
structural assertions should not.

## 1. Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Expect **71 passed**. Breakdown: `test_vor` (8), `test_state` (13), `test_rules` (31),
`test_scoring` (12), `test_draft_replay` (7).

## 2. Sources and pool

```bash
.venv/bin/python -c "
import logging; logging.basicConfig(level=logging.INFO, format='%(message)s')
from fantasy_vor.config import Config
from fantasy_vor.pool import build_pool
p = build_pool(Config(), refresh=True)
print('rows', len(p), '| dupes', p.player_id.duplicated().sum())
"
```

Expected log and output:

```
QB 2025: 86 players
RB 2025: 173 players
WR 2025: 262 players
TE 2025: 158 players
K 2025: 42 players
DST 2025: 32 players
ADP feed: 659 players, 5 experts, last updated 8/20
kept 556 draftable players
rush ranks for 32 teams (2025)
flex replacement: rank 60 of pooled RB/WR = Kenneth Walker III (11.30 ppg)
QB replacement: rank 12 = Daniel Jones (18.00 ppg)
TE replacement: rank 12 = Dalton Kincaid (10.50 ppg)
K replacement: rank 12 = Jake Bates (8.90 ppg)
DST replacement: rank 12 = New Orleans Saints (6.90 ppg)
VOR computed for 486 players, 267 held back as small-sample
ADP->VOR curve fit on 378 players: vor = -3.811 * ln(adp_rank) + 16.575
imputed VOR for 180 players without a usable prior season
pool: 556 players, 180 with imputed VOR, 174 on run-heavy teams
rows 556 | dupes 0
```

**Must hold regardless of data vintage:** `dupes` is 0, the imputation slope is negative,
and the pool is within a few rows of the "kept N draftable players" count.

## 3. VOR arithmetic, checked by hand

```bash
.venv/bin/python -c "
import pandas as pd
from fantasy_vor.config import Config
from fantasy_vor.pool import build_pool
pool = build_pool(Config())
stats = pd.read_parquet('data/stats_2025.parquet')
qb12 = stats[(stats.position=='QB')&(stats.games>=9)].nlargest(12,'ppg').iloc[11]
a = pool[pool.name=='Josh Allen'].iloc[0]
print(f'QB12 = {qb12[\"name\"]} @ {qb12.ppg}')
print(f'{a.ppg} - {qb12.ppg} = {a.ppg-qb12.ppg:.2f} | computed {a.vor:.2f}')
assert abs((a.ppg-qb12.ppg) - float(a.vor)) < 1e-6
print('MATCH')
"
```

Observed: QB12 = Daniel Jones @ 18.0; Josh Allen 22.0 − 18.0 = **4.00**, matching the
computed VOR exactly.

## 4. The shared RB/WR baseline

The single most important invariant in the whole system.

```bash
.venv/bin/python -c "
from fantasy_vor.config import Config
from fantasy_vor.pool import build_pool
r = build_pool(Config()).groupby('position')['replacement_ppg'].first()
print(r.to_string())
assert r['RB'] == r['WR'], 'flex baseline not shared'
print('MATCH:', r['RB'])
"
```

Observed:

```
DST     6.9
K       8.9
QB     18.0
RB     11.3     <-- must equal WR
TE     10.5
WR     11.3     <-- must equal RB
```

If RB and WR ever differ, the pooled flex cutoff has been broken and every RB/WR ranking in
the tool is wrong.

## 5. Full mock draft — the real end-to-end test

Runs all 12 teams through the engine and checks every roster is legal. This is the check
that caught all three engine bugs.

```bash
.venv/bin/python - <<'EOF'
from fantasy_vor.config import Config, LeagueSettings
from fantasy_vor.pool import build_pool
from fantasy_vor.draft.state import DraftState
from fantasy_vor.draft.engine import recommend

base = LeagueSettings(n_teams=12, my_slot=6)
cfg = Config(league=base)
pool = build_pool(cfg)
state = DraftState(settings=base)

while not state.is_complete:
    slot = state.slot_on_clock(state.current_pick)
    seat_l = LeagueSettings(**{**base.__dict__, "my_slot": slot})
    seat_c = Config(league=seat_l, weights=cfg.weights, rules=cfg.rules)
    seat_s = DraftState(settings=seat_l, picks=state.picks)   # shares picks; see bugs-found.md
    recs = recommend(seat_s, pool, seat_c, limit=1)
    seat_s.record(pool[pool.player_id == recs[0].player_id].iloc[0])

bad = []
for slot in range(1, 13):
    c = state.position_counts(slot)
    for pos in ("QB", "TE", "K", "DST"):
        if c.get(pos, 0) != 1:
            bad.append(f"slot{slot} {pos}={c.get(pos,0)}")
    if c.get("RB",0) + c.get("WR",0) < 5:
        bad.append(f"slot{slot} flex short {c}")
    if abs(c.get("WR",0) - c.get("RB",0)) >= 3:
        bad.append(f"slot{slot} imbalance {c}")

print("LEGALITY:", "all 12 rosters legal, all balanced" if not bad else bad)
print("K/DST early:", [p.name for p in state.picks
                       if p.position in ("K","DST") and state.round_of(p.pick_number) < 14] or "none")
EOF
```

Expected:

```
LEGALITY: all 12 rosters legal, all balanced
K/DST early: none
```

Plus every team finishing RB 5 / WR 6 (gap of 1).

## 6. Run-heavy boost and the two bases

```bash
.venv/bin/python -c "
from fantasy_vor.sources import cache, nflverse
r = cache.cached('rush_2025', lambda: nflverse.fetch_rush_ranks(2025))
rb = nflverse.run_heavy_teams(r, 10, 'rb_carries')
tm = nflverse.run_heavy_teams(r, 10, 'team_carries')
print('rb_carries :', sorted(rb))
print('team_carries:', sorted(tm))
print('team-only (QB-inflated):', sorted(tm-rb))
print('rb-only (truly RB-heavy):', sorted(rb-tm))
"
```

Observed for 2025:

```
rb_carries : ['ATL','BAL','BUF','CHI','DET','LAR','NYG','SEA','SF','TB']
team_carries: ['BAL','BUF','CHI','GB','JAC','NE','NYG','SEA','SF','WAS']
team-only (QB-inflated): ['GB','JAC','NE','WAS']
rb-only (truly RB-heavy): ['ATL','DET','LAR','TB']
```

The two bases should disagree on ~4 teams. If they agree completely, the team-alias mapping
has probably broken and one side is joining on nothing.

## 7. Weekly logs and consistency (Score 3)

Score 3 is weight-zero in v1, so nothing else exercises this path. Six weeks of RB data is
enough to prove it works without a 108-request pull:

```bash
.venv/bin/python -c "
from fantasy_vor.sources import fantasypros_stats as fps
from fantasy_vor.scoring import consistency
w = fps.fetch_weekly_stats(2025, weeks=range(1,7), positions=('RB',))
c = consistency.compute_consistency(w)
got = c[c.consistency.notna()]
print('computed for', len(got), 'players')
print(got.nlargest(3,'consistency').to_string(index=False))
"
```

Observed: 71 players scored; McCaffrey (id 16393) tops it at **0.927 consistency with a
23.4-point floor** over 6 weeks — exactly the profile of a steady elite back, which is the
signal Score 3 is supposed to capture.

Note: pulling fewer than 4 weeks correctly yields all-NA (the `MIN_WEEKS` guard), which
looks like a failure but isn't.

## 8. CLI smoke test

```bash
printf 'pick Gibbs\npick Bijan\npick Chase\npick Nacua\npick Smith-Njigba\nrec 4\nquit\n' \
  | .venv/bin/python -m fantasy_vor.cli --teams 12 --slot 6
```

Expect the pick-6 recommendation to lead with Christian McCaffrey, annotated with both a
FLEX drop-off line (~55% over 13 picks) and the SF rushing-volume boost.
