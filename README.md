# Expense Tracker

Imports a credit card statement CSV into our shared Notion expense database. Auto-categorizes by merchant, supports refunds (marks original purchase as `Refunded` instead of deleting), dedups against existing rows.

## Setup

1. **Get your Notion integration token.** Go to https://www.notion.so/profile/integrations → New integration → Internal. Copy the `ntn_...` secret.

2. **Connect the integration to our shared expense DB.** Open the database page in Notion → `...` (top right) → Connections → search for your integration name → add. Without this, the API can't see the DB.

3. **Clone & install:**
   ```bash
   git clone <repo-url>
   cd expense-tracker
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

4. **Create `.env`:**
   ```bash
   cp .env.example .env
   ```
   Open `.env` and paste your token after `NOTION_TOKEN=`. The DB ID is already filled in.

## Workflow (required)

**Always dry-run first. Never push to Notion without reviewing the dry-run output.**

Coding agents in this repo (Codex, Claude Code, Cursor, etc.) follow this workflow automatically: `AGENTS.md` at the repo root is the canonical source, and `.claude/skills/expense-import/SKILL.md` is a Claude-specific pointer to it. Treat `AGENTS.md` as the canonical guide; the rest of this section is a quick recap.

The auto-categorizer is good but not perfect — it routinely miscategorizes new merchants, and Notion rows are tedious to fix manually after the fact. The dry-run is fast and catches problems before they land.

1. Run with `--dry-run` and read the full output.
2. Identify any miscategorizations, wrong name cleanup, or unmapped merchants.
3. If anything's wrong: fix it (add a merchant rule, override a name, adjust a trip range) and re-dry-run. Iterate until the output is right.
4. Only then drop `--dry-run` to push for real.

## Usage

Download a CSV from chase.com → Account activity → download icon → CSV. Both per-card and "All Activity" formats work.

```bash
# Step 1: dry-run — shows what would happen, doesn't touch Notion
.venv/bin/python import.py /path/to/statement.csv --dry-run

# Step 2: real import (only after reviewing the dry-run output)
.venv/bin/python import.py /path/to/statement.csv

# Tag a date range as a trip subcategory. Repeat the flag for multiple trips.
# If the trip name doesn't exist in Notion's Subcategory enum yet, it's added automatically.
.venv/bin/python import.py /path/to/statement.csv \
    --trip "Hawaii:2026-04-25:2026-04-29" \
    --trip "Seattle:2026-04-06:2026-04-10" \
    --dry-run
```

## How it works

- **Dedup**: queries Notion for existing rows in the CSV's date range; skips anything matching `(date, amount, name)`. Also flags `(date, amount)` matches with different names so you can review.
- **Refunds** (negative amounts in the CSV): finds the matching original purchase in Notion and sets its `Status` to `Refunded`. Nothing is deleted.
- **Categorization**: merchant rules in `import.py` (`MERCHANT_RULES` list) take priority; falls back to the bank's own category. Unmapped merchants are reported at the end of each run — add them to `MERCHANT_RULES` to auto-categorize next time.

## Project layout

```
expense-tracker/
├── import.py          # CLI: parsing, categorization, name cleanup
├── reader/            # Notion read operations (queries, dedup checks, report aggregation)
├── writer/            # Notion write operations (create, update, archive)
├── tests/             # unittest suite — run with `.venv/bin/python -m unittest discover tests`
├── report/            # generated monthly PDF reports (gitignored)
├── AGENTS.md          # canonical agent workflow (Codex / Cursor / any agent)
├── .claude/skills/    # Claude Code skill — points at AGENTS.md
├── .env               # your token + DB ID (gitignored)
├── .env.example       # template
└── requirements.txt
```
