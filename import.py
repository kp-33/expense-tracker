#!/usr/bin/env python3
"""Import a credit card statement CSV into the Notion expense database."""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from notion_client import Client

from reader import fetch_existing_keys, find_matching_purchase, get_data_source_id, row_exists
from writer import create_entry, ensure_subcategory_options, mark_refunded

# Bank-provided categorization → our enum (used as fallback when no merchant rule matches).
# Note: "Food & Drink" maps to Dining as a default; the merchant rules below override
# specific fast-food/snack/drink merchants to "Food".
BANK_CATEGORY_MAP = {
    "Shopping": "Shopping",
    "Food & Drink": "Dining",
    "Groceries": "Grocery",
    "Gas": "Transportation",
    "Automotive": "Transportation",
    "Travel": "Travel",
    "Health & Wellness": "Health",
    "Entertainment": "Entertainment",
    "Home": "Home Decor",
    "Bills & Utilities": "Utility",
}

# Substring → our category. Checked in order; first match wins. Edit freely.
MERCHANT_RULES = [
    # Transportation
    ("LYFT", "Transportation"),
    ("UBER EATS", "Dining"),  # must come before "UBER"
    ("UBER", "Transportation"),
    ("CHEVRON", "Transportation"),
    ("SHELL OIL", "Transportation"),
    ("76 ", "Transportation"),
    ("BART", "Transportation"),
    ("MUNI", "Transportation"),
    ("PARKING", "Transportation"),
    ("PARKLINQ", "Transportation"),
    ("GARAGE", "Transportation"),
    ("CALTRAIN", "Transportation"),

    # Grocery
    ("WHOLE FOODS", "Grocery"),
    ("TRADER JOE", "Grocery"),
    ("SAFEWAY", "Grocery"),
    ("COSTCO", "Grocery"),
    ("RALPHS", "Grocery"),
    ("KROGER", "Grocery"),
    ("ALDI", "Grocery"),
    ("INSTACART", "Grocery"),
    ("99 RANCH", "Grocery"),
    ("H MART", "Grocery"),
    ("SPROUTS", "Grocery"),
    ("FOODLAND", "Grocery"),
    ("NAPILI MARKET", "Grocery"),

    # Food (fast food, snacks, takeout, drinks, treats, pet food).
    # Per user's framework: "quick / casual / snack / treat / takeout / drinks".
    ("CROISSANT", "Food"),  # bakery — must precede TST* to avoid being routed to Dining
    ("BURGER KING", "Food"),
    ("MCDONALD", "Food"),
    ("TACO BELL", "Food"),
    ("SUBWAY", "Food"),
    ("WENDY", "Food"),
    ("IN-N-OUT", "Food"),
    ("SHAKE SHACK", "Food"),
    ("KFC", "Food"),
    ("PANERA", "Food"),
    ("CHIPOTLE", "Food"),
    ("FIVE GUYS", "Food"),
    ("JACK IN THE BOX", "Food"),
    ("CHICK-FIL-A", "Food"),
    ("POPEYES", "Food"),
    # Boba / bubble tea
    ("HEYTEA", "Food"),
    ("SHARETEA", "Food"),
    ("GONG CHA", "Food"),
    ("BOBA", "Food"),
    ("KUNG FU TEA", "Food"),
    # Donuts / pastries / chocolate / candy
    ("DUNKIN", "Food"),
    ("KRISPY KREME", "Food"),
    ("DONUT", "Food"),
    ("BAKERY", "Food"),
    ("PASTRY", "Food"),
    ("CHOCO", "Food"),
    ("VENCHI", "Food"),
    ("MEET FRESH", "Food"),
    ("MATCHA", "Food"),
    ("JOECOFFEE", "Food"),
    # Pet food (vet visits go to Doctor; food/treats go here)
    ("CHEWY", "Food"),
    ("SPOT TANGO", "Food"),

    # Dining (sit-down, full meals)
    ("TST*", "Dining"),  # Toast POS — almost always restaurants
    ("SQ *", "Dining"),  # Square POS — usually small businesses; tweak if too aggressive
    ("STARBUCKS", "Dining"),  # ambiguous; default Dining (revisit if user prefers Food)
    ("PEET", "Dining"),
    ("BLUE BOTTLE", "Dining"),
    ("DOORDASH", "Dining"),  # delivery of full meals; revisit if treated as Food
    ("GRUBHUB", "Dining"),
    ("UBER EATS", "Dining"),  # already routed above; keep here for clarity
    ("PIZZA", "Dining"),
    ("SUSHI", "Dining"),
    ("RAMEN", "Dining"),
    ("CAFE", "Dining"),
    ("RESTAURANT", "Dining"),
    ("COFFEE", "Dining"),
    ("BISTRO", "Dining"),
    ("KITCHEN", "Dining"),
    ("TEPPANYAKI", "Dining"),
    ("THAI", "Dining"),
    ("BENIHANA", "Dining"),
    ("TAQUERIA", "Dining"),
    ("IGM WAILEA", "Dining"),
    ("KALEI", "Dining"),
    ("CHO DANG TOFU", "Dining"),

    # Utility
    ("PG&E", "Utility"),
    ("AT&T", "Utility"),
    ("VERIZON", "Utility"),
    ("COMCAST", "Utility"),
    ("XFINITY", "Utility"),
    ("T-MOBILE", "Utility"),
    ("SPECTRUM", "Utility"),
    ("CSJ SMART METERS", "Utility"),

    # Travel
    ("DELTA AIR", "Travel"),
    ("UNITED AIR", "Travel"),
    ("AMERICAN AIRLINES", "Travel"),
    ("SOUTHWEST AIR", "Travel"),
    ("ALASKA AIR", "Travel"),
    ("HAWAIIAN AIR", "Travel"),
    ("MARRIOTT", "Travel"),
    ("HILTON", "Travel"),
    ("HYATT", "Travel"),
    ("WESTIN", "Travel"),
    ("AIRBNB", "Travel"),
    ("BOOKING.COM", "Travel"),
    ("EXPEDIA", "Travel"),
    ("NATIONAL PAR", "Travel"),  # national park entry fees
    ("CITI TRAVEL", "Travel"),
    ("ALLSAVE CAR RENTAL", "Travel"),
    ("CAR RENTAL", "Travel"),  # generic catch-all for rental car merchants
    ("HERTZ", "Travel"),
    ("AVIS", "Travel"),
    ("ENTERPRISE RENT", "Travel"),

    # Health
    ("CVS", "Health"),
    ("WALGREENS", "Health"),
    ("RITE AID", "Health"),

    # Doctor
    ("KAISER", "Doctor"),
    ("ONE MEDICAL", "Doctor"),

    # Entertainment
    ("NETFLIX", "Entertainment"),
    ("SPOTIFY", "Entertainment"),
    ("HULU", "Entertainment"),
    ("DISNEY", "Entertainment"),
    ("HBO", "Entertainment"),
    ("AMC ", "Entertainment"),
    ("REGAL", "Entertainment"),
    ("CINEMA", "Entertainment"),
    ("CINELUX", "Entertainment"),
    ("MOVIETICKET", "Entertainment"),
    ("FH*", "Entertainment"),  # FareHarbor: tour/activity bookings

    # Home Decor
    ("IKEA", "Home Decor"),
    ("WILLIAMS SONOMA", "Home Decor"),
    ("WEST ELM", "Home Decor"),
    ("CRATE & BARREL", "Home Decor"),
    ("WAYFAIR", "Home Decor"),
    ("HOME DEPOT", "Home Decor"),
    ("LOWE'S", "Home Decor"),
    ("TJMAXX", "Home Decor"),
    ("TJ MAXX", "Home Decor"),
    ("HOMEGOODS", "Home Decor"),

    # Clothing
    ("NORDSTROM", "Clothing"),
    ("MACY", "Clothing"),
    ("OLD NAVY", "Clothing"),
    ("H&M", "Clothing"),
    ("ZARA", "Clothing"),
    ("UNIQLO", "Clothing"),
    ("NIKE", "Clothing"),
    ("ADIDAS", "Clothing"),
    ("LULULEMON", "Clothing"),
    ("MAUI JIM", "Clothing"),  # sunglasses
    ("MALIBU SHIRTS", "Clothing"),
    ("MARSHALLS", "Clothing"),  # user buys clothes here per Jan pattern
    ("ARITZIA", "Clothing"),
    ("FREE PEOPLE", "Clothing"),

    # Shopping (catch-alls — keep last)
    ("AMAZON", "Shopping"),
    ("AMZN", "Shopping"),
    ("TARGET", "Shopping"),
    ("WALMART", "Shopping"),
    ("BEST BUY", "Shopping"),
    ("APPLE.COM", "Shopping"),
    ("ABC #", "Shopping"),  # Hawaii ABC Stores — convenience
    ("MAUIPINEAPPLE", "Shopping"),  # MAUIPINEAPPLESTORE is one token; needs explicit prefix
    ("TEMU", "Shopping"),
    ("MEMBERSHIP FEE", "Shopping"),  # credit card annual fees

    # Self Development (essential — gym, learning tools, productivity software)
    ("CLAUDE.AI", "Self Development"),
]

ESSENTIAL_CATEGORIES = {"Grocery", "Utility", "Mortgage", "Doctor", "Health", "Self Development"}


def categorize(description: str, bank_category: str) -> str | None:
    desc_upper = description.upper()
    for needle, cat in MERCHANT_RULES:
        # \b at the start prevents false positives like HULU matching kaHULUi.
        if re.search(r"\b" + re.escape(needle), desc_upper):
            return cat
    return BANK_CATEGORY_MAP.get(bank_category)


def subcategorize(category, txn_date, description, trip_ranges, mark_rules):
    """Compute the Subcategory value for a transaction.

    Precedence (highest first):
      1. Per-merchant overrides via --mark (substring match against description).
      2. Trip date ranges via --trip.
      3. Default: Essential if category is in ESSENTIAL_CATEGORIES, else Nonessential.
    """
    desc_upper = description.upper()
    for needle, sub_name in mark_rules:
        if needle.upper() in desc_upper:
            return sub_name
    for trip_name, start, end in trip_ranges:
        if start <= txn_date <= end:
            return trip_name
    if category is None:
        return None
    if category in ESSENTIAL_CATEGORIES:
        return "Essential"
    return "Nonessential"


_POS_PREFIX_RE = re.compile(r"^(?:TST|SQ|SP|CP|GMS|PY|IN)\s*\*\s*", re.IGNORECASE)

# Per-merchant canonical-name overrides (matched on description, case-insensitive).
NAME_OVERRIDES = [
    (re.compile(r"\b(AMAZON|AMZN)\b", re.IGNORECASE), "Amazon"),
    (re.compile(r"\b(GYMPASS|WELLHUB)\b", re.IGNORECASE), "Wellhub"),
]


def clean_name(description: str) -> str:
    for pattern, canonical in NAME_OVERRIDES:
        if pattern.search(description):
            return canonical
    s = description.strip()
    # Strip POS aggregator prefixes like "TST*", "SQ *", "SP*" — keep what's after.
    s = _POS_PREFIX_RE.sub("", s)
    # Drop trailing URL fragments
    s = re.sub(r"https?://\S+", "", s)
    # Drop trailing 2-letter state code
    s = re.sub(r"\s+[A-Z]{2}\s*$", "", s)
    # Drop trailing TitleCase city words (e.g., " Wailea", " San Jose"). Only matches Title Case
    # so all-caps merchant tokens (e.g., "GOLDHILL BISTRO") survive intact.
    s = re.sub(r"\s+(?:[A-Z][a-z]+\s+)*[A-Z][a-z]+\s*$", "", s)
    # Drop trailing standalone numbers (phone, zip, store no.)
    s = re.sub(r"\s+\d{3,}\s*$", "", s)
    # Drop trailing #1234-style store numbers (with optional suffix word)
    s = re.sub(r"\s+#\S+(?:\s+\S+)?\s*$", "", s)
    # Normalize backtick to apostrophe (some statements use ` for ')
    s = s.replace("`", "'")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return description.strip()
    # Title-case but keep the letter after an apostrophe lowercase (e.g., "Joey's", not "Joey'S")
    titled = s.title()
    titled = re.sub(r"(\w)'([A-Z])", lambda m: m.group(1) + "'" + m.group(2).lower(), titled)
    return titled


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%m/%d/%Y").date()


def parse_money(value: str) -> float:
    cleaned = value.strip().replace("$", "").replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    return float(cleaned)


def parse_trip_ranges(values):
    """Parse --trip "NAME:YYYY-MM-DD:YYYY-MM-DD" entries.
    Returns list of (name, start_date, end_date)."""
    ranges = []
    for v in values:
        parts = v.split(":")
        if len(parts) != 3:
            sys.exit(f"--trip expects NAME:YYYY-MM-DD:YYYY-MM-DD, got: {v}")
        name, start_s, end_s = parts
        try:
            start = datetime.strptime(start_s, "%Y-%m-%d").date()
            end = datetime.strptime(end_s, "%Y-%m-%d").date()
        except ValueError:
            sys.exit(f"--trip dates must be YYYY-MM-DD, got: {v}")
        ranges.append((name.strip(), start, end))
    return ranges


def parse_mark_rules(values):
    """Parse --mark "MERCHANT_SUBSTRING:SUBCATEGORY" entries.
    Returns list of (substring, subcategory_name). Match is case-insensitive substring."""
    rules = []
    for v in values:
        try:
            substring, sub_name = v.rsplit(":", 1)
        except ValueError:
            sys.exit(f"--mark expects SUBSTRING:SUBCATEGORY, got: {v}")
        rules.append((substring.strip(), sub_name.strip()))
    return rules


def read_statement_csv(path):
    """Detect statement format by header and parse. Returns (rows, skipped_payments)."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if "Transaction Date" in fields and "Amount" in fields:
            return _parse_per_card(reader)
        if "Status" in fields and "Debit" in fields and "Credit" in fields:
            return _parse_all_activity(reader)
        sys.exit(f"Unrecognized CSV header: {fields}")


def _parse_per_card(reader):
    """Per-card export: Transaction Date, Post Date, Description, Category, Type, Amount, Memo."""
    rows, skipped = [], 0
    for r in reader:
        if r.get("Type") == "Payment":
            skipped += 1
            continue
        try:
            amount = -parse_money(r["Amount"])  # purchases are negative in CSV; flip
            txn_date = parse_date(r["Transaction Date"])
        except (ValueError, KeyError):
            continue
        rows.append({
            "date": txn_date,
            "amount": amount,
            "raw_description": r["Description"],
            "bank_category": r.get("Category", ""),
        })
    return rows, skipped


def _parse_all_activity(reader):
    """All-activity export: Status, Date, Description, Debit, Credit, Member Name."""
    rows, skipped = [], 0
    for r in reader:
        desc = r.get("Description", "")
        if "PAYMENT" in desc.upper():
            skipped += 1
            continue
        debit = (r.get("Debit") or "").strip()
        credit = (r.get("Credit") or "").strip()
        try:
            if debit:
                amount = parse_money(debit)  # debit is already positive expense
            elif credit:
                amount = -abs(parse_money(credit))  # refund → negative expense
            else:
                continue
            txn_date = parse_date(r["Date"])
        except (ValueError, KeyError):
            continue
        rows.append({
            "date": txn_date,
            "amount": amount,
            "raw_description": desc,
            "bank_category": "",
        })
    return rows, skipped


def main():
    parser = argparse.ArgumentParser(description="Import a credit card statement CSV into the Notion expense DB.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--trip", action="append", default=[],
                        help="Tag transactions in a date range with a trip subcategory. "
                             "Format NAME:YYYY-MM-DD:YYYY-MM-DD (repeatable). "
                             "If the trip name isn't in the Subcategory enum yet, it will be added to Notion.")
    parser.add_argument("--mark", action="append", default=[],
                        help="Per-merchant subcategory override (takes precedence over --trip). "
                             "Format SUBSTRING:SUBCATEGORY (repeatable). Useful for trip pre-bookings "
                             "charged outside the trip dates, e.g. --mark \"PACWHALE:Hawaii\".")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and categorize but do not write to Notion.")
    args = parser.parse_args()

    trip_ranges = parse_trip_ranges(args.trip)
    mark_rules = parse_mark_rules(args.mark)

    rows, skipped_payments = read_statement_csv(args.csv_path)

    if not rows:
        sys.exit("No expense rows found in CSV.")

    entries = []
    unmapped = defaultdict(list)
    for r in rows:
        category = categorize(r["raw_description"], r["bank_category"])
        subcategory = subcategorize(category, r["date"], r["raw_description"], trip_ranges, mark_rules)
        name = clean_name(r["raw_description"])
        entries.append({
            "date": r["date"],
            "amount": r["amount"],
            "name": name,
            "category": category,
            "subcategory": subcategory,
            "raw": r["raw_description"],
        })
        if category is None:
            unmapped[name].append(r["raw_description"])

    date_min = min(e["date"] for e in entries)
    date_max = max(e["date"] for e in entries)

    if args.dry_run:
        notion = None
        strict_existing, loose_existing = set(), defaultdict(set)
        data_source_id = None
    else:
        load_dotenv(Path(__file__).parent / ".env")
        token = os.environ.get("NOTION_TOKEN")
        db_id = os.environ.get("NOTION_DATABASE_ID")
        if not token or not db_id:
            sys.exit("NOTION_TOKEN and NOTION_DATABASE_ID must be set in .env")

        notion = Client(auth=token)
        data_source_id = get_data_source_id(notion, db_id)
        sub_names_needed = [name for name, _, _ in trip_ranges] + [n for _, n in mark_rules]
        if sub_names_needed:
            added = ensure_subcategory_options(notion, data_source_id, sub_names_needed)
            for name in added:
                print(f"  + Added Subcategory option to Notion: {name!r}")
        print(f"Querying existing Notion rows from {date_min} to {date_max}…")
        strict_existing, loose_existing = fetch_existing_keys(
            notion, data_source_id, date_min, date_max
        )

    purchases = [e for e in entries if e["amount"] > 0]
    refunds = [e for e in entries if e["amount"] < 0]

    new_entries = []
    skipped_dupes = 0
    skipped_loose = 0
    for e in purchases:
        date_iso = e["date"].isoformat()
        amt_str = f"{e['amount']:.2f}"
        if (date_iso, amt_str, e["name"]) in strict_existing:
            skipped_dupes += 1
            continue
        if (date_iso, amt_str) in loose_existing:
            existing_names = loose_existing[(date_iso, amt_str)]
            print(f"  ! Skipping likely duplicate: {date_iso} ${e['amount']:.2f} {e['name']!r}"
                  f" — DB already has same date/amount with name(s) {sorted(existing_names)}")
            skipped_loose += 1
            continue
        new_entries.append(e)

    written = 0
    skipped_race = 0
    archived = 0
    unmatched_refunds = 0
    if args.dry_run:
        print("\n--- DRY RUN: rows that would be created ---")
        for e in new_entries:
            cat = e["category"] or "(blank)"
            sub = e["subcategory"] or "(blank)"
            print(f"  {e['date']}  ${e['amount']:8.2f}  {cat:<14}  {sub:<12}  {e['name']}")
        if refunds:
            print("\n--- DRY RUN: refunds that would mark matching purchases as Refunded ---")
            for r in refunds:
                print(f"  {r['date']}  ${abs(r['amount']):8.2f}  search-and-mark: {r['name']!r}")
    else:
        for e in new_entries:
            # Per-row safety net: re-check immediately before insert in case the DB
            # changed between the bulk fetch and now.
            if row_exists(notion, data_source_id, e["date"].isoformat(), e["amount"], e["name"]):
                print(f"  ! Skipping (appeared since bulk fetch): {e['date']} ${e['amount']:.2f} {e['name']}")
                skipped_race += 1
                continue
            create_entry(notion, data_source_id, e)
            written += 1
            print(f"  + {e['date']}  ${e['amount']:8.2f}  {e['name']}")
        for r in refunds:
            page_id, match_count = find_matching_purchase(
                notion, data_source_id, r["name"], abs(r["amount"])
            )
            if not page_id:
                print(f"  ? Refund {r['date']} ${abs(r['amount']):.2f} {r['name']!r} — no matching purchase in Notion")
                unmatched_refunds += 1
                continue
            if match_count > 1:
                print(f"  ! Refund matches {match_count} purchases for {r['name']!r} ${abs(r['amount']):.2f}; marking most recent")
            mark_refunded(notion, page_id)
            archived += 1
            print(f"  ↻ Marked Refunded (refund {r['date']} ${abs(r['amount']):.2f}): {r['name']}")

    print("\n=== Summary ===")
    print(f"  Parsed:                {len(rows)} rows ({len(purchases)} purchases, {len(refunds)} refunds)")
    print(f"  Skipped payments:      {skipped_payments}")
    print(f"  Skipped exact dupes:   {skipped_dupes}")
    print(f"  Skipped (date+amount): {skipped_loose}")
    if not args.dry_run:
        print(f"  Skipped (race-check):  {skipped_race}")
        print(f"  Refunds marked:        {archived}")
        print(f"  Refunds unmatched:     {unmatched_refunds}")
    if args.dry_run:
        print(f"  Would write:           {len(new_entries)} (dry run)")
        print(f"  Would mark refunded:   {len(refunds)} refund(s) (dry run; matches not verified)")
    else:
        print(f"  Written:               {written}")
    if unmapped:
        print(f"\n  Unmapped merchants ({len(unmapped)}) — Category left blank:")
        for name, descs in sorted(unmapped.items()):
            print(f"    - {name}  (raw: {descs[0]})")
        print("\n  Add these to MERCHANT_RULES in import.py to auto-categorize next time.")


if __name__ == "__main__":
    main()
