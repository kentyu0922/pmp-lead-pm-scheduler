"""Schedule risk analytics built on top of the deterministic CPM baseline.

Everything here is reproducible: the Monte Carlo simulation uses a fixed seed
so the report renders identically on every run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

import numpy as np

from .cpm_engine import Schedule, Task
from .sample_project import Risk

MC_SEED = 20260904
MC_ITERATIONS = 5000

FLOAT_BUCKETS = [
    ("0", 0, 0),
    ("1–3", 1, 3),
    ("4–7", 4, 7),
    ("8–14", 8, 14),
    ("15+", 15, 10**6),
]


def float_distribution(schedule: Schedule) -> List[dict]:
    tasks = [t for t in schedule.ordered_tasks if not t.milestone]
    out = []
    for label, lo, hi in FLOAT_BUCKETS:
        n = sum(1 for t in tasks if lo <= t.total_float <= hi)
        out.append({"label": label, "count": n, "share": n / len(tasks) if tasks else 0.0})
    return out


def near_critical(schedule: Schedule, threshold: int = 3) -> List[Task]:
    return [t for t in schedule.ordered_tasks if 0 < t.total_float <= threshold and not t.milestone]


@dataclass
class MonteCarloResult:
    iterations: int
    durations: np.ndarray           # project duration per iteration (working days)
    p50: float
    p80: float
    p90: float
    mean: float
    deterministic: int
    criticality: Dict[str, float]   # task id -> share of iterations on critical path
    on_time_probability: float      # P(finish <= deterministic duration)

    def probability_by(self, duration: float) -> float:
        return float(np.mean(self.durations <= duration))


def _risk_uplift(task: Task, risks: Dict[str, Risk]) -> float:
    """Extra pessimistic days injected by risks linked to the task (probability-weighted)."""
    return sum(risks[r].delay_days * risks[r].probability / 5.0 for r in task.risk_ids if r in risks)


def monte_carlo(schedule: Schedule, risks: Sequence[Risk], iterations: int = MC_ITERATIONS,
                seed: int = MC_SEED) -> MonteCarloResult:
    rng = np.random.default_rng(seed)
    rmap = {r.id: r for r in risks}
    tasks = schedule.tasks
    order = schedule.order

    successors: Dict[str, List[str]] = {tid: [] for tid in tasks}
    for t in tasks.values():
        for p in t.predecessors:
            successors[p].append(t.id)

    dur: Dict[str, np.ndarray] = {}
    for tid in order:
        t = tasks[tid]
        if t.duration == 0:
            dur[tid] = np.zeros(iterations)
            continue
        lo = t.duration * 0.85
        hi = t.duration * 1.10 + _risk_uplift(t, rmap)
        dur[tid] = rng.triangular(lo, t.duration, hi, size=iterations)

    es: Dict[str, np.ndarray] = {}
    ef: Dict[str, np.ndarray] = {}
    for tid in order:
        t = tasks[tid]
        if t.predecessors:
            es[tid] = np.max(np.stack([ef[p] for p in t.predecessors]), axis=0)
        else:
            es[tid] = np.zeros(iterations)
        ef[tid] = es[tid] + dur[tid]
    total = np.max(np.stack([ef[tid] for tid in order]), axis=0)

    lf: Dict[str, np.ndarray] = {}
    ls: Dict[str, np.ndarray] = {}
    for tid in reversed(order):
        succ = successors[tid]
        lf[tid] = np.min(np.stack([ls[s] for s in succ]), axis=0) if succ else total
        ls[tid] = lf[tid] - dur[tid]

    criticality = {tid: float(np.mean(np.abs(ls[tid] - es[tid]) < 1e-6)) for tid in order}

    return MonteCarloResult(
        iterations=iterations,
        durations=total,
        p50=float(np.percentile(total, 50)),
        p80=float(np.percentile(total, 80)),
        p90=float(np.percentile(total, 90)),
        mean=float(total.mean()),
        deterministic=schedule.project_duration,
        criticality=criticality,
        on_time_probability=float(np.mean(total <= schedule.project_duration + 1e-9)),
    )


def s_curve(result: MonteCarloResult, points: int = 60):
    xs = np.linspace(result.durations.min(), result.durations.max(), points)
    ys = np.array([np.mean(result.durations <= x) for x in xs])
    return xs, ys


def risk_exposure(risks: Sequence[Risk], schedule: Schedule) -> List[dict]:
    """Probability-weighted schedule exposure per risk, with CPM context of linked tasks."""
    out = []
    for r in risks:
        linked = [schedule.tasks[t] for t in r.task_ids if t in schedule.tasks]
        min_float = min((t.total_float for t in linked), default=0)
        on_critical = any(t.critical for t in linked)
        # Delay only propagates to the finish once it exceeds the smallest float available.
        propagated = max(0, r.delay_days - min_float)
        out.append({
            "risk": r,
            "linked": linked,
            "min_float": min_float,
            "on_critical": on_critical,
            "expected_delay": r.delay_days * r.probability / 5.0,
            "propagated_delay": propagated,
            "expected_propagated": propagated * r.probability / 5.0,
        })
    out.sort(key=lambda d: (-d["risk"].score, -d["expected_propagated"], d["risk"].id))
    return out


def phase_exposure(exposure: List[dict], schedule: Schedule) -> Dict[str, float]:
    by_phase: Dict[str, float] = {}
    for e in exposure:
        phases = {t.phase for t in e["linked"]} or {"P1"}
        for ph in phases:
            by_phase[ph] = by_phase.get(ph, 0.0) + e["expected_delay"] / len(phases)
    return by_phase
