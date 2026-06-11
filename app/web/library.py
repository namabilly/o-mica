"""Library view helpers: load and index saved outputs, handoffs, deliverables."""

from __future__ import annotations

from typing import Optional

from storage import (
    list_deliverable_record_files,
    list_handoff_packet_files,
    list_specialist_output_files,
    load_deliverable_record,
    load_handoff_packet_json,
    load_specialist_output_json,
)


def _enum(v) -> str:
    return str(getattr(v, "value", v))


def outputs() -> list[dict]:
    out = []
    for md in list_specialist_output_files():
        jp = md.with_suffix(".json")
        if not jp.exists():
            continue
        try:
            o = load_specialist_output_json(jp)
        except Exception:
            continue
        out.append(
            {"id": o.output_id, "title": o.title, "specialist": _enum(o.specialist_type),
             "domain": _enum(o.domain_type), "summary": o.summary}
        )
    return out


def handoffs() -> list[dict]:
    out = []
    for md in list_handoff_packet_files():
        jp = md.with_suffix(".json")
        if not jp.exists():
            continue
        try:
            h = load_handoff_packet_json(jp)
        except Exception:
            continue
        out.append(
            {"id": h.handoff_id, "title": h.title, "specialist": _enum(h.specialist_type),
             "domain": _enum(h.domain_type)}
        )
    return out


def deliverables() -> list[dict]:
    out = []
    for jp in list_deliverable_record_files():
        try:
            d = load_deliverable_record(jp)
        except Exception:
            continue
        out.append({"id": d.deliverable_id, "title": d.title, "filename": d.filename})
    return out


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
