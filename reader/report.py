"""Generate a PDF expense report from the Notion expense database.

Usage:
    python -m reader.report --month 2026-04
    python -m reader.report --month 2026-04 -o ~/Desktop/april.pdf
    python -m reader.report --ytd                     # Jan 1 → today, current year
    python -m reader.report --start 2026-01-01 --end 2026-06-08
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


def default_output_path(slug):
    return DEFAULT_REPORT_DIR / f"expense-report-{slug}.pdf"


def fetch_rows(notion, data_source_id, start, end):
    """Fetch all expense rows with Date in [start, end] (inclusive)."""
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
    return rows


def fetch_month_rows(notion, data_source_id, year, month):
    """Fetch all rows in the given calendar month. Returns (rows, start, end)."""
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return fetch_rows(notion, data_source_id, start, end), start, end


def aggregate(rows):
    purchases = [r for r in rows if r["amount"] > 0]
    total = sum(r["amount"] for r in purchases)

    cat_totals = defaultdict(float)
    sub_totals = defaultdict(float)
    merchant_totals = defaultdict(float)
    month_totals = defaultdict(float)
    for r in purchases:
        cat_totals[r["category"] or "(Uncategorized)"] += r["amount"]
        sub_totals[r["subcategory"] or "(Unset)"] += r["amount"]
        merchant_totals[r["name"]] += r["amount"]
        month_totals[r["date"][:7]] += r["amount"]  # YYYY-MM

    cats_sorted = sorted(cat_totals.items(), key=lambda kv: -kv[1])
    subs_sorted = sorted(sub_totals.items(), key=lambda kv: -kv[1])
    top_merchants = sorted(merchant_totals.items(), key=lambda kv: -kv[1])[:TOP_N_MERCHANTS]
    months_sorted = sorted(month_totals.items())  # chronological

    return {
        "total": total,
        "n_purchases": len(purchases),
        "categories": cats_sorted,
        "subcategories": subs_sorted,
        "top_merchants": top_merchants,
        "months": months_sorted,
    }


def render_pdf(stats, start, end, output_path, title):
    # Add a monthly-trend row when the period spans more than one month.
    multi_month = len(stats["months"]) > 1
    n_rows = 4 if multi_month else 3
    height_ratios = [0.5, 1.4, 1.4] + ([1.0] if multi_month else [])
    fig = plt.figure(figsize=(11, 14 if not multi_month else 17))
    gs = fig.add_gridspec(n_rows, 2, height_ratios=height_ratios, hspace=0.45, wspace=0.25)

    # Header
    header_ax = fig.add_subplot(gs[0, :])
    header_ax.axis("off")
    header_ax.text(
        0.0, 0.95, title,
        fontsize=22, fontweight="bold", va="top",
    )
    avg = stats["total"] / len(stats["months"]) if stats["months"] else 0.0
    summary = (
        f"Period: {start.isoformat()} to {end.isoformat()}\n"
        f"Transactions: {stats['n_purchases']}\n"
        f"Total spend: ${stats['total']:,.2f}"
    )
    if multi_month:
        summary += f"\nAvg / month: ${avg:,.2f}  ({len(stats['months'])} months)"
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

    # Monthly trend (full width) — only for multi-month periods like YTD
    if multi_month:
        trend_ax = fig.add_subplot(gs[3, :])
        months = [m for m, _ in stats["months"]]
        values = [v for _, v in stats["months"]]
        trend_ax.bar(months, values, color="#4C78A8")
        trend_ax.set_title("Spend by Month", fontsize=13, fontweight="bold")
        trend_ax.set_ylabel("Amount ($)")
        for i, v in enumerate(values):
            trend_ax.text(i, v, f"${v:,.0f}", ha="center", va="bottom", fontsize=9)
        trend_ax.spines["top"].set_visible(False)
        trend_ax.spines["right"].set_visible(False)

    fig.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


def resolve_period(args):
    """Turn CLI args into (start, end, title, slug). Exits on bad input."""
    if args.month:
        try:
            year_s, month_s = args.month.split("-")
            year, month = int(year_s), int(month_s)
            if not (1 <= month <= 12):
                raise ValueError
        except ValueError:
            sys.exit(f"--month expects YYYY-MM, got: {args.month}")
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        return start, end, f"Expense Report — {start.strftime('%B %Y')}", args.month

    if args.ytd:
        today = date.today()
        start = date(today.year, 1, 1)
        return start, today, f"Expense Report — {today.year} YTD", f"YTD-{today.year}"

    # custom range
    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError:
        sys.exit("--start and --end expect YYYY-MM-DD")
    if end < start:
        sys.exit("--end must be on or after --start")
    title = f"Expense Report — {start.isoformat()} to {end.isoformat()}"
    return start, end, title, f"{start.isoformat()}_to_{end.isoformat()}"


def main():
    parser = argparse.ArgumentParser(
        description="Generate a PDF expense report from the Notion expense DB."
    )
    period = parser.add_mutually_exclusive_group(required=True)
    period.add_argument("--month", help="YYYY-MM, e.g. 2026-04")
    period.add_argument("--ytd", action="store_true",
                        help="Year-to-date: Jan 1 of the current year through today")
    period.add_argument("--start", help="Range start YYYY-MM-DD (use with --end)")
    parser.add_argument("--end", help="Range end YYYY-MM-DD (use with --start)")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output PDF path. Default: ./report/expense-report-<period>.pdf",
    )
    args = parser.parse_args()
    if bool(args.start) ^ bool(args.end):
        sys.exit("--start and --end must be used together")

    start, end, title, slug = resolve_period(args)

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        sys.exit("NOTION_TOKEN and NOTION_DATABASE_ID must be set in .env")

    output = args.output or default_output_path(slug)
    output.parent.mkdir(parents=True, exist_ok=True)

    notion = Client(auth=token)
    data_source_id = get_data_source_id(notion, db_id)

    print(f"Fetching expenses {start.isoformat()} → {end.isoformat()}…")
    rows = fetch_rows(notion, data_source_id, start, end)
    if not rows:
        sys.exit(f"No rows found for {start.isoformat()} → {end.isoformat()}.")
    print(f"  Found {len(rows)} rows.")

    stats = aggregate(rows)
    print(f"  Total spend: ${stats['total']:,.2f} across {stats['n_purchases']} purchases")

    print(f"Writing PDF: {output}")
    render_pdf(stats, start, end, output, title)
    print("Done.")


if __name__ == "__main__":
    main()
