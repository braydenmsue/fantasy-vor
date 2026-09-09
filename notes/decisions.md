# Decisions

Every ambiguity in the spec, how it was resolved, and why. Decisions marked **[user]** were
made by the project owner; the rest are implementation judgment calls.

## The spec's own open questions

The spec ends section 4 with three open questions. All three are now closed.

### Q1 — Rule 2 and rule 5 can conflict **[user: take the suggestion]**

> "Rule 2 and rule 5 can conflict (balance guard picks a player, then anti-reach guard
> rejects *that* player) — need a defined resolution order. Suggest: apply rule 5 as a
> filter on the *entire* eligible pool first, then rules 1–3 run only against players that
> pass it."

**Resolved: adopt the suggestion.** The anti-reach guard runs first as a pool filter, so
everything downstream only ever sees players that already passed it. The balance guard
reorders that filtered list and can never resurrect a rejected player.

Enforced by `tests/test_rules.py::test_rule_2_can_only_choose_players_that_passed_rule_5`.

**Consequence to be aware of:** if no player at the short position survives the reach
filter, the balance guard has nothing to swap in and steps aside. That is the specified
behavior under this resolution, not a bug — but it is why balance can drift by one in
tight spots.

### Q2 — Does rule 3 interact with rule 2's balance check? **[user: take the parenthetical]**

> "(Shouldn't matter since QB/TE aren't part of that check, but worth confirming K/DEF are
> always excluded from rules 1–5 entirely, only appearing in 6–7.)"

**Resolved: K and DEF are excluded from rules 1–5 entirely** and appear only in the
last-two-rounds rules.

Note the spec's own numbering slips here: the parenthetical says "6–7", but in the numbered
list rule 6 is the low-value ADP fallback, and kicker/defense are rules **7 and 8**. The
substance is unambiguous, so K/DEF are gated to rules 7–8. The QB/TE half of the question
is moot as the spec predicted — the balance check only ever looks at RB and WR.

### Q3 — Bye-week stacking / handcuffs, in scope for v1?

**Resolved two ways:**

1. **Bye weeks: soft penalty [user].** A small ensemble penalty when a pick would put two
   or more *projected starters* at the same position on the same bye. Never hard-blocks a
   clearly-best player. Only applies while the position is still filling starting slots —
   bench depth sharing a bye is not a lineup problem.
2. **Handcuffs → replaced with a team-rushing-volume rule [user].** Instead of handcuff
   logic, the owner specified a new rule: rank teams by rushing attempts, and prioritize
   remaining RBs from top-10 teams. If taking that RB would violate rule 2, take the
   highest-ADP WR instead. See [spec-deviations.md](spec-deviations.md).

## Rule 9 was an unfinished sentence

The spec's rule 9 reads, in full:

> **9. Avoiding Bye-Weeks**: When drafting

That is the entire rule — it is cut off mid-sentence in the source export. The soft-penalty
design above is the resolution; there was no further text to implement.

## Other decisions

### Interface: interactive CLI **[user]**

Chosen over a Streamlit UI and over a library-plus-tests-only build. Rationale: a live
draft runs on a ~90-second clock, and typing `pick mccaffrey` is faster than clicking. The
engine is a pure function regardless, so a UI can be added later without touching the rules.

### Players with no usable prior season: impute VOR from ADP **[user]**

Rookies have no prior-season row, and the spec's 9-game filter also removes stars who
missed most of last year. Both groups go early in real drafts. The three options were:
exclude them (bot never drafts a rookie), rank them by ADP only (they surface solely
through the fallback paths), or impute.

**Chosen: impute.** Fit `vor ~ slope * ln(adp_rank) + intercept` on players who do have
data, then read imputed VOR off that curve, clipped to the observed VOR range and flagged
`vor_imputed=True` so the CLI can show it.

Current fit (2025 data, 378 players): `vor = -3.811 * ln(adp_rank) + 16.575`, applied to
180 players. Slope must be negative — a later pick cannot imply more value — and there's a
test asserting that.

### Positional drop-off: scarcity bonus **[user]**

The spec's Review section describes the idea but leaves its strength open ("should be
considered more?"). Implemented as a bonus scaled by the projected drop-off, reaching full
strength at the spec's 40% threshold. Requires the draft slot to project the next pick.

Projection model: players come off the board in ADP order, so anyone whose ADP rank falls
inside the gap before your next pick is assumed gone. Groups are QB / FLEX / TE, per the
Review section.

### Ensemble weights: 0.857 / 0 / 0 / 0.143

The spec gives nominal weights of 0.6 VOR / 0.15 games-adjusted / 0.15 consistency / 0.1
ADP-gap, then says to "reweight so score2 and score3 are 0".

Zeroing the middle two and renormalizing to sum to 1 gives **0.857 / 0 / 0 / 0.143**, which
preserves the intended **6:1 ratio** between VOR and the ADP value gap. Scores 2 and 3 are
still computed and stored — the spec wants that data tracked before it counts.

There's a test asserting that tampering with `consistency` and `games` cannot change the
recommendation order under v1 weights.

## Tunables

All in `fantasy_vor/config.py`. Values that came from the spec are marked; the rest are
judgment calls that are worth tuning against real drafts.

| Setting | Value | Source |
|---|---|---|
| `min_games` | 9 | spec §2 |
| `max_qb`, `max_te` | 1, 1 | spec §4.3 — "this bot will only work for 1QB, 1TE leagues" |
| `rb_wr_imbalance` | 3 | spec §4.2 ("differ by ≥3") |
| `reach_threshold` | 20 | spec §4.5 ("more than 20 picks") |
| `low_vor_floor` | 0.5 | spec §4.6 |
| `dropoff_threshold` | 0.40 | spec Review section |
| `dropoff_max_bonus` | 12.0 | **judgment** — bonus is on the 0–100 ensemble scale |
| `rush_rank_top_n` | 10 | user ("top 10") |
| `rush_rank_basis` | `rb_carries` | **judgment** — see the QB-rush distortion in data-sources.md |
| `rush_boost` | 6.0 | **judgment** |
| `bye_penalty` | 4.0 | **judgment** |

### On the magnitudes

`dropoff_max_bonus=12`, `rush_boost=6` and `bye_penalty=4` are all expressed on the
normalized 0–100 ensemble scale. For calibration: in the live 2026 pool, 12 points of
ensemble score is roughly the gap between the RB1 and the RB5 — so a maxed-out drop-off
bonus is deliberately strong enough to jump a tier, and the rush boost is about half a
tier. These are the first knobs to turn if recommendations feel wrong; nothing about them
is derived, they were set to feel proportionate and then sanity-checked against a mock
draft.
