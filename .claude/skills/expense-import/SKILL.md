---
name: expense-import
description: Use whenever the user shares one or more credit card statement CSV files to import into the Notion expense database via `import.py`.
---

# Expense Import

The full workflow, categorization principles, and review checklist live in `AGENTS.md` at the repo root (cross-tool agent instructions file). Read that file before processing any CSV.

Quick recap of the non-negotiable parts:

1. **Always `--dry-run` first.** Pass all CSVs as positional args in one invocation.
2. **Surface unmapped merchants, miscategorizations, suspicious amounts, trip clusters** for the user to review.
3. **Iterate** on rule additions, `--trip`, `--mark` until the user explicitly approves.
4. **Only push to Notion** after explicit approval ("push it", "yes go", etc.).

See `AGENTS.md` for the full version.
