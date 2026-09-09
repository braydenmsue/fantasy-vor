# Bugs found during the build

Three real defects in the engine, plus test-harness traps worth knowing about. All are
fixed with regression tests; recorded here because the root causes are non-obvious and
easy to reintroduce.

The common thread: **all three engine bugs were caught by the full-draft replay test, not
by unit tests.** Each one is invisible at a single pick and only shows up over 180 picks.
That test is the most valuable one in the suite — keep it.

---

## 1. Drop-off projected against the wrong pool

**Symptom.** Every position group reported a 100% drop-off, on every pick:

```
FLEX projected to lose 100% of its best VOR (13.2 -> 0.0) before your next pick in 23 picks (+12.0)
```

Since every group maxed out, the bonus was uniform and did nothing except add noise — the
scarcity signal was entirely absent while appearing to work.

**Root cause.** `projected_dropoff` was being passed `candidates` — the pool *after* the
anti-reach filter. That filter keeps only players whose ADP is within 20 picks of now. But
the drop-off calculation asks "who will still be on the board at my next pick", and those
are by definition players with *later* ADP — precisely the ones the reach filter removes.
`best_later` was computed over an empty set every time, so it was always 0.0.

**Fix.** Pass the full `eligible` pool to the projection. The reach filter is a discipline
about who *I* should take now; it has no bearing on what the market will leave behind.

**Guard.** `engine.py` carries a comment explaining why this one call deliberately uses
`eligible` and not `candidates`. `test_dropoff_prefers_the_scarcer_position` asserts all
drop-off fractions land in `[0, 1]`.

**Sanity check after the fix:** at pick 1 from slot 6 (5 picks until your next), no
drop-off bonus fires at all — correct, almost nothing valuable disappears in 5 picks at the
top of a draft. At pick 6 with 13 picks to wait, FLEX shows a 55% drop-off. Both plausible.

---

## 2. Rule 6 silently bypassed rule 2

**Symptom.** One team in a 12-team mock finished **RB 3 / WR 8** — a gap of 5, where the
balance guard is supposed to cap it at 2.

**Root cause.** The low-value fallback was an early `return`:

```python
if float(candidates["vor"].max()) < config.rules.low_vor_floor:
    return _by_adp(candidates, "Rule 6: ...", limit)   # <-- skips everything below
```

The balance guard ran *after* this, so once rule 6 engaged it never ran at all. And rule 6
engages for most of the back half of a draft — by round 8 every remaining player is below
the 0.5 VOR floor. The guard was effectively off for half the draft.

Tracing slot 7 made it obvious:

```
pick  90 R8  RB2/WR4 short=RB in_candidates=  6 -> took WR Terry McLaurin
pick 127 R11 RB2/WR6 short=RB in_candidates=  0 -> took WR Rashid Shaheed
pick 138 R12 RB2/WR7 short=RB in_candidates= 70 -> took WR Ja'Kobi Lane
```

At pick 90 there were 6 RBs available and taking a WR pushed the gap to 3 — the guard
should have fired and didn't. At pick 138 there were 70 RBs available.

**Why it's a genuine spec question, not just a coding slip.** The spec's rule 6 says
"ignore VOR and draft by best ADP instead". Read as a full early exit, the behavior above
is arguably what it says. But the spec also states rules are "evaluated top-to-bottom", and
rule 2 sits above rule 6 — so rule 6 should ignore *VOR*, not roster construction.

**Fix.** Factored the guard into `_apply_balance_guard(state, candidates, config, ordered,
by_adp=False)` and applied it to both the ensemble path and the rule-6 path. Under rule 6
it ranks within the short position by ADP rather than VOR, since VOR carries no signal
there. It only ever reorders the list it's given, so it still cannot resurrect a
reach-rejected player.

**Guard.** `test_balance_guard_still_applies_under_the_rule_6_fallback`.

**After the fix**, all 12 teams in the live mock finish with an RB/WR gap of exactly 1.

---

## 3. Nothing guaranteed a legal starting lineup

**Symptom.** `slot 1 has no QB` — final roster `{'RB': 4, 'WR': 5, 'K': 1, 'DST': 1}`.
Eleven picks, no quarterback and no tight end.

**Root cause.** Not an implementation bug — a gap in the spec's rule set. See
[spec-deviations.md](spec-deviations.md) #1 for the full reasoning. Short version: VOR
defines QB replacement as QB12, which mathematically guarantees quarterbacks look bad
relative to RB/WR, so best-available never takes one.

**Fix.** Added the roster-need guard.

**Guard.** `test_every_team_fills_its_starting_lineup` in the replay test, plus
`test_roster_guard_forces_an_unfilled_position_late` and
`test_roster_guard_stays_out_of_the_way_early`.

---

## Test-harness traps

Not product bugs, but each cost real time and will bite the next person writing tests.

### `DraftState.count()` reads `settings.my_slot`

Roster lookups are relative to "my" slot. When simulating a whole draft where every team
uses the engine, it is **not** enough to pass a per-seat `Config` — the `DraftState` itself
has to be re-seated, or every team gets evaluated against slot 1's roster:

```python
seat_league = LeagueSettings(**{**config.league.__dict__, "my_slot": slot})
seat_state  = DraftState(settings=seat_league, picks=state.picks)  # shares the picks list
```

Sharing the `picks` list makes this a view, not a copy, so recording through the seat state
mutates the real draft. This masked the true severity of bug #2 until it was fixed.

### A "draft N players at position P" helper must target *your* slot

The obvious helper — repeatedly call `state.record()` — assigns each pick to whoever is on
the clock, so "give me 2 WRs" actually gives you one and gives slot 2 the other. Rule tests
that depend on roster composition then silently test the wrong thing. `tests/conftest.py`
provides `give()`, which appends directly to `my_slot`.

### The balance guard only fires when the *top* candidate causes the violation

A test that rosters 2 WRs and expects a switch will pass for the wrong reason if the
top-scored player is already an RB. To actually exercise the swap, the fixture has to be
tilted so a WR leads.

### Stable sorts and ADP ties

Setting a player's `adp_rank` to 1 to force them to the front doesn't work if another
player already has rank 1 — `sort_values` is stable and keeps the incumbent first. Use a
value strictly lower than any existing one.

### The fixture pool is only 140 players

A 12-team, 15-round draft needs 180. Tests that draft to completion use the `small_league`
fixture (4 teams) instead.
