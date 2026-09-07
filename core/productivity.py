# -*- coding: utf-8 -*-
"""
core/productivity.py — quantity → productivity → duration (pilot)

Pilot scope: ONE activity type (`suspended_ceiling`). Everything else keeps the
hard-coded template duration untouched. The two paths coexist via an
activity-type switch:

  * task has `activity_type` (known in config/productivity_rates.json) + `quantity`
        → duration is computed here and the explainable breakdown is attached
          as task["productivity"], task["duration_method"] = "productivity_formula"
  * task has no `activity_type`
        → not touched (template / calibration duration stands)

Formula (integer workdays, per SKILL.md):
    daily_output        = rate_per_worker_day × crew_size
    base_duration       = quantity / daily_output
    calculated_duration = base_duration × Π factors
    final_duration      = max(min_duration_days, ceil(calculated_duration))

Rates and factor tables live only in config/productivity_rates.json (single source,
same rule as holidays / city permits). No live lookups.
"""
import os
import json
import math
import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RATES_PATH = os.path.join(BASE_DIR, "config", "productivity_rates.json")

METHOD_FORMULA = "productivity_formula"
METHOD_TEMPLATE = "template"

QTY_MEASURED = "measured"
QTY_DERIVED = "derived_from_area"

_DEFAULT_LEVELS = ["low", "medium", "high"]


def load_productivity_rates(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the rate library. Raises on missing/invalid file (fail loudly, no silent defaults)."""
    p = path or RATES_PATH
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "activity_types" not in data or not isinstance(data["activity_types"], dict):
        raise ValueError(f"productivity rates file {p} lacks 'activity_types' map")
    return data


def _downgrade(level: str, levels: Sequence[str]) -> str:
    idx = list(levels).index(level) if level in levels else 0
    return levels[max(0, idx - 1)]


def _resolve_factors(spec: Dict[str, Any], tables: Dict[str, Dict[str, float]]):
    """Turn {name: key|multiplier} into ({name: multiplier}, {name: label}).

    Every factor table in config gets an entry (default 1.0 when unspecified) so the
    explanation always lists the full factor set, not just the ones the caller set.
    """
    spec = dict(spec or {})
    multipliers: Dict[str, float] = {}
    labels: Dict[str, str] = {}
    for name, table in tables.items():
        if name not in spec:
            multipliers[name] = 1.0
            labels[name] = "unspecified(1.0)"
            continue
        val = spec.pop(name)
        if isinstance(val, str):
            if val not in table:
                raise ValueError(f"unknown {name} factor key '{val}'; allowed: {sorted(table)}")
            multipliers[name] = float(table[val])
            labels[name] = val
        else:
            multipliers[name] = float(val)
            labels[name] = "custom"
    for name, val in spec.items():
        # ad-hoc numeric factor not in config tables
        if isinstance(val, str):
            raise ValueError(f"factor '{name}' is not in the rate library and has no numeric value")
        multipliers[name] = float(val)
        labels[name] = "custom"
    for name, m in multipliers.items():
        if not (m > 0):
            raise ValueError(f"factor '{name}' must be > 0, got {m}")
    return multipliers, labels


def compute_activity_duration(
    activity_type: str,
    quantity: float,
    crew_size: Optional[int] = None,
    factors: Optional[Dict[str, Any]] = None,
    rates: Optional[Dict[str, Any]] = None,
    quantity_source: str = QTY_MEASURED,
) -> Dict[str, Any]:
    """Compute one activity's duration from quantity and productivity.

    Returns an explainable dict (quantity, unit, productivity_rate, crew_size, factors,
    calculated_duration, final_duration, confidence, ...). Raises ValueError on bad input
    or unknown activity type — callers decide whether to fall back to the template path.
    """
    rates = rates or load_productivity_rates()
    lib = rates["activity_types"]
    if activity_type not in lib:
        raise ValueError(f"activity_type '{activity_type}' not in rate library {sorted(lib)}")
    entry = lib[activity_type]
    levels = rates.get("confidence_levels") or _DEFAULT_LEVELS

    try:
        qty = float(quantity)
    except (TypeError, ValueError):
        raise ValueError(f"quantity must be numeric, got {quantity!r}")
    if not (qty > 0):
        raise ValueError(f"quantity must be > 0, got {qty}")

    rate = float(entry["rate_per_worker_day"])
    if not (rate > 0):
        raise ValueError(f"rate_per_worker_day must be > 0 for {activity_type}")

    reasons: List[str] = []
    confidence = entry.get("base_confidence", "medium")
    if confidence not in levels:
        confidence = levels[0]
    reasons.append(f"base confidence from rate library = {confidence} ({activity_type} rate not yet field-calibrated)")

    if crew_size is None:
        crew = int(entry.get("default_crew_size", 1))
        crew_source = "default"
        confidence = _downgrade(confidence, levels)
        reasons.append(f"crew_size not given → default {crew} → confidence downgraded to {confidence}")
    else:
        crew = int(crew_size)
        crew_source = "task"
    if crew < 1:
        raise ValueError(f"crew_size must be >= 1, got {crew}")

    if quantity_source != QTY_MEASURED:
        confidence = _downgrade(confidence, levels)
        reasons.append(f"quantity is {quantity_source} (not measured takeoff) → confidence downgraded to {confidence}")

    multipliers, labels = _resolve_factors(factors or {}, entry.get("factors", {}))
    factor_product = 1.0
    for m in multipliers.values():
        factor_product *= m

    daily_output = rate * crew
    base_duration = qty / daily_output
    calculated = base_duration * factor_product
    min_days = int(entry.get("min_duration_days", 1))
    # round(…, 6) guards against float noise turning an exact 24.0 into 25 after ceil
    final = max(min_days, int(math.ceil(round(calculated, 6))))

    return {
        "method": METHOD_FORMULA,
        "activity_type": activity_type,
        "quantity": qty,
        "unit": entry.get("unit", ""),
        "quantity_source": quantity_source,
        "productivity_rate": rate,
        "productivity_unit": f"{entry.get('unit', '')}/worker-day",
        "crew_size": crew,
        "crew_source": crew_source,
        "daily_output": round(daily_output, 4),
        "factors": multipliers,
        "factor_labels": labels,
        "factor_product": round(factor_product, 6),
        "base_duration": round(base_duration, 4),
        "calculated_duration": round(calculated, 4),
        "final_duration": final,
        "min_duration_days": min_days,
        "rounding": "ceil_to_integer_workday_then_floor_at_min",
        "confidence": confidence,
        "confidence_reasons": reasons,
        "rates_version": rates.get("version", "unknown"),
    }


def apply_productivity_durations(
    tasks: List[Dict[str, Any]],
    rates: Optional[Dict[str, Any]] = None,
    log: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    """Activity-type switch. Tasks with `activity_type` + `quantity` get a formula duration
    and an explainable `productivity` block; all other tasks are returned untouched.

    Unknown activity types / missing quantity / invalid factors do NOT raise: the task keeps
    its template duration and a warning is logged, so the legacy path is never broken by a
    half-tagged task.
    """
    log = log or logger
    rates = rates or load_productivity_rates()
    n_applied = 0
    for t in tasks:
        atype = t.get("activity_type")
        if not atype:
            continue
        prev = int(round(float(t.get("duration_days", t.get("duration", 0)) or 0)))
        if t.get("quantity") is None:
            log.warning(f"  -> [productivity] task {t.get('id')} '{t.get('name')}' has activity_type={atype} but no quantity; keeping template duration {prev}d")
            continue
        try:
            res = compute_activity_duration(
                atype,
                t["quantity"],
                crew_size=t.get("crew_size"),
                factors=t.get("factors"),
                rates=rates,
                quantity_source=t.get("quantity_source", QTY_MEASURED),
            )
        except ValueError as ex:
            log.warning(f"  -> [productivity] task {t.get('id')} '{t.get('name')}': {ex}; keeping template duration {prev}d")
            continue
        res["template_duration"] = prev
        t["duration_days"] = res["final_duration"]
        t["duration"] = res["final_duration"]
        t["duration_method"] = METHOD_FORMULA
        t["productivity"] = res
        n_applied += 1
        log.info(
            f"  -> [productivity] task {t.get('id')} '{t.get('name')}': {atype} "
            f"{res['quantity']:g}{res['unit']} ÷ ({res['productivity_rate']:g}{res['productivity_unit']} × crew {res['crew_size']}) "
            f"× factors {res['factor_product']:g} = {res['calculated_duration']:g} → {res['final_duration']}d "
            f"(template was {prev}d; confidence={res['confidence']})"
        )
    if n_applied:
        log.info(f"  -> [productivity] formula path applied to {n_applied} task(s); all others keep template durations.")
    return tasks


def tag_legacy_pilot_tasks(
    tasks: List[Dict[str, Any]],
    area_sqm: float,
    activity_types: Sequence[str] = ("suspended_ceiling",),
    quantity_override: Optional[float] = None,
    rates: Optional[Dict[str, Any]] = None,
    log: Optional[logging.Logger] = None,
) -> List[int]:
    """Bridge for hard-coded WBS templates (opt-in, `--productivity_pilot`).

    Legacy tasks carry no quantity. For each pilot activity type with a
    `legacy_template_bridge` in the rate library, leaf tasks whose name contains a
    match keyword are tagged with `activity_type` and a quantity — either the caller's
    measured value (`quantity_override`) or gross area × ratio (flagged as derived).
    Templates on disk are never modified. Returns the tagged task ids.
    """
    log = log or logger
    rates = rates or load_productivity_rates()
    tagged: List[int] = []
    for atype in activity_types:
        entry = rates["activity_types"].get(atype)
        if not entry or "legacy_template_bridge" not in entry:
            log.warning(f"  -> [productivity] no legacy bridge for activity_type={atype}; nothing tagged")
            continue
        bridge = entry["legacy_template_bridge"]
        kws = bridge.get("match_keywords", [])
        ratio = float(bridge.get("quantity_from_area_ratio", 1.0))
        for t in tasks:
            if t.get("activity_type") or t.get("milestone"):
                continue
            if int(t.get("outline_level", t.get("level", 3))) < 3:
                continue
            if not (float(t.get("duration_days", t.get("duration", 0)) or 0) > 0):
                continue
            name = str(t.get("name", ""))
            if not any(k in name for k in kws):
                continue
            t["activity_type"] = atype
            t["unit"] = entry.get("unit", "")
            if quantity_override is not None:
                t["quantity"] = float(quantity_override)
                t["quantity_source"] = QTY_MEASURED
            else:
                t["quantity"] = round(float(area_sqm) * ratio, 1)
                t["quantity_source"] = QTY_DERIVED
            tagged.append(t["id"])
            log.info(
                f"  -> [productivity] pilot-tagged task {t['id']} '{name}' as {atype}: "
                f"quantity={t['quantity']:g}{t['unit']} ({t['quantity_source']})"
            )
    return tagged


def productivity_summary(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Explainable rows for every formula-path task (for logs / sidecar JSON)."""
    rows = []
    for t in tasks:
        if t.get("duration_method") == METHOD_FORMULA and t.get("productivity"):
            row = {"id": t.get("id"), "name": t.get("name"),
                   "start": t.get("start"), "finish": t.get("finish"),
                   "critical": t.get("critical"), "total_slack_days": t.get("total_slack_days")}
            row.update(t["productivity"])
            rows.append(row)
    return rows
