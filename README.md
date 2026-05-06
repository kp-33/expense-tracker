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

## Usage

Download a CSV from chase.com → Account activity → download icon → CSV. Both per-card and "All Activity" formats work.

```bash
# Dry-run first — shows what would happen, doesn't write to Notion
.venv/bin/python import.py /path/to/statement.csv --dry-run

# Real import
.venv/bin/python import.py /path/to/statement.csv

# Tag a date range as Hawaii (subcategory). Repeat the flag for multiple trips.
.venv/bin/python import.py /path/to/statement.csv --hawaii 2026-04-24:2026-04-30
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
├── .env               # your token + DB ID (gitignored)
├── .env.example       # template
└── requirements.txt
```
