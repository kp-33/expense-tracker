---
name: expense-import
description: Use whenever the user shares one or more credit card statement CSV files to import into the Notion expense database. Defines the dry-run → review → approve → push workflow for `import.py`.
---

# Expense Import Workflow

When the user hands over a CSV path (or several), follow this loop. Do not skip steps and do not push to Notion without explicit user approval.

## 1. Dry-run first — always

Run the import with `--dry-run` before anything else. Pass all CSV paths as positional arguments — the script handles them as one combined batch:

```
python import.py path/to/file1.csv path/to/file2.csv --dry-run
```

If trips are obvious from the data (e.g., charges in Hawaii / Seattle / Dallas), pre-populate `--trip "NAME:YYYY-MM-DD:YYYY-MM-DD"` flags. You can also pre-populate `--mark "MERCHANT_SUBSTRING:SUBCATEGORY"` for trip pre-bookings (charges outside the trip dates that belong to the trip — flights, hotels, tour bookings).

## 2. Review the dry-run output and surface issues

Look for and **proactively flag** these to the user:

### Categorization issues
- **Unmapped merchants** (`(blank)` in Category column). Propose a `MERCHANT_RULES` addition or a one-off override.
- **Misclassifications**. Apply the categorization principles below.

### Trips
- **Clusters of charges in trip locations** (city/state in the description) → propose `--trip` ranges.
- **Trip pre-bookings** charged outside the actual trip date range — flights, hotels, tour bookings (e.g., FareHarbor `FH*` charges for Hawaii activities booked weeks in advance). These need `--mark`.

### Suspicious expenses (always flag — don't try to fix)
- **Outlier amounts** — one charge much larger than typical for the same merchant type.
- **Repeated same-day charges** with very different amounts (could be tip + bill split, group order, fraud).
- **Mismatched categories** — e.g., a $10k Entertainment charge from a payment processor that's usually small.
- **First-time large charges** from unfamiliar merchants.

Just call them out for the user to confirm. The user knows their own spending best.

### Refunds (negative amounts)
- The script searches for the matching original purchase by `(name, abs(amount))` and sets `Status=Refunded`. Nothing is deleted.
- **Partial refunds will appear as "unmatched"** because they don't equal any single purchase amount. That's expected — just inform the user; they can adjust manually in Notion if they want.

### Card payments
- The parser already auto-skips rows whose description contains `PAYMENT`, `AUTOPAY`, or `AUTO-PMT` (these are payments TO the card, not expenses).
- If the user has a recurring legitimate "AUTOPAY" expense that's getting wrongly skipped, narrow the rule.

## 3. Iterate

Apply the user's requested fixes — `MERCHANT_RULES` additions, `--mark`/`--trip` flags, name overrides, etc. Re-dry-run. Loop until the user explicitly approves.

## 4. Real run

Only when the user says something unambiguous like "push it", "yes go", "do it for real", drop `--dry-run` and run for real. After it completes, report:
- How many rows were written
- How many were deduped
- How many refunds were marked / unmatched
- Any new Subcategory options that were auto-added to Notion

---

## Categorization principles

These reflect the database owner's mental model. Stay consistent when adding new merchant rules — don't invent your own scheme.

### Food vs Dining
- **Dining** = full sit-down meals at restaurants. Examples: Mayflower, Tomi Sushi, Joey's Kitchen, Benihana, anything with "Bistro" / "Kitchen" / "Restaurant" in the name. TST\* (Toast POS) and SQ \* (Square POS) usually fall here.
- **Food** = fast food, snacks, takeout, drinks, treats, pet food. Examples: Burger King, In-N-Out, Heytea (boba), Puffin Donut, Venchi (chocolate), Spot Tango (dog food), Croissante (bakery).
- **Coffee shops** default to Dining unless the merchant is clearly grab-and-go.

### Subcategory defaults
- **Essential**: Grocery, Utility, Mortgage, Doctor, Health, Self Development.
- **Nonessential**: everything else.
- **Trip subcategories** (Hawaii, Seattle, Dallas, etc.) take precedence over Essential/Nonessential and are auto-added to the Notion enum on first use via `--trip` or `--mark`.

### Insurance
Currently routes to **Utility** via the bank-category fallback (no separate Insurance category exists). Don't auto-create one — confirm with the user first.

### Naming
- Use the existing `NAME_OVERRIDES` for merchants whose statement description varies but should normalize to one canonical name (e.g., AMAZON / AMZN → "Amazon", GYMPASS / WELLHUB → "Wellhub").
- The `clean_name` heuristics handle most cleanup (POS prefixes, store numbers, trailing city/state). When they fail, propose a fix rather than working around it.
