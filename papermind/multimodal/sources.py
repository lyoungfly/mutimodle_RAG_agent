from urllib.parse import quote

from papermind.storage import DocumentStore


def asset_url(document_id: str, asset_id: str, collection: str) -> str:
    return (
        f"/documents/{document_id}/assets/{asset_id}?collection_id={quote(collection)}"
    )


def enrich_source(store: DocumentStore, source: dict, collection: str) -> dict:
    if source["content_type"] not in {"figure", "table"}:
        return source
    document = store.get(source["document_id"], collection)["body"]
    kind = source["content_type"]
    key = f"{kind}_id"
    item = next(
        (
            item
            for item in document[f"{kind}s"]
            if item[key] == source["metadata"].get(key)
        ),
        None,
    )
    if item:
        if kind == "table":
            offset = max(0, source["metadata"].get("row_index", 0) - 3)
            source[kind] = {
                **item,
                "rows": item["rows"][offset : offset + 20],
                "row_offset": offset,
                "total_rows": len(item["rows"]),
            }
        else:
            source[kind] = item
        if item.get("asset_id"):
            source["image_url"] = asset_url(
                source["document_id"], item["asset_id"], collection
            )
    return source
