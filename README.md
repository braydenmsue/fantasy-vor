# fantasy-vor

A PPR draft assistant that ranks players by **Value Over Replacement** — points per game
above the last realistically-startable player at a position — and uses that ranking to
recommend picks during a live draft.

Points scored are not comparable across positions; a 20-PPG quarterback and a 20-PPG
running back are worth very different things. VOR converts scoring into *points above what
you'd get anyway*, which is comparable.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m fantasy_vor.cli --teams 12 --slot 6
```

First run pulls and caches the data (a few seconds). Use `--refresh` to re-pull.

```
draft> rec              top 5 recommendations, with the reasoning
draft> pick mccaffrey   record a pick for whoever is on the clock (fuzzy match)
draft> undo             take back the last pick
draft> board wr         best available, optionally by position
draft> roster           your roster so far
draft> save             persist to draft.json  (resume with --load)
```

Recommendations explain themselves:

```
>> 1. Christian McCaffrey (RB, SF) VOR +13.2 | ADP 6 | score 111.2
       - FLEX projected to lose 55% of its best VOR (13.2 -> 5.9) before your next pick in 13 picks (+12.0)
       - SF is top-10 in rushing volume (+6.0)
```

## How a player is scored

Replacement level is the production you could get for free. VOR is what a player adds on
top of it.

- **QB, TE, K, DEF** — replacement is the `N`-th best player at the position, so QB12 in a
  12-team league.
- **RB and WR** — these share the FLEX slot, so they share **one** pooled replacement rank
  at `N × (RB + WR + FLEX)`. Computing separate RB and WR baselines would double-count the
  FLEX slot and inflate both.

Players under 9 games last season are excluded before any baseline is computed, so a
small-sample fluke can't move the replacement level.

Four scores are normalized to 0–100 and combined (weights in `config.py`):

| Score | Captures | v1 weight |
|---|---|---|
| VOR | positional scarcity | 0.857 |
| Games-adjusted VOR | availability risk | 0 — tracked only |
| Consistency | weekly floor vs boom/bust | 0 — tracked only |
| ADP value gap | where the market is wrong | 0.143 |

Scores 2 and 3 are computed and stored but carry no weight yet, by design — the intent is
to accumulate the data before letting it move a pick.

**Rookies and returning injured players** have no usable prior season. Rather than dropping
them (which would mean never drafting a rookie), their VOR is imputed from a fit of
`VOR ~ log(ADP rank)` over the players who do have data, and flagged as imputed.

## Draft rules

Evaluated in this order each time you're on the clock:

1. Eligibility — position caps (1 QB, 1 TE), and no K/DEF outside the last two rounds
2. **Anti-reach**, applied as a filter over the *whole* pool first — nothing downstream can
   resurrect a player it rejected
3. Roster guard — once the picks left equal the starting slots still open, fill them
4. Scoring, plus three adjustments:
   - **Positional drop-off** — projects who survives to your next pick via ADP and favors
     the position about to lose the most value (full strength at a 40% drop)
   - **Run-heavy RB boost** — RBs on teams that rank top-10 in rushing volume
   - **Bye-week penalty** — for stacking projected starters on one bye
5. **Balance guard** — blocks a pick that would put RB and WR 3+ apart
6. Low-value fallback to ADP when nothing clears 0.5 VOR
7. Kicker in the second-to-last round, defense in the last

Two ordering questions the spec left open are resolved as: the anti-reach guard filters the
pool *before* the balance guard runs (so they can't contradict each other), and K/DEF are
excluded from rules 1–5 entirely.

## Data sources

| Data | Source |
|---|---|
| Season + weekly stats | FantasyPros `stats/{pos}.php` — server-rendered tables |
| ADP and bye weeks | FantasyPros consensus JSON feed |
| Team rushing volume | nflverse `stats_player_reg_{year}.csv` |

Stats and ADP share the same FantasyPros player id, so they join exactly with no name
matching. Everything is cached to `data/` as parquet.

Two notes on sources:

- The public ADP *page* renders client-side and has no table to scrape; the JSON feed
  behind it is the real source, and it carries bye weeks too.
- pro-football-reference sits behind a Cloudflare challenge that returns 403 to plain HTTP
  clients, so team rushing data comes from nflverse instead.

### Why RB carries, not team rushing attempts

The run-heavy rule ranks teams by **RB-only carries** by default, because total team
rushing attempts include quarterback runs. In 2025 the two disagree sharply:

| | Team-attempt rank | RB-carry rank |
|---|---|---|
| WAS, JAC, NE, NYJ | top-10ish | 17th–28th |
| DET, LAR, ATL | 12th–21st | 2nd–5th |

Four of the top-10 "run-heavy" teams don't actually feed their backs. Set
`rush_rank_basis="team_carries"` in `RuleConfig` for the literal total-attempts reading.

## Layout

```
fantasy_vor/
  config.py     league settings, ensemble weights, rule thresholds
  pool.py       assembles the scored, draftable player pool
  sources/      fantasypros_stats, fantasypros_adp, nflverse, cache
  scoring/      vor, imputation, consistency, ensemble
  draft/        state (snake math), rules, engine
  cli.py        the REPL
```

`recommend(state, pool, config)` is a pure function, so a whole draft can be replayed
deterministically — which is what `tests/test_draft_replay.py` does, running all 12 teams
through the engine and asserting every roster comes out legal.

```bash
.venv/bin/python -m pytest tests/ -q
```

## Limitations

- 1QB / 1TE leagues only; no superflex or TE-premium
- PPR only
- Single prior season, so no multi-season blending
- Recommendations are driven by last year's production — they know nothing about training
  camp, depth-chart changes, or holdouts
