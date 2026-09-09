# Data sources

Everything here was verified live on 2026-08-20. Endpoints change; if something breaks,
start by re-running the probes at the bottom.

## 1. FantasyPros season stats — works

```
https://www.fantasypros.com/nfl/stats/{qb|rb|wr|te|k|dst}.php?scoring=PPR&year=2025
```

Server-rendered. Parse `<table id="data">`.

**Row structure.** Each player row carries a stable FantasyPros id in the anchor's class
list and the clean name in an attribute:

```html
<tr class="mpb-player-17298">
  <td class="player-rank">1</td>
  <td class="player-label ...">
    <a href="/nfl/stats/josh-allen-qb.php"
       class="player-name fp-player-link fp-id-17298"
       fp-player-name="Josh Allen">Josh Allen</a> (BUF)
  </td>
  ...
```

Take the id from `fp-id-(\d+)` and the team from the `(BUF)` suffix in the label cell.

**Column layout is position-dependent, but the tail is not.** A QB table has passing
columns, a DST table has sacks/INT. The **last four columns are always
`G, FPTS, FPTS/G, ROST`** for every position. Read from the right (`cells[-4:-1]`) and one
parser handles all six pages. Do not index from the left.

Cells need cleaning: thousands separators (`1,202`), percent signs (`99.5%`), and `-` for
missing.

**Weekly logs.** Same URL plus `&range=week&week=N`. One request per (position, week),
so a full season is ~108 requests rather than one per player. Confirmed working for
week 3 of 2025.

**Expected 2025 row counts:** QB 86, RB 173, WR 262, TE 158, K 42, DST 32 → **753 total**.
A large drop here means the parser broke or a page changed.

## 2. FantasyPros ADP — the public page does NOT work; use the JSON feed

**Dead end.** `https://www.fantasypros.com/nfl/adp/ppr-overall.php` renders its table
client-side (`<app id="reports-app">`, a Vue mount point). There is no player table in the
HTML at all. What *is* in the HTML is a decoy: an `<table id="experts">` modal listing the
expert sources, and a `popular` players JSON blob — neither contains ADP.

Other dead ends probed:
- `...ppr-overall.php?ajax=1` → 302
- `https://api.fantasypros.com/v2/json/nfl/2026/consensus-rankings?...` → 403 (needs a key)
- The reports JS bundle (`cdn.fantasypros.com/assets/js/min/pages/reports/bundle-*.js`)
  is vendor Vue code with no visible endpoint

**What works** — the feed the Vue app is backed by, no auth:

```
https://partners.fantasypros.com/api/v1/consensus-rankings.php
    ?sport=NFL&year=2026&week=0&position=ALL&scoring=PPR&type=ADP
```

Returns `{sport, type, year, week, position_id, scoring, count, total_experts,
last_updated, players: [...]}`. As of 2026-08-20: 659 players, 5 experts, updated daily.

Per-player fields that matter:

| Field | Use |
|---|---|
| `player_id` | **Same id namespace as the stats pages** — the join key |
| `player_name`, `player_team_id`, `player_position_id` | identity |
| `rank_ecr` | consensus ADP rank (integer) |
| `rank_ave` | average draft position (float) — also `rank_min`, `rank_max`, `rank_std` |
| `player_bye_week` | **bye weeks come free here** — the spec never sourced these |
| `tier` | tier grouping, currently unused |

**Filtering.** Two things get dropped:

- **IDP rows.** The feed carries 1 LB and 1 CB. Keep only QB/RB/WR/TE/K/DST.
- **Free agents.** 101 rows have `player_team_id == "FA"`, and those are *exactly* the rows
  with `player_bye_week == 0` (Tyreek Hill, Joe Mixon, Justin Tucker, Philip Rivers…).
  Unrostered or retired, undraftable. Note the check is the string `"FA"`, not an empty
  string — an emptiness check only caught 2 of them.

After filtering: **556 draftable players**.

## 3. The join — exact, no name matching

Stats `fp-id-NNNNN` == ADP `player_id`. Verified across positions, including team
defenses (Seattle DST is 8260 on both sides). This is the single most valuable property of
this source pairing; do not replace either source with one that forces fuzzy name matching.

Match rates (556 ADP rows against 753 stat rows):

| Position | Matched | Total |
|---|---|---|
| DST | 32 | 32 |
| K | 30 | 37 |
| QB | 70 | 83 |
| RB | 101 | 122 |
| TE | 78 | 95 |
| WR | 151 | 189 |
| **Total** | **462** | **556** |

The 94 unmatched are rookies and deep bench with no 2025 production. Only **one** top-60
player is unmatched: Jeremiyah Love (rookie RB, ADP 27) — which is exactly the case the
imputation module exists for.

### Duplicate ids in the stats pull

12 players appear on two position pages (dual-eligible fullbacks and gadget players:
Andrew Beck RB+TE, Connor Heyward TE+RB, Feleipe Franks QB+TE…), giving 24 rows. All are
0-point scrubs so baselines are unaffected, **but leaving them in would put a duplicate row
in the pool and let the same player be drafted twice.**

Deduped in `pool.build_pool` by keeping the highest `ppr_pts` row per `player_id`. Position
then comes from the ADP feed, which is authoritative for what a player is drafted at.

Post-dedupe pool: **556 rows, 0 duplicate ids.**

## 4. Team rushing volume — nflverse, not pro-football-reference

**Dead end: PFR is Cloudflare-gated.** `https://www.pro-football-reference.com/years/2025/`
returns **403** to plain `curl`, and returns the Cloudflare interstitial
(`<title>Just a moment...</title>`) even with a full browser User-Agent, Accept, and
Accept-Language header set. `requests` + BeautifulSoup cannot reach it. Getting through
would need a headless browser or a CF-solver, which is not worth it for 32 numbers that
change once a year.

**What works** — nflverse flat CSVs on GitHub releases, no auth:

```
https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_{year}.csv   (~880 KB)
https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_reg_{year}.csv       (~20 KB)
```

Player CSV columns used: `player_display_name`, `position`, `recent_team`, `carries`.
Team CSV columns used: `team`, `carries`.

### Team code aliases

nflverse and FantasyPros disagree. Mapping is nflverse → FantasyPros:

| nflverse | FantasyPros |
|---|---|
| `LA` | `LAR` |
| `JAX` | `JAC` |
| `OAK` | `LV` |
| `SD` | `LAC` |
| `STL` | `LAR` |
| `WSH` | `WAS` |

The first two are live in current data. The rest are defensive against historical seasons.
**If the run-heavy boost silently stops firing for a team, check this map first.**

### The QB-rush distortion (important)

The rule as originally specified reads team rushing-attempt rank off PFR. That number
**includes quarterback runs**, which makes it a poor proxy for running back opportunity.
2025 ranks by the two bases:

- **RB-only carries, top 10:** ATL, BAL, BUF, CHI, DET, LAR, NYG, SEA, SF, TB
- **Total team attempts, top 10:** BAL, BUF, CHI, GB, JAC, NE, NYG, SEA, SF, WAS

Only in the team-attempts list (inflated by mobile QBs): **GB, JAC, NE, WAS**
Only in the RB-carries list (genuinely RB-heavy): **ATL, DET, LAR, TB**

Individual rank shifts:

| Team | Team-attempt rank | RB-carry rank |
|---|---|---|
| DET | 21 | 5 |
| LAR | 17 | 4 |
| ATL | 12 | 2 |
| WAS | 9 | 24 |
| JAC | 8 | 19 |
| NE | 6 | 17 |
| NYJ | 20 | 28 |
| MIA | 24 | 15 |

**Four of the top-10 "run-heavy" teams don't actually feed their backs.** Hence the default
`rush_rank_basis = "rb_carries"`. Set it to `"team_carries"` for the literal PFR reading.

## Re-verification probes

```bash
# Are the endpoints alive?
curl -s -o /dev/null -w "%{http_code}\n" -A "Mozilla/5.0" \
  "https://www.fantasypros.com/nfl/stats/rb.php?scoring=PPR&year=2025"

curl -s -o /dev/null -w "%{http_code} %{size_download}\n" \
  "https://partners.fantasypros.com/api/v1/consensus-rankings.php?sport=NFL&year=2026&week=0&position=ALL&scoring=PPR&type=ADP"

curl -sL -o /dev/null -w "%{http_code}\n" \
  "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_reg_2025.csv"

# Does the pipeline still produce a sane pool?
.venv/bin/python -c "
import logging; logging.basicConfig(level=logging.INFO, format='%(message)s')
from fantasy_vor.config import Config
from fantasy_vor.pool import build_pool
p = build_pool(Config(), refresh=True)
print('rows', len(p), 'dupes', p.player_id.duplicated().sum())
"
```

The `--refresh` run logs replacement levels and the imputation fit, which is the fastest way
to spot a source regression.
