"""Graph/lineage view helpers.

Builds initiative trees from ticket lineage (root → children) for a clean nested
HTML render. No external graph library — keeps the page light.
"""

from __future__ import annotations

from storage import list_ticket_json_files, load_ticket


def _enum(v) -> str:
    return str(getattr(v, "value", v))


def _load_all():
    by_id = {}
    children = {}
    roots = {}
    for path in list_ticket_json_files():
        try:
            env = load_ticket(path)
        except Exception:
            continue
        t = env.ticket
        by_id[t.ticket_id] = t
        if t.parent_ticket_id:
            children.setdefault(t.parent_ticket_id, []).append(t.ticket_id)
        rid = t.root_ticket_id or t.ticket_id
        roots.setdefault(rid, set()).add(t.ticket_id)
    return by_id, children, roots


def _node(t) -> dict:
    return {
        "id": t.ticket_id,
        "title": t.title,
        "status": _enum(t.status),
        "specialist": _enum(t.specialist_type),
        "domain": _enum(t.domain_type),
    }


def _subtree(tid: str, by_id: dict, children: dict, seen: set) -> dict | None:
    if tid in seen or tid not in by_id:
        return None
    seen.add(tid)
    node = _node(by_id[tid])
    node["children"] = [
        c for c in (_subtree(cid, by_id, children, seen) for cid in sorted(children.get(tid, [])))
        if c is not None
    ]
    return node


def initiatives() -> list[dict]:
    """Return one tree per initiative (root ticket), each a nested node dict."""
    by_id, children, roots = _load_all()
    trees = []
    for rid in roots:
        seen: set = set()
        tree = _subtree(rid, by_id, children, seen)
        if tree is None and rid in by_id:
            tree = _node(by_id[rid])
            tree["children"] = []
        if tree is not None:
            trees.append(tree)
    # Newest-ish first: by title for stability.
    trees.sort(key=lambda n: n["title"].lower())
    return trees
