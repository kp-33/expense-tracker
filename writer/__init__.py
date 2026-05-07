"""Write-side helpers: building Notion property payloads and creating expense pages."""


def create_entry(notion, data_source_id, entry):
    """Insert one expense row.

    entry is a dict with keys: name, amount, date (date object), category, subcategory.
    Category/Subcategory are omitted from the payload when None (leaves the cell blank).
    """
    props = {
        "Name": {"title": [{"text": {"content": entry["name"]}}]},
        "Amount": {"number": round(entry["amount"], 2)},
        "Date": {"date": {"start": entry["date"].isoformat()}},
    }
    if entry.get("category"):
        props["Category"] = {"select": {"name": entry["category"]}}
    if entry.get("subcategory"):
        props["Subcategory"] = {"select": {"name": entry["subcategory"]}}
    notion.pages.create(parent={"data_source_id": data_source_id}, properties=props)


def archive_entry(notion, page_id):
    """Soft-delete a Notion page (Notion API has no hard-delete in v1)."""
    notion.pages.update(page_id=page_id, archived=True)


def mark_refunded(notion, page_id):
    """Mark an existing expense row as refunded by setting Status=Refunded.
    Preserves the original row for audit; nothing is deleted."""
    notion.pages.update(
        page_id=page_id,
        properties={"Status": {"select": {"name": "Refunded"}}},
    )


def ensure_subcategory_options(notion, data_source_id, names):
    """Add any missing names to the Subcategory select options.
    Returns the list of names that were newly added."""
    ds = notion.data_sources.retrieve(data_source_id=data_source_id)
    sub_prop = ds["properties"].get("Subcategory", {})
    current = sub_prop.get("select", {}).get("options", [])
    current_names = {o["name"] for o in current}
    missing = [n for n in names if n not in current_names]
    if not missing:
        return []
    new_options = current + [{"name": n} for n in missing]
    notion.data_sources.update(
        data_source_id=data_source_id,
        properties={"Subcategory": {"select": {"options": new_options}}},
    )
    return missing
