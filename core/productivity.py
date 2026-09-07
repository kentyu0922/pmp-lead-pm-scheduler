# -*- coding: utf-8 -*-
"""
core/productivity.py — quantity → productivity → duration

Scope (V5-A): `suspended_ceiling`, `partition_framing`, `flooring`, `painting` — every
activity type declared in config/productivity_rates.json. Everything else keeps the
hard-coded template duration untouched. The two paths coexist via an activity-type switch:

  * task has `activity_type` (known in the rate library) + `quantity`
        → duration is computed here and the explainable breakdown is attached
          as task["productivity"], task["duration_method"] = "productivity_formula"
  * task has no `activity_type`
        → not touched (template / calibration duration stands)

Formula (integer workdays, per SKILL.md):
    rate                = rates_per_worker_day[rate_level]      (low | typical | high)
    daily_output        = rate × crew_size
    base_duration       = quantity / daily_output
    calculated_duration = base_duration × Π factors
    final_duration      = max(min_duration_days, ceil(calculated_duration))

Rates, rate-level tables and factor tables live only in config/productivity_rates.json
(single source, same rule as holidays / city permits). No live lookups, and no task-level
rate override: a task may choose *which* configured level applies (`rate_level`) but can
never supply its own rate — an LLM or a caller must not invent productivity or durations.
"""
import os
import json
import math
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RATES_PATH = os.path.join(BASE_DIR, "config", "productivity_rates.json")

METHOD_FORMULA = "productivity_formula"
METHOD_TEMPLATE = "template"

QTY_MEASURED = "measured"
QTY_DERIVED = "derived_from_area"

_DEFAULT_LEVELS = ["low", "medium", "high"]
_DEFAULT_RATE_LEVELS = ["low", "typical", "high"]
_DEFAULT_RATE_LEVEL = "typical"

# Task keys that would smuggle a rate past the config. They are ignored with a warning.
_FORBIDDEN_TASK_RATE_KEYS = ("productivity_rate", "rate_per_worker_day", "rates_per_worker_day", "daily_output")


def _rate_levels(rates: Dict[str, Any]) -> List[str]:
    return list(rates.get("rate_levels") or _DEFAULT_RATE_LEVELS)


def _default_rate_level(rates: Dict[str, Any]) -> str:
    return rates.get("default_rate_level") or _DEFAULT_RATE_LEVEL


def _rate_table(entry: Dict[str, Any], levels: Sequence[str], name: str) -> Dict[str, float]:
    """Normalise one activity's rate spec into {level: rate}.

    Preferred form is `rates_per_worker_day: {low, typical, high}`. A legacy scalar
    `rate_per_worker_day` is accepted and used for every level (no range information).
    """
    if "rates_per_worker_day" in entry:
        raw = entry["rates_per_worker_day"]
        if not isinstance(raw, dict):
            raise ValueError(f"{name}: rates_per_worker_day must be a map of level -> rate")
        missing = [lv for lv in levels if lv not in raw]
        if missing:
            raise ValueError(f"{name}: rates_per_worker_day missing level(s) {missing}; required {list(levels)}")
        table = {lv: float(raw[lv]) for lv in levels}
    elif "rate_per_worker_day" in entry:
        table = {lv: float(entry["rate_per_worker_day"]) for lv in levels}
    else:
        raise ValueError(f"{name}: no rates_per_worker_day / rate_per_worker_day in rate library")
    for lv, r in table.items():
        if not (r > 0):
            raise ValueError(f"{name}: rate for level '{lv}' must be > 0, got {r}")
    ordered = [table[lv] for lv in levels]
    if any(a > b for a, b in zip(ordered, ordered[1:])):
        raise ValueError(f"{name}: rates must be non-decreasing across levels {list(levels)}, got {ordered}")
    return table


def validate_rate_library(rates: Dict[str, Any]) -> None:
    """Structural check of the whole library. Raises ValueError on the first defect."""
    if "activity_types" not in rates or not isinstance(rates["activity_types"], dict):
        raise ValueError("productivity rates lack 'activity_types' map")
    levels = _rate_levels(rates)
    if _default_rate_level(rates) not in levels:
        raise ValueError(f"default_rate_level '{_default_rate_level(rates)}' not in rate_levels {levels}")
    for name, entry in rates["activity_types"].items():
        for k in ("unit", "default_crew_size", "min_duration_days", "factors"):
            if k not in entry:
                raise ValueError(f"{name}: missing '{k}'")
        _rate_table(entry, levels, name)
        if int(entry["default_crew_size"]) < 1:
            raise ValueError(f"{name}: default_crew_size must be >= 1")
        if int(entry["min_duration_days"]) < 1:
            raise ValueError(f"{name}: min_duration_days must be >= 1")
        for fname, table in entry["factors"].items():
            if not isinstance(table, dict) or not table:
                raise ValueError(f"{name}: factor table '{fname}' must be a non-empty map")
            for key, m in table.items():
                if not (float(m) > 0):
                    raise ValueError(f"{name}: factor {fname}.{key} must be > 0")
        bridge = entry.get("legacy_template_bridge")
        if bridge is not None:
            if not bridge.get("match_keywords"):
                raise ValueError(f"{name}: legacy_template_bridge needs match_keywords")
            if not (float(bridge.get("quantity_from_area_ratio", 1.0)) > 0):
                raise ValueError(f"{name}: legacy_template_bridge.quantity_from_area_ratio must be > 0")
            for fname, key in (bridge.get("factors") or {}).items():
                if fname not in entry["factors"] or key not in entry["factors"][fname]:
                    raise ValueError(f"{name}: legacy_template_bridge.factors {fname}={key!r} not in factor tables")


def load_productivity_rates(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and validate the rate library. Raises on missing/invalid file (fail loudly, no silent defaults)."""
    p = path or RATES_PATH
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    try:
        validate_rate_library(data)
    except ValueError as ex:
        raise ValueError(f"productivity rates file {p}: {ex}")
    return data


def bridged_activity_types(rates: Optional[Dict[str, Any]] = None) -> List[str]:
    """Activity types that can be applied to legacy templates (have a keyword bridge), config order."""
    rates = rates or load_productivity_rates()
    return [k for k, v in rates["activity_types"].items() if "legacy_template_bridge" in v]


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


def _final_days(qty: float, rate: float, crew: int, factor_product: float, min_days: int) -> int:
    calculated = qty / (rate * crew) * factor_product
    # round(…, 6) guards against float noise turning an exact 24.0 into 25 after ceil
    return max(min_days, int(math.ceil(round(calculated, 6))))


def compute_activity_duration(
    activity_type: str,
    quantity: float,
    crew_size: Optional[int] = None,
    factors: Optional[Dict[str, Any]] = None,
    rates: Optional[Dict[str, Any]] = None,
    quantity_source: str = QTY_MEASURED,
    rate_level: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute one activity's duration from quantity and productivity.

    Returns an explainable dict (quantity, unit, productivity_rate, rate_level, rate_table,
    crew_size, factors, calculated_duration, final_duration, duration_by_rate_level,
    confidence, ...). Raises ValueError on bad input or unknown activity type — callers
    decide whether to fall back to the template path.
    """
    rates = rates or load_productivity_rates()
    lib = rates["activity_types"]
    if activity_type not in lib:
        raise ValueError(f"activity_type '{activity_type}' not in rate library {sorted(lib)}")
    entry = lib[activity_type]
    levels = rates.get("confidence_levels") or _DEFAULT_LEVELS
    rate_levels = _rate_levels(rates)

    try:
        qty = float(quantity)
    except (TypeError, ValueError):
        raise ValueError(f"quantity must be numeric, got {quantity!r}")
    if not (qty > 0):
        raise ValueError(f"quantity must be > 0, got {qty}")

    table = _rate_table(entry, rate_levels, activity_type)
    level = rate_level or _default_rate_level(rates)
    if level not in table:
        raise ValueError(f"unknown rate_level '{level}'; allowed: {rate_levels}")
    rate = table[level]

    reasons: List[str] = []
    confidence = entry.get("base_confidence", "medium")
    if confidence not in levels:
        confidence = levels[0]
    reasons.append(f"base confidence from rate library = {confidence} ({activity_type} rate not yet field-calibrated)")
    if rate_level is None:
        reasons.append(f"rate_level not given → library default '{level}' ({rate:g} {entry.get('unit', '')}/worker-day)")
    else:
        reasons.append(f"rate_level pinned by task = '{level}' ({rate:g} {entry.get('unit', '')}/worker-day)")

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
    final = _final_days(qty, rate, crew, factor_product, min_days)
    by_level = {lv: _final_days(qty, table[lv], crew, factor_product, min_days) for lv in rate_levels}

    return {
        "method": METHOD_FORMULA,
        "activity_type": activity_type,
        "quantity": qty,
        "unit": entry.get("unit", ""),
        "quantity_source": quantity_source,
        "productivity_rate": rate,
        "productivity_unit": f"{entry.get('unit', '')}/worker-day",
        "rate_level": level,
        "rate_level_source": "task" if rate_level is not None else "default",
        "rate_table": table,
        "crew_size": crew,
        "crew_source": crew_source,
        "daily_output": round(daily_output, 4),
        "factors": multipliers,
        "factor_labels": labels,
        "factor_product": round(factor_product, 6),
        "base_duration": round(base_duration, 4),
        "calculated_duration": round(calculated, 4),
        "final_duration": final,
        "duration_by_rate_level": by_level,
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

    Unknown activity types / missing quantity / invalid factors / unknown rate_level do NOT
    raise: the task keeps its template duration and a warning is logged, so the legacy path
    is never broken by a half-tagged task. Task-level rate keys are ignored (config only).
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
        smuggled = [k for k in _FORBIDDEN_TASK_RATE_KEYS if k in t]
        if smuggled:
            log.warning(
                f"  -> [productivity] task {t.get('id')} '{t.get('name')}' carries task-level rate key(s) {smuggled}; "
                f"ignored — rates come only from config/productivity_rates.json (choose a level via rate_level instead)"
            )
        try:
            res = compute_activity_duration(
                atype,
                t["quantity"],
                crew_size=t.get("crew_size"),
                factors=t.get("factors"),
                rates=rates,
                quantity_source=t.get("quantity_source", QTY_MEASURED),
                rate_level=t.get("rate_level"),
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
        rng = res["duration_by_rate_level"]
        log.info(
            f"  -> [productivity] task {t.get('id')} '{t.get('name')}': {atype} "
            f"{res['quantity']:g}{res['unit']} ÷ ({res['productivity_rate']:g}{res['productivity_unit']}[{res['rate_level']}] × crew {res['crew_size']}) "
            f"× factors {res['factor_product']:g} = {res['calculated_duration']:g} → {res['final_duration']}d "
            f"(range by rate level {rng}; template was {prev}d; confidence={res['confidence']})"
        )
    if n_applied:
        log.info(f"  -> [productivity] formula path applied to {n_applied} task(s); all others keep template durations.")
    return tasks


def tag_legacy_pilot_tasks(
    tasks: List[Dict[str, Any]],
    area_sqm: float,
    activity_types: Union[str, Sequence[str]] = ("suspended_ceiling",),
    quantity_override: Optional[float] = None,
    rates: Optional[Dict[str, Any]] = None,
    log: Optional[logging.Logger] = None,
    quantity_overrides: Optional[Dict[str, float]] = None,
    rate_level: Optional[str] = None,
) -> List[int]:
    """Bridge for hard-coded WBS templates (opt-in, `--productivity_pilot`).

    Legacy tasks carry no quantity. For each requested activity type with a
    `legacy_template_bridge` in the rate library, leaf tasks whose name contains a
    match keyword are tagged with `activity_type` and a quantity — either the caller's
    measured value (`quantity_overrides[type]`, or `quantity_override` for every type)
    or gross area × ratio (flagged as derived). Bridge-level default factors (e.g. a
    composite legacy task) are copied onto the task so they show up in the explanation.
    `activity_types="all"` selects every bridged type in config order. Templates on disk
    are never modified. Returns the tagged task ids.
    """
    log = log or logger
    rates = rates or load_productivity_rates()
    if isinstance(activity_types, str):
        activity_types = bridged_activity_types(rates) if activity_types == "all" else [activity_types]
    overrides = dict(quantity_overrides or {})
    tagged: List[int] = []
    for atype in activity_types:
        entry = rates["activity_types"].get(atype)
        if not entry or "legacy_template_bridge" not in entry:
            log.warning(f"  -> [productivity] no legacy bridge for activity_type={atype}; nothing tagged")
            continue
        bridge = entry["legacy_template_bridge"]
        kws = bridge.get("match_keywords", [])
        ratio = float(bridge.get("quantity_from_area_ratio", 1.0))
        override = overrides.get(atype, quantity_override)
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
            if override is not None:
                t["quantity"] = float(override)
                t["quantity_source"] = QTY_MEASURED
            else:
                t["quantity"] = round(float(area_sqm) * ratio, 1)
                t["quantity_source"] = QTY_DERIVED
            if bridge.get("factors") and not t.get("factors"):
                t["factors"] = dict(bridge["factors"])
            if rate_level:
                t["rate_level"] = rate_level
            tagged.append(t["id"])
            log.info(
                f"  -> [productivity] pilot-tagged task {t['id']} '{name}' as {atype}: "
                f"quantity={t['quantity']:g}{t['unit']} ({t['quantity_source']})"
                + (f", factors={t['factors']}" if t.get("factors") else "")
                + (f", rate_level={rate_level}" if rate_level else "")
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
