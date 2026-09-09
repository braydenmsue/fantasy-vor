# Deviations from and additions to the spec

Where the implementation does something the spec does not describe, or describes
differently. Each entry says what changed and why.

## Additions — things the spec needs but doesn't specify

### 1. Roster-need guard (not in the spec at all)

**The spec's rule set does not guarantee a legal starting lineup.** This is not a small
gap — it produces unusable rosters.

The mechanism: VOR is defined relative to the Nth-best player at a position, so in a
12-team league the QB baseline is QB12. That construction *guarantees* quarterbacks carry
low VOR — only 11 QBs in the league are above replacement, and barely. Running backs and
receivers, drawn from a 60-deep pooled baseline, dominate the top of the VOR board
essentially all draft. Pure best-available therefore never takes a QB or TE, and teams
finish with no starter at those positions.

Caught by the full-draft replay test (`slot 1 has no QB`), not by any unit test.

**Added:** once the picks a team has left before the K/DEF rounds have run down to the
number of starting slots still open, the engine stops taking best-available and fills those
slots. This is a direct generalization of what rules 7–8 already do for kicker and defense —
reserve just enough picks at the end for what's still missing.

Lives in `rules.unmet_starting_needs` / `rules.picks_before_endgame`, applied in
`engine.recommend` after the reach filter and before rule 6.

The FLEX slot is handled as "three bodies out of RB and WR in any mix", so it only counts
as an open need once the dedicated RB and WR slots are accounted for.

### 2. ADP-implied VOR for players with no usable prior season

Covered in [decisions.md](decisions.md). Without it the bot silently refuses to ever draft
a rookie, which in the live 2026 pool means never considering Jeremiyah Love at ADP 27.

### 3. Reach-filter relaxation

The spec's rule 5 has no escape hatch. Applied literally, late in a draft every remaining
player's ADP has long since passed and the filter empties the pool — the engine would have
nothing to recommend.

**Added:** if the filter would return nothing, it steps aside and returns the unfiltered
pool, and the recommendation is annotated `"Rule 5 relaxed: every remaining player is past
their ADP"`. Refusing to reach must never mean refusing to pick.

### 4. Dedupe of dual-eligible players

Not a spec concern, but a correctness one — see [data-sources.md](data-sources.md).
Without it the same player can be drafted twice.

## Deviations — where the implementation differs from the text

### 1. ADP is not scraped from the page the spec names

The spec says:

> ADP (separate source — FantasyPros also publishes ADP pages, e.g. `/nfl/adp/ppr-overall.php`)

That page is client-rendered and has no table in the HTML. Uses the JSON feed behind it
instead. Same data, plus bye weeks for free. Details in [data-sources.md](data-sources.md).

### 2. Team rushing ranks come from nflverse, not pro-football-reference

The rule was specified against PFR's team ranks. PFR is Cloudflare-gated and returns 403 to
any plain HTTP client. nflverse serves the same underlying numbers as a flat CSV.

**This also changes the number being used**, deliberately: RB-only carries rather than
total team rushing attempts, because the latter includes QB runs and misranks four of the
top ten teams. Configurable via `rush_rank_basis`. Full evidence in
[data-sources.md](data-sources.md).

**Not implemented:** the offensive-coordinator part of the rule. The user's description
routed through "teams → offensive coordinator → 2025 team ranks", which implies OC
continuity matters (a run-heavy scheme means less if the coordinator left). nflverse
doesn't carry coordinators, so **a team that ranked top-10 under a coordinator who has
since departed still gets the boost.** See [open-questions.md](open-questions.md).

### 3. Rule numbering for K/DEF

The spec's open-questions parenthetical says K/DEF appear "only in 6–7". In the numbered
list, rule 6 is the low-value ADP fallback and K/DEF are rules 7 and 8. Implemented as
7–8. Noted in [decisions.md](decisions.md) under Q2.

### 4. Rule 6 does not override rule 2

The spec's rule 6 says "ignore VOR and draft by best ADP instead". Read literally as an
early exit, that also discards the balance guard — and since every late-round player is
below the 0.5 VOR floor, that means the guard is off for most of the back half of a draft.
One team in a mock finished RB 3 / WR 8.

Implemented so that rule 6 ignores **VOR only**, not roster shape: the balance guard still
applies, ranking within the short position by ADP (since VOR carries no signal in that
regime). This matches the spec's stated top-to-bottom evaluation order, where rule 2 sits
above rule 6. See [bugs-found.md](bugs-found.md) #2.

### 5. Consistency treats missing weeks as absences, not zeros

The spec defines Score 3 as `1 - (stdev(weekly_pts) / mean(weekly_pts))` without saying
what a missing week is. Counting a bye or an inactive as a 0-point game would tank the
variance of anyone who missed time — but Score 2 (games-adjusted VOR) *already* penalizes
availability. Counting it in both places punishes the same thing twice.

Missing and zero-point weeks are excluded from the calculation. Players with fewer than 4
scoring weeks get no consistency score rather than a noisy one, and are neutral-scored
(50) rather than treated as the least consistent player in the pool.

Moot for v1 since the weight is 0, but it matters whenever Score 3 gets switched on.

## Faithful to the spec — worth stating explicitly

These were easy to get wrong and are implemented exactly as written:

- **RB and WR share one pooled replacement rank** at `N × (RB + WR + FLEX)`, sorted
  together by PPG. Both subtract the *same* player's PPG. The spec calls this out as a fix
  to an earlier typo; independent per-position baselines would double-count the FLEX slot.
  Verified live: both show `replacement_ppg == 11.3` (Kenneth Walker III at pooled rank 60).
- **The 9-game filter runs before replacement rank is computed**, not after, so a
  small-sample player can neither set a baseline nor be ranked.
- **QB/TE replacement is rank N**, i.e. QB12 and TE12 in a 12-team league.
- **Scores 2 and 3 are computed and stored but weighted zero.**
- **1QB/1TE only** — the spec explicitly settles this ("This bot will only work for 1QB,
  1TE leagues") even though it floats `max_qb`/`max_te` as config. Both exist as config
  defaulting to 1, so superflex is a config change rather than a rewrite, but nothing else
  in the engine is tested for it.
