# Open questions and known gaps

Things that are unresolved, unvalidated, or deliberately deferred. Roughly ordered by how
much they'd matter in a real draft.

## Unimplemented parts of specified rules

### Offensive-coordinator continuity is not modeled

The run-heavy rule was described as "teams → offensive coordinator → 2025 team ranks →
rushing attempt rank", which implies the coordinator matters: a team that ran a lot under a
coordinator who has since left is a much weaker signal for 2026.

**Current behavior: coordinator is ignored entirely.** A top-10 rushing team from 2025 gets
the boost regardless of whether the staff that produced those carries is still there.

nflverse doesn't carry coordinators. Options if this matters:
- Hand-maintain a 32-row CSV of OC continuity, refreshed each offseason (probably the right
  call — it's an afternoon of work once a year and fully under your control)
- Scrape a coaching-staff source, which puts us back in Cloudflare territory
- Drop the boost for teams with a new OC rather than trying to model the new scheme

**Also unvalidated:** whether last season's rushing volume predicts *next* season's RB
production well enough to justify a 6-point boost at all. It's an assumption inherited from
the rule as specified, not something measured.

## Calibration

### The three magnitude constants are guesses

`dropoff_max_bonus=12`, `rush_boost=6`, `bye_penalty=4` were set to feel proportionate on
the 0–100 ensemble scale and then sanity-checked against one mock draft. Nothing derives
them. They're the first knobs to turn if recommendations look wrong.

The spec anticipated exactly this — "You'll want the weights configurable rather than
hardcoded — easy to A/B against historical draft outcomes later." That A/B has not been
done. Doing it properly needs completed drafts plus the season results that followed, which
is a bigger data problem than anything currently in the repo.

### The drop-off projection assumes the market drafts in ADP order

`projected_dropoff` assumes every player with an ADP inside the gap before your next pick
is gone. Real drafts deviate — runs happen, people reach. The projection will be
systematically optimistic about who survives during a positional run, which is exactly when
it matters most.

A better model would use `rank_std` from the ADP feed (already fetched, currently unused) to
compute a survival *probability* per player rather than a hard cutoff.

### Whether the 9-game filter is right for the imputation set

The filter correctly stops small-sample players from setting a baseline. But it also routes
every player who missed time into ADP-based imputation, which discards their actual
production. A star who played 8 excellent games gets imputed purely from market ADP. A
blended estimate — weight real PPG by games played, fall back to the curve for the
remainder — would probably beat both.

## Scope limits (deliberate, from the spec)

- **1QB / 1TE only.** `max_qb`/`max_te` exist as config but nothing is tested above 1, and
  the pooled flex baseline assumes RB/WR-only flex. Superflex would need the QB replacement
  rank reworked, not just a config bump.
- **PPR only.** The scoring param is threaded through the scrapers, so half-PPR and
  standard are likely a small change, but untested.
- **Single prior season.** The spec's future section wants a weighted 1–3 season blend to
  reduce single-year noise. The schema supports it (`season` is a column); nothing uses it.
- **TE-premium / TE-eligible flex.** Not supported; would change the flex pool definition.
- **No auction mode.** VOR converts naturally to auction dollars, per the spec's future
  section.

## Data and operational

### ADP is a daily-moving snapshot

The cached parquet freezes ADP at pull time. ADP moves substantially through August.
**Run with `--refresh` on draft day** — a stale ADP degrades the anti-reach guard, the
drop-off projection, and Score 4 simultaneously.

### No live-platform integration

Every pick has to be typed in. The spec's future section names Sleeper's public API as the
easy first adapter (ESPN/Yahoo need auth). The `DraftState` interface is the intended
normalization point, and `recommend()` is already a pure function of it, so an adapter
should be additive.

### Scraper fragility

The stats parser depends on `<table id="data">` existing and on the last four columns being
`G, FPTS, FPTS/G, ROST`. Both have held across all six position pages, but a FantasyPros
redesign breaks it. The parser raises rather than returning empty when the table is missing,
which is the right failure mode. Expected row counts are in
[verification.md](verification.md) as a tripwire.

Rate limiting is 1 req/sec with a browser UA. Fine for a season pull (6 requests); the
weekly pull is ~108 requests and takes about two minutes.

### Score 3 has never run on a full season

Validated on 6 weeks of RB data only. The full 18-week × 6-position pull has not been
executed end to end. Low risk since it's weight-zero, but don't switch the weight on
without pulling and inspecting the real distribution first.

## Smaller things

- **Bye-week penalty only considers same-position starters.** Having your QB and TE share a
  bye is also mildly bad and isn't modeled.
- **`tier` from the ADP feed is fetched and stored but unused.** Tier breaks are arguably a
  cleaner scarcity signal than the continuous drop-off calculation.
- **The balance guard steps aside when nothing at the short position survives the reach
  filter.** That's the specified behavior under the Q1 resolution, but it means balance can
  drift by one in tight spots. Worth watching in real drafts.
- **`find_player` resolves ambiguous names to the earliest ADP match.** Right during a
  draft almost always, but it will silently pick the wrong player for genuine duplicate
  surnames. There's no confirmation prompt.
- **No undo beyond one level of history** — `undo` pops one pick at a time, which is fine,
  but there's no redo and no pick-editing.
