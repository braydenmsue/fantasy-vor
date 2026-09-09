# Fantasy VOR Draft Assistant — Spec

# 1. Overview

**Idea:** Rank draftable fantasy football players by *Value Over Replacement* (VOR) — how many more fantasy points per game (PPG) a player scores versus the last realistically-startable player at that position — using the previous season's data, and use that ranking to drive live draft recommendations.

**Format assumptions (state these explicitly, since they change every formula below):**

- Scoring: PPR only (v1)
- League size: `N` teams (configurable)
- Roster construction: configurable counts for QB, RB, WR, TE, FLEX, K, DEF (defaults: 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 K, 1 DEF)
- FLEX eligibility: RB/WR only (v1 — no TE-eligible flex yet, see Future section)

---

## 2. Core Concept: Replacement Level & VOR

**Replacement level** = the production you could get for free (waiver wire / last player drafted at that position). VOR measures a player's PPG *above* that baseline. This is what actually separates "must-draft" players from "any of these 10 guys are basically the same."

### Positions with 1-per-team starters (QB, TE)

```
Replacement rank = N  (e.g., 12-team league → QB12, TE12)
VOR(player) = PPG(player) − PPG(player ranked N at that position)
```

### Positions that share the FLEX pool (RB, WR)

Both RB and WR compete for the same FLEX spot, so they need a **shared replacement rank**, not independent ones — otherwise you'd double-count FLEX value.

```
FlexPoolSize = N × (RB_spots + WR_spots + FLEX_spots)
Replacement rank = FlexPoolSize  (same number for both RB and WR)

VOR(RB) = PPG(RB) − PPG(the player ranked FlexPoolSize when RBs and WRs
          are pooled and sorted together by PPG)
VOR(WR) = PPG(WR) − PPG(that same pooled replacement-rank player)
```

*(This is the fix to the RB formula typo mentioned above — RB and WR should reference the identical pooled cutoff, since a marginal RB and a marginal WR are true substitutes for the same FLEX slot.)*

### Filter

- Exclude any player with **< 9 games played** in the prior season before computing replacement rank or VOR (small-sample players shouldn't set the baseline or get ranked).

### Cross-position ranking

Once every player has a VOR number, they're directly comparable — a QB with VOR +4.2 and a WR with VOR +4.2 are treated as equal-value draft targets. This is the whole point of VOR: it converts "points scored" (which is meaningless across positions) into "points above what you'd get anyway" (which isn't).

---

## 3. Scoring: from one VOR number to an ensemble

Right now the spec has one score (raw VOR). A single-season PPG delta is noisy — it overweights players who had one big injury-window/opportunity year. Proposed ensemble, each normalized to 0–100 (or z-scored) before combining:

| Score | What it captures | Formula sketch | First pass |
| --- | --- | --- | --- |
| **Score 1 — VOR** | Raw positional scarcity value (defined above) | `PPG(player) − PPG(replacement)` |  |
| **Score 2 — Games-adjusted VOR** | Penalizes injury risk / unreliable availability | `VOR × (games_played / 17)` or a games-played confidence multiplier | Track the data but dont include it until enough data is collected |
| **Score 3 — Consistency** | Rewards a stable weekly floor over boom/bust | `1 − (stdev(weekly_pts) / mean(weekly_pts))`, or floor = 25th-percentile week | Track the data but dont include it until enough data is collected |
| **Score 4 — ADP value gap** | How much the market is undervaluing them relative to your VOR rank | `ADP_rank − VOR_rank` (positive = value, feeds the "don't reach >20 picks" rule too) |  |
| **Ensemble** | Combined draft priority score | Weighted sum, e.g. `0.6×Score1 + 0.15×Score2 + 0.15×Score3 + 0.1×Score4` (weights configurable) | Reweight so score2 and score3 are 0 |

You'll want the weights configurable rather than hardcoded — easy to A/B against historical draft outcomes later.

---

## 4. Draft Recommendation Logic

Given the current roster state (what you've drafted, what's still available, pick number), recommend the next pick. Priority order, evaluated top-to-bottom each time it's your turn:

1. **Start with the highest-Ensemble-Score available player.**
2. **Positional balance guard:** if drafting this player would make your WR count and RB count differ by ≥3 (e.g. 4 WR vs 1 RB), instead draft the highest-VOR player at whichever of RB/WR you have fewer of.
3. **Single-QB / single-TE cap:** once you've drafted 1 QB, remove all remaining QBs from consideration (same for TE). *(Clarify: is this a hard v1 rule, or should it become configurable per league — some leagues do 2-QB/Superflex? Flagging as a config flag: `max_qb`, `max_te`, both default 1.). - This bot will only work for 1QB, 1TE leagues*
4. **Avoid drafting Defense and Kickers outside the last two rounds.**
5. **Anti-reach guard:** if the top pick's ADP is more than 20 picks later than the current pick number (i.e., you'd be reaching >20 picks early), skip to the next-highest-Ensemble-Score player that doesn't violate this.
6. **Low-value fallback:** if every remaining eligible player has VOR < 0.5, ignore VOR and draft by best ADP instead.
7. **Second-to-last round:** draft best-ADP kicker.
8. **Last round:** draft best-ADP defense.
9. **Avoiding Bye-Weeks**: When drafting 

## Review:

**Consider positional VOR drop-offs when drafting.**

- Treat position groups as **QB, FLEX, and TE**.
- When choosing between players with similar VOR, consider the VOR expected to remain at each position by the team’s next projected pick.
- **Prioritize the position with the larger projected VOR drop-off.**
    - If the next projected available player through ADP of a position group results in a reduction of 40% VOR or more, they should be considered more?
    - Example: If Jaylen Warren (RB, **4.2 VOR**) and George Kittle (TE, **4.1 VOR**) are available, but the next projected pick would leave a **3.0 VOR FLEX** and **2.1 VOR TE**, Kittle should receive greater consideration because TE is projected to lose substantially more value before the next pick.

**Open questions to pin down before building this:**

- Rule 2 and rule 5 can conflict (balance guard picks a player, then anti-reach guard rejects *that* player) — need a defined resolution order. Suggest: apply rule 5 as a filter on the *entire* eligible pool first, then rules 1–3 run only against players that pass it.
- Rule 3 says "ignored" once a position is filled — does that include for the purposes of rule 2's WR/RB balance check? (Shouldn't matter since QB/TE aren't part of that check, but worth confirming K/DEF are always excluded from rules 1–5 entirely, only appearing in 6–7.)
- Bye-week stacking / handcuff logic — not in scope for v1?

---

## 5. Data Requirements

**Source:** FantasyPros stats pages, per position, per scoring format:
`https://www.fantasypros.com/nfl/stats/{position}.php?scoring=PPR`

**Per player, per season:**

- Name, team, position, games played
- Total PPR points, PPG
- ADP (separate source — FantasyPros also publishes ADP pages, e.g. `/nfl/adp/ppr-overall.php`)
- Weekly point log (needed for Score 3 consistency calc — likely a separate scrape, e.g. weekly game logs, not the season-totals page)

**Storage:** Pandas DataFrame is sufficient for v1 (dataset is small — a few hundred rows/season). Move to SQLite/Postgres only if you start storing multiple seasons and want to query historically without re-scraping.

**Schema sketch:**

```
players_season(player_id, name, position, team, season, games_played,
                ppr_pts, ppg, adp)
players_weekly(player_id, season, week, ppr_pts)   # for consistency score
```

---

## 6. Architecture

```
scraper/          → one module per source (fantasypros_stats.py, fantasypros_adp.py)
data/              → cached CSV/parquet pulls, so you're not re-scraping every run
scoring/           → vor.py, consistency.py, ensemble.py
draft_engine/      → state tracker (who's drafted, whose turn) + recommendation logic
cli.py / app.py    → interface to actually use it during a live draft
```

Recommend a `DraftState` class that holds: current roster per team, players taken, current pick number, league settings (N, roster spots) — the recommendation engine is a pure function of `(DraftState, player_pool) → recommended_player`, which makes it testable against past drafts.

---

## 7. Dependencies

- `pandas` — data storage/manipulation
- `requests` + `beautifulsoup4` (or `lxml`) — scraping
- `numpy` — z-scoring / normalization for the ensemble
- Optional later: `sqlite3`/`sqlalchemy` if you move off flat files; `fastapi`/`streamlit` for a UI

---

## 8. Future

- Connect to live leagues via platform APIs/scraping (Sleeper has a public API; ESPN/Yahoo require auth scraping or unofficial APIs) — one adapter per platform, normalized to the same `DraftState` interface.
- TE-premium / TE-eligible-flex league support.
- Superflex / 2-QB support (`max_qb` config already anticipates this).
- Multi-season VOR (weighted blend of last 1–3 seasons instead of single prior season) to reduce single-season noise.
- Auction-draft mode (VOR converts more naturally to auction $ value than to snake-draft picks).