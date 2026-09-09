# Project notes

Working notes for `fantasy-vor`. These record the things that are **not** recoverable from
reading the code: why sources were chosen, which spec ambiguities were resolved and how,
what broke and why, and what is still open.

The user-facing overview lives in the top-level `README.md`. These notes are for whoever
has to change this later — including future me.

| File | What's in it |
|---|---|
| [data-sources.md](data-sources.md) | Endpoints, payload shapes, quirks, dead ends, expected row counts |
| [decisions.md](decisions.md) | Spec open questions and how each was resolved; tunables and why they're set where they are |
| [spec-deviations.md](spec-deviations.md) | Where the implementation departs from or adds to the spec |
| [bugs-found.md](bugs-found.md) | Real defects caught during the build, root cause, fix, regression test |
| [verification.md](verification.md) | Commands to re-verify the system end to end, with expected output |
| [open-questions.md](open-questions.md) | Known gaps, unvalidated assumptions, future work |

## State of things

As of the initial build (2026-08-20):

- 71 tests pass (`.venv/bin/python -m pytest tests/ -q`)
- A full 12-team mock draft on live 2025/2026 data yields 12 legal, balanced rosters
- Scores 2 and 3 are computed and stored but weighted zero, by design
- Nothing has been committed to git

## Source data vintage

Everything is keyed to **2025 stats** (the completed prior season) driving a **2026 draft**.
The ADP feed updates daily during draft season; the cached parquet under `data/` is a
snapshot. Re-pull with `--refresh` before a real draft, since ADP moves a lot in August.
