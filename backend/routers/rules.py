"""
Rules router (P1 determinism).

Read-only view of the rule registry: every alert and notification rule
in the app, with its trigger, thresholds, action, size rule,
invalidation, expiry, cooldown, dedupe key, status, and source
function. Rules not in this registry cannot fire or notify.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/rules", tags=["Rules"])


def _serialize(row) -> dict:
    try:
        thresholds = json.loads(row.trigger_json or "{}")
    except Exception:
        thresholds = {}
    return {
        "rule_key": row.rule_key,
        "name": row.name,
        "category": row.category,
        "trigger": row.trigger_text,
        "thresholds": thresholds,
        "universe": row.universe,
        "action": row.action_template,
        "size_rule": row.size_rule,
        "size_fallback": row.size_fallback,
        "invalidation": row.invalidation,
        "expiry": row.expiry,
        "cooldown_days": row.cooldown_days,
        "dedupe_key_format": row.dedupe_key_format,
        "status": row.status,
        "source_function": row.source_function,
        "last_fired_at": row.last_fired_at.isoformat() if row.last_fired_at else None,
        "fired_count": row.fired_count,
    }


@router.get("")
def list_rules(db: Session = Depends(get_db)):
    from services.rule_registry import ensure_seeded, get_all_rules

    ensure_seeded(db)
    rows = get_all_rules(db)
    return {"rules": [_serialize(r) for r in rows], "count": len(rows)}


@router.get("/{rule_key}")
def get_rule(rule_key: str, db: Session = Depends(get_db)):
    from services.rule_registry import get_rule as _get_rule

    row = _get_rule(db, rule_key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_key}' not found in registry")
    return _serialize(row)
