"""Read-side helpers: resolving the Notion data source ID and querying existing rows."""

import sys
from collections import defaultdict


def get_data_source_id(notion, database_id):
    """Notion API v2025-09-03+ requires a data_source_id (not database_id) for queries."""
    db = notion.databases.retrieve(database_id=database_id)
    sources = db.get("data_sources", [])
    if not sources:
        sys.exit(f"Database {database_id} has no data sources.")
    if len(sources) > 1:
        print(f"Warning: database has {len(sources)} data sources; using the first.")
    return sources[0]["id"]


def fetch_existing_keys(notion, data_source_id, start_date, end_date):
    """Bulk-fetch existing rows in date range.

    Returns:
      strict: set of (date_iso, amount_str, name)
      loose: dict from (date_iso, amount_str) → set of names already in DB
    """
    strict = set()
    loose = defaultdict(set)
    cursor = None
    while True:
        resp = notion.data_sources.query(
            data_source_id=data_source_id,
            filter={"and": [
                {"property": "Date", "date": {"on_or_after": start_date.isoformat()}},
                {"property": "Date", "date": {"on_or_before": end_date.isoformat()}},
            ]},
            start_cursor=cursor,
        )
        for page in resp["results"]:
            props = page["properties"]
            d = props.get("Date", {}).get("date", {}).get("start")
            amt = props.get("Amount", {}).get("number")
            title_arr = props.get("Name", {}).get("title", [])
            name = title_arr[0]["plain_text"] if title_arr else ""
            if d and amt is not None:
                amt_str = f"{amt:.2f}"
                strict.add((d, amt_str, name))
                loose[(d, amt_str)].add(name)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return strict, loose


def row_exists(notion, data_source_id, date_iso, amount, name):
    """Per-row safety check immediately before insert."""
    resp = notion.data_sources.query(
        data_source_id=data_source_id,
        filter={"and": [
            {"property": "Date", "date": {"equals": date_iso}},
            {"property": "Amount", "number": {"equals": round(amount, 2)}},
            {"property": "Name", "title": {"equals": name}},
        ]},
        page_size=1,
    )
    return len(resp.get("results", [])) > 0


def find_matching_purchase(notion, data_source_id, name, amount):
    """Find a Notion page representing the original purchase a refund corresponds to.
    Matches by exact Name and Amount. Returns (page_id, total_match_count).
    If multiple match, returns the most recent by Date.
    """
    resp = notion.data_sources.query(
        data_source_id=data_source_id,
        filter={"and": [
            {"property": "Amount", "number": {"equals": round(amount, 2)}},
            {"property": "Name", "title": {"equals": name}},
        ]},
        sorts=[{"property": "Date", "direction": "descending"}],
        page_size=10,
    )
    results = resp.get("results", [])
    if not results:
        return None, 0
    return results[0]["id"], len(results)
