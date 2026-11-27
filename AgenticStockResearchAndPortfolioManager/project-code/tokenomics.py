"""Read-side helpers for the Admin tokenomics panel. Plain code, no model call, no database access.

what_if   prices the same token totals on every known rate, so a provider switch can be judged before it is made.
call_tree orders usage rows as a tree from parent_id. Rows with no parent (or a parent that is not in the list) are roots.
"""
from __future__ import annotations


def what_if(tokens_in: int, tokens_out: int, rates: list[dict]) -> list[dict]:
    """Cost of the given token totals on each rate entry, cheapest first. A rate is never invented: only entries in `rates`."""
    rows = [{"provider": r["provider"], "model": r["model"],
             "cost": tokens_in * r["per_m_in"] / 1_000_000 + tokens_out * r["per_m_out"] / 1_000_000} for r in rates]
    return sorted(rows, key=lambda r: r["cost"])


def call_tree(rows: list[dict]) -> list[dict]:
    """Rows in tree order, each with a `depth`. Input order is kept among siblings. A cycle cannot loop forever."""
    ids = {r["id"] for r in rows}
    children: dict = {}
    for r in rows:
        parent = r.get("parent_id")
        children.setdefault(parent if parent in ids and parent != r["id"] else None, []).append(r)
    out, seen = [], set()

    def walk(node: dict, depth: int) -> None:
        if node["id"] in seen:
            return
        seen.add(node["id"])
        out.append({**node, "depth": depth})
        for child in children.get(node["id"], []):
            walk(child, depth + 1)

    for root in children.get(None, []):
        walk(root, 0)
    for r in rows:                                   # anything left is in a cycle: show it as a root, never drop it
        walk(r, 0)
    return out
