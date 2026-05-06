"""Generate a monthly PDF expense report from the Notion expense database.

Usage:
    python -m reader.report --month 2026-04
    python -m reader.report --month 2026-04 -o ~/Desktop/april.pdf
"""

import argparse
import calendar
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from notion_client import Client

CACHE_DIR = Path(__file__).resolve().parent.parent / ".matplotlib-cache"
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_DIR))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reader import get_data_source_id


TOP_N_MERCHANTS = 10
DEFAULT_REPORT_DIR = Path("report")


def default_output_path(month):
    return DEFAULT_REPORT_DIR / f"expense-report-{month}.pdf"


def fetch_month_rows(notion, data_source_id, year, month):
    """Fetch all rows in the given calendar month. Returns (rows, start, end)."""
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])

    rows = []
    cursor = None
    while True:
        resp = notion.data_sources.query(
            data_source_id=data_source_id,
            filter={"and": [
                {"property": "Date", "date": {"on_or_after": start.isoformat()}},
                {"property": "Date", "date": {"on_or_before": end.isoformat()}},
            ]},
            start_cursor=cursor,
        )
        for page in resp["results"]:
            props = page["properties"]
            d = props.get("Date", {}).get("date", {}).get("start")
            amt = props.get("Amount", {}).get("number")
            title_arr = props.get("Name", {}).get("title", [])
            name = title_arr[0]["plain_text"] if title_arr else "(no name)"
            cat_obj = props.get("Category", {}).get("select")
            sub_obj = props.get("Subcategory", {}).get("select")
            if d and amt is not None:
                rows.append({
                    "date": d,
                    "amount": float(amt),
                    "name": name,
                    "category": cat_obj["name"] if cat_obj else None,
                    "subcategory": sub_obj["name"] if sub_obj else None,
                })
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return rows, start, end


def aggregate(rows):
    purchases = [r for r in rows if r["amount"] > 0]
    total = sum(r["amount"] for r in purchases)

    cat_totals = defaultdict(float)
    sub_totals = defaultdict(float)
    merchant_totals = defaultdict(float)
    for r in purchases:
        cat_totals[r["category"] or "(Uncategorized)"] += r["amount"]
        sub_totals[r["subcategory"] or "(Unset)"] += r["amount"]
        merchant_totals[r["name"]] += r["amount"]

    cats_sorted = sorted(cat_totals.items(), key=lambda kv: -kv[1])
    subs_sorted = sorted(sub_totals.items(), key=lambda kv: -kv[1])
    top_merchants = sorted(merchant_totals.items(), key=lambda kv: -kv[1])[:TOP_N_MERCHANTS]

    return {
        "total": total,
        "n_purchases": len(purchases),
        "categories": cats_sorted,
        "subcategories": subs_sorted,
        "top_merchants": top_merchants,
    }


def render_pdf(stats, start, end, output_path):
    fig = plt.figure(figsize=(11, 14))
    gs = fig.add_gridspec(3, 2, height_ratios=[0.5, 1.4, 1.4], hspace=0.45, wspace=0.25)

    # Header
    header_ax = fig.add_subplot(gs[0, :])
    header_ax.axis("off")
    header_ax.text(
        0.0, 0.95,
        f"Expense Report — {start.strftime('%B %Y')}",
        fontsize=22, fontweight="bold", va="top",
    )
    summary = (
        f"Period: {start.isoformat()} to {end.isoformat()}\n"
        f"Transactions: {stats['n_purchases']}\n"
        f"Total spend: ${stats['total']:,.2f}"
    )
    header_ax.text(0.0, 0.55, summary, fontsize=12, va="top", family="monospace")

    # Category bar (horizontal — better than pie for ~13 categories)
    cat_ax = fig.add_subplot(gs[1, 0])
    if stats["categories"]:
        labels = [k for k, _ in stats["categories"]]
        values = [v for _, v in stats["categories"]]
        # Reverse so the largest bar is on top.
        cat_ax.barh(labels[::-1], values[::-1], color="#4C78A8")
        cat_ax.set_title("Spend by Category", fontsize=13, fontweight="bold")
        cat_ax.set_xlabel("Amount ($)")
        for i, v in enumerate(values[::-1]):
            cat_ax.text(v, i, f"  ${v:,.0f}", va="center", fontsize=9)
        cat_ax.spines["top"].set_visible(False)
        cat_ax.spines["right"].set_visible(False)
    else:
        cat_ax.axis("off")

    # Subcategory pie (only ~3 values: Essential / Nonessential / Hawaii)
    sub_ax = fig.add_subplot(gs[1, 1])
    if stats["subcategories"]:
        labels = [k for k, _ in stats["subcategories"]]
        values = [v for _, v in stats["subcategories"]]
        colors = {"Essential": "#54A24B", "Nonessential": "#E45756", "Hawaii": "#F58518"}
        slice_colors = [colors.get(lbl, "#9D9D9D") for lbl in labels]
        sub_ax.pie(
            values, labels=labels, autopct="%1.1f%%", startangle=90,
            colors=slice_colors, textprops={"fontsize": 10},
        )
        sub_ax.set_title("Essential vs Nonessential", fontsize=13, fontweight="bold")
    else:
        sub_ax.axis("off")

    # Top merchants bar (full width)
    merch_ax = fig.add_subplot(gs[2, :])
    if stats["top_merchants"]:
        names = [m for m, _ in stats["top_merchants"]]
        values = [v for _, v in stats["top_merchants"]]
        merch_ax.barh(names[::-1], values[::-1], color="#72B7B2")
        merch_ax.set_title(f"Top {len(names)} Merchants by Spend", fontsize=13, fontweight="bold")
        merch_ax.set_xlabel("Amount ($)")
        for i, v in enumerate(values[::-1]):
            merch_ax.text(v, i, f"  ${v:,.2f}", va="center", fontsize=9)
        merch_ax.spines["top"].set_visible(False)
        merch_ax.spines["right"].set_visible(False)
    else:
        merch_ax.axis("off")

    fig.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a monthly PDF expense report from the Notion expense DB."
    )
    parser.add_argument("--month", required=True, help="YYYY-MM, e.g. 2026-04")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output PDF path. Default: ./report/expense-report-YYYY-MM.pdf",
    )
    args = parser.parse_args()

    try:
        year_s, month_s = args.month.split("-")
        year, month = int(year_s), int(month_s)
        if not (1 <= month <= 12):
            raise ValueError
    except ValueError:
        sys.exit(f"--month expects YYYY-MM, got: {args.month}")

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        sys.exit("NOTION_TOKEN and NOTION_DATABASE_ID must be set in .env")

    output = args.output or default_output_path(args.month)
    output.parent.mkdir(parents=True, exist_ok=True)

    notion = Client(auth=token)
    data_source_id = get_data_source_id(notion, db_id)

    print(f"Fetching {args.month} expenses…")
    rows, start, end = fetch_month_rows(notion, data_source_id, year, month)
    if not rows:
        sys.exit(f"No rows found in {args.month}.")
    print(f"  Found {len(rows)} rows.")

    stats = aggregate(rows)
    print(f"  Total spend: ${stats['total']:,.2f} across {stats['n_purchases']} purchases")

    print(f"Writing PDF: {output}")
    render_pdf(stats, start, end, output)
    print("Done.")


if __name__ == "__main__":
    main()
