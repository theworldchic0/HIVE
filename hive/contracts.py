"""Contract validation for Hive events — a tiny JSON-Schema subset validator (stdlib only).

Supported keywords: type (incl. list with null), required, properties, enum, pattern,
minimum, maximum, items. That's all the contracts in hive/contracts/ use. Keeping it dependency
free matters: the Hive must install on a fresh Windows/Mac machine with nothing but Python.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

CONTRACT_DIR = Path(__file__).resolve().parent / "contracts"

# event type -> schema file
EVENT_SCHEMAS = {
    "research.verdict": "research.verdict.schema.json",
    "fib.zone.entered": "fib.zone.schema.json",
    "fib.zone.exited": "fib.zone.schema.json",
    "fib.zone.observed": "fib.zone.schema.json",
    "trader.intent.created": "trader.event.schema.json",
    "trader.intent.rejected": "trader.event.schema.json",
    "trader.approval.requested": "trader.event.schema.json",
    "trader.trade.executed": "trader.event.schema.json",
    "trader.trade.failed": "trader.event.schema.json",
    "hive.control": "hive.control.schema.json",
    "research.request": "research.request.schema.json",
}
# free-form event types that are allowed without a schema (observability only)
FREEFORM_PREFIXES = ("trader.status", "trader.paused", "trader.resumed", "fib.structure", "fib.data_error",
                     "fib.learning", "queen.", "scout.", "bottom_blueprint_candidate")


class ContractError(ValueError):
    pass


@lru_cache(maxsize=None)
def schema(name: str) -> dict:
    return json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))


_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "number": (int, float), "integer": int, "null": type(None),
}


def _type_ok(value, t) -> bool:
    ts = t if isinstance(t, list) else [t]
    for one in ts:
        py = _TYPES[one]
        if one in ("number", "integer") and isinstance(value, bool):
            continue
        if isinstance(value, py):
            return True
    return False


def _check(value, sch: dict, path: str, errors: list):
    if "type" in sch and not _type_ok(value, sch["type"]):
        errors.append(f"{path}: expected {sch['type']}, got {type(value).__name__}")
        return
    if "enum" in sch and value not in sch["enum"]:
        errors.append(f"{path}: {value!r} not in {sch['enum']}")
    if isinstance(value, str) and "pattern" in sch and not re.search(sch["pattern"], value):
        errors.append(f"{path}: {value!r} does not match {sch['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in sch and value < sch["minimum"]:
            errors.append(f"{path}: {value} < minimum {sch['minimum']}")
        if "maximum" in sch and value > sch["maximum"]:
            errors.append(f"{path}: {value} > maximum {sch['maximum']}")
    if isinstance(value, dict):
        for req in sch.get("required", []):
            if req not in value:
                errors.append(f"{path}.{req}: required")
        for k, sub in sch.get("properties", {}).items():
            if k in value:
                _check(value[k], sub, f"{path}.{k}", errors)
    if isinstance(value, list) and "items" in sch:
        for i, item in enumerate(value):
            _check(item, sch["items"], f"{path}[{i}]", errors)


def errors_for(event_type: str, payload) -> list[str]:
    name = EVENT_SCHEMAS.get(event_type)
    if name is None:
        if event_type.startswith(FREEFORM_PREFIXES):
            return [] if isinstance(payload, dict) else ["payload must be an object"]
        return [f"unknown event type {event_type!r} (add it to hive/contracts.py)"]
    errs: list[str] = []
    _check(payload, schema(name), "payload", errs)
    # cross-field rules the schema subset can't express
    if event_type == "research.verdict" and isinstance(payload, dict) and not errs:
        exp = f"{str(payload['chain']).lower()}:{str(payload['contract']).lower()}"
        if payload["asset_id"] != exp:
            errs.append(f"payload.asset_id must equal '<chain>:<contract>' lowercase ({exp})")
    return errs


def validate(event_type: str, payload) -> None:
    errs = errors_for(event_type, payload)
    if errs:
        raise ContractError(f"{event_type} contract violation: " + "; ".join(errs))


def asset_id(chain: str, contract: str) -> str:
    return f"{chain.lower()}:{contract.lower()}"
