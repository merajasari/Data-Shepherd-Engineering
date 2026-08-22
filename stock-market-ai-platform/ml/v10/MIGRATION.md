# V10 consolidation

V10 is the only active stock research generation after frozen V8.

The automatic-tuning capabilities formerly developed under V9 are now owned by
V10:

- `auto_tuning_registry.py` — bounded deterministic Cycle 1 candidate registry
- `auto_tuning_evaluator.py` — purged walk-forward Cycle 1 evaluation
- `auto_tuning_confirmation.py` — fixed-winner confirmation gates
- `auto_tuning_cycle2_registry.py` — risk-controlled Cycle 2 registry
- `auto_tuning_cycle2_evaluator.py` — Cycle 2 walk-forward and stress evaluation

New artifacts are written under `data/model/v10/auto_tuning/`. Existing
`data/model/v9/` artifacts are historical evidence: do not rewrite them,
relabel them as V10 results, or use them as fresh confirmation/holdout evidence.
They may be moved to archival storage only after checksums and provenance are
preserved.

V10's existing prospective confirmation and its 2026-11-02 formal holdout remain
authoritative. Migrating an algorithm does not migrate or reset evidence. Frozen
V8 code, artifacts, holdout boundary, and production reference are unchanged.
No module in this consolidation places brokerage orders.
