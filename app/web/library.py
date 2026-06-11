"""Library view helpers: load and index saved outputs, handoffs, deliverables."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from storage import (
    list_deliverable_record_files,
    list_handoff_packet_files,
    list_specialist_output_files,
    load_deliverable_record,
    load_handoff_packet_json,
    load_specialist_output_json,
)
from web.timeutil import exact, relative, resolve_created


def _enum(v) -> str:
    return str(getattr(v, "value", v))


def _filter_sort(
    rows: list[dict], *, q: str, specialist: str, domain: str, sort: str
) -> list[dict]:
    def ok(r: dict) -> bool:
        if q and q.lower() not in f"{r['title']} {r.get('summary','')}".lower():
            return False
        if specialist and specialist != "all" and r.get("specialist") != specialist:
            return False
        if domain and domain != "all" and r.get("domain") != domain:
            return False
        return True

    out = [r for r in rows if ok(r)]
    out.sort(key=lambda r: r["_dt"], reverse=(sort != "old"))
    return out


def outputs(*, q="", specialist="all", domain="all", sort="new") -> list[dict]:
    rows = []
    for md in list_specialist_output_files():
        jp = md.with_suffix(".json")
        if not jp.exists():
            continue
        try:
            o = load_specialist_output_json(jp)
        except Exception:
            continue
        dt = resolve_created(getattr(o, "created_at", None), jp)
        rows.append(
            {"id": o.output_id, "title": o.title, "specialist": _enum(o.specialist_type),
             "domain": _enum(o.domain_type), "summary": o.summary,
             "_dt": dt or datetime.min, "rel": relative(dt), "exact": exact(dt)}
        )
    return _filter_sort(rows, q=q, specialist=specialist, domain=domain, sort=sort)


def handoffs(*, q="", specialist="all", domain="all", sort="new") -> list[dict]:
    rows = []
    for md in list_handoff_packet_files():
        jp = md.with_suffix(".json")
        if not jp.exists():
            continue
        try:
            h = load_handoff_packet_json(jp)
        except Exception:
            continue
        dt = resolve_created(None, jp)  # handoffs have no created_at field
        rows.append(
            {"id": h.handoff_id, "title": h.title, "specialist": _enum(h.specialist_type),
             "domain": _enum(h.domain_type), "summary": "",
             "_dt": dt or datetime.min, "rel": relative(dt), "exact": exact(dt)}
        )
    return _filter_sort(rows, q=q, specialist=specialist, domain=domain, sort=sort)


def deliverables(*, q="", sort="new") -> list[dict]:
    rows = []
    for jp in list_deliverable_record_files():
        try:
            d = load_deliverable_record(jp)
        except Exception:
            continue
        dt = resolve_created(getattr(d, "accepted_at", None), jp)
        rows.append(
            {"id": d.deliverable_id, "title": d.title, "filename": d.filename,
             "summary": "", "_dt": dt or datetime.min, "rel": relative(dt), "exact": exact(dt)}
        )
    if q:
        rows = [r for r in rows if q.lower() in f"{r['title']} {r['filename']}".lower()]
    rows.sort(key=lambda r: r["_dt"], reverse=(sort != "old"))
    return rows


def output_by_id(output_id: str):
    for md in list_specialist_output_files():
        jp = md.with_suffix(".json")
        if not jp.exists():
            continue
        try:
            o = load_specialist_output_json(jp)
        except Exception:
            continue
        if o.output_id == output_id:
            return o
    return None


def handoff_by_id(handoff_id: str):
    for md in list_handoff_packet_files():
        jp = md.with_suffix(".json")
        if not jp.exists():
            continue
        try:
            h = load_handoff_packet_json(jp)
        except Exception:
            continue
        if h.handoff_id == handoff_id:
            return h
    return None


def deliverable_by_id(deliverable_id: str):
    for jp in list_deliverable_record_files():
        try:
            d = load_deliverable_record(jp)
        except Exception:
            continue
        if d.deliverable_id == deliverable_id:
            return d
    return None
