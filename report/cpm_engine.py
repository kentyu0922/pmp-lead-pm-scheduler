"""Deterministic Critical Path Method engine.

Durations are expressed in working days. The schedule is solved with Kahn's
topological sort followed by a forward pass (ES/EF) and backward pass (LS/LF).
Circular dependencies are rejected up front so the passes can never loop.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass
class Task:
    id: str
    wbs: str
    name_zh: str
    name_en: str
    phase: str
    duration: int
    predecessors: List[str] = field(default_factory=list)
    trade: str = ""
    milestone: bool = False
    risk_ids: List[str] = field(default_factory=list)

    # CPM results (working-day offsets from project start; EF/LF are exclusive)
    es: int = 0
    ef: int = 0
    ls: int = 0
    lf: int = 0
    total_float: int = 0
    free_float: int = 0
    critical: bool = False

    # Calendar dates (filled by WorkCalendar)
    start: Optional[date] = None
    finish: Optional[date] = None


class CyclicDependencyError(ValueError):
    pass


class WorkCalendar:
    """Working-day calendar with configurable weekend and holiday set."""

    def __init__(self, project_start: date, workdays: Sequence[int] = (0, 1, 2, 3, 4, 5),
                 holidays: Iterable[date] = ()):
        self.project_start = project_start
        self.workdays = set(workdays)
        self.holidays = set(holidays)
        self._cache: Dict[int, date] = {}

    def is_workday(self, d: date) -> bool:
        return d.weekday() in self.workdays and d not in self.holidays

    def offset_to_date(self, offset: int) -> date:
        """Date of the working day `offset` days after the project start (0 = first workday)."""
        if offset in self._cache:
            return self._cache[offset]
        d = self.project_start
        while not self.is_workday(d):
            d += timedelta(days=1)
        remaining = offset
        while remaining > 0:
            d += timedelta(days=1)
            if self.is_workday(d):
                remaining -= 1
        self._cache[offset] = d
        return d

    def finish_date(self, ef: int, duration: int) -> date:
        """Inclusive finish date. Milestones (duration 0) finish on their start day."""
        if duration == 0:
            return self.offset_to_date(ef)
        return self.offset_to_date(ef - 1)


def topological_order(tasks: Dict[str, Task]) -> List[str]:
    """Kahn's algorithm. Ties are broken by WBS code so output is deterministic."""
    indeg = {tid: 0 for tid in tasks}
    successors: Dict[str, List[str]] = {tid: [] for tid in tasks}
    for t in tasks.values():
        for p in t.predecessors:
            if p not in tasks:
                raise KeyError(f"Task {t.id} references unknown predecessor {p}")
            successors[p].append(t.id)
            indeg[t.id] += 1

    ready = sorted((tid for tid, d in indeg.items() if d == 0), key=lambda x: tasks[x].wbs)
    queue = deque(ready)
    order: List[str] = []
    while queue:
        tid = queue.popleft()
        order.append(tid)
        newly_ready = []
        for s in successors[tid]:
            indeg[s] -= 1
            if indeg[s] == 0:
                newly_ready.append(s)
        for s in sorted(newly_ready, key=lambda x: tasks[x].wbs):
            queue.append(s)

    if len(order) != len(tasks):
        stuck = sorted(tid for tid, d in indeg.items() if d > 0)
        raise CyclicDependencyError(f"Circular dependency detected among: {', '.join(stuck)}")
    return order


@dataclass
class Schedule:
    tasks: Dict[str, Task]
    order: List[str]
    calendar: WorkCalendar
    project_duration: int

    @property
    def ordered_tasks(self) -> List[Task]:
        return [self.tasks[t] for t in sorted(self.tasks, key=lambda x: _wbs_key(self.tasks[x].wbs))]

    @property
    def critical_tasks(self) -> List[Task]:
        return [t for t in self.ordered_tasks if t.critical]

    @property
    def project_finish(self) -> date:
        return self.calendar.offset_to_date(max(1, self.project_duration) - 1)

    @property
    def project_start(self) -> date:
        return self.calendar.offset_to_date(0)

    def critical_chain(self) -> List[Task]:
        """One explicit critical chain from start to finish (deterministic driver selection)."""
        crit = {t.id for t in self.tasks.values() if t.critical}
        successors: Dict[str, List[str]] = {tid: [] for tid in self.tasks}
        for t in self.tasks.values():
            for p in t.predecessors:
                successors[p].append(t.id)

        # Start from the critical task with ES == 0 and walk driving successors.
        starts = sorted((t for t in self.tasks.values() if t.critical and t.es == 0),
                        key=lambda t: _wbs_key(t.wbs))
        if not starts:
            return []
        chain = [starts[0]]
        seen = {starts[0].id}
        while True:
            cur = chain[-1]
            nxt = [self.tasks[s] for s in successors[cur.id]
                   if s in crit and self.tasks[s].es == cur.ef and s not in seen]
            if not nxt:
                break
            nxt.sort(key=lambda t: (-t.duration, _wbs_key(t.wbs)))
            chain.append(nxt[0])
            seen.add(nxt[0].id)
        return chain


def _wbs_key(wbs: str):
    return tuple(int(p) if p.isdigit() else p for p in wbs.split("."))


def solve(task_list: Sequence[Task], calendar: WorkCalendar) -> Schedule:
    tasks = {t.id: t for t in task_list}
    order = topological_order(tasks)

    successors: Dict[str, List[str]] = {tid: [] for tid in tasks}
    for t in tasks.values():
        for p in t.predecessors:
            successors[p].append(t.id)

    # Forward pass
    for tid in order:
        t = tasks[tid]
        t.es = max((tasks[p].ef for p in t.predecessors), default=0)
        t.ef = t.es + t.duration
    project_duration = max(t.ef for t in tasks.values())

    # Backward pass
    for tid in reversed(order):
        t = tasks[tid]
        t.lf = min((tasks[s].ls for s in successors[tid]), default=project_duration)
        t.ls = t.lf - t.duration
        t.total_float = t.ls - t.es
        succ_es = min((tasks[s].es for s in successors[tid]), default=project_duration)
        t.free_float = succ_es - t.ef
        t.critical = t.total_float == 0

    for t in tasks.values():
        if t.milestone and t.es > 0:
            # A milestone reached at offset N is achieved at the end of working day N-1.
            t.start = t.finish = calendar.offset_to_date(t.es - 1)
        else:
            t.start = calendar.offset_to_date(t.es)
            t.finish = calendar.finish_date(t.ef, t.duration)

    return Schedule(tasks=tasks, order=order, calendar=calendar, project_duration=project_duration)


def phases(schedule: Schedule) -> List[str]:
    seen: List[str] = []
    for t in schedule.ordered_tasks:
        if t.phase not in seen:
            seen.append(t.phase)
    return seen


def phase_summary(schedule: Schedule) -> List[dict]:
    out = []
    for ph in phases(schedule):
        ts = [t for t in schedule.ordered_tasks if t.phase == ph]
        es = min(t.es for t in ts)
        ef = max(t.ef for t in ts)
        out.append({
            "phase": ph,
            "tasks": len(ts),
            "critical": sum(1 for t in ts if t.critical and not t.milestone),
            "es": es,
            "ef": ef,
            "start": schedule.calendar.offset_to_date(es),
            "finish": schedule.calendar.finish_date(ef, ef - es),
            "span": ef - es,
            "work": sum(t.duration for t in ts),
            "critical_days": sum(t.duration for t in ts if t.critical),
        })
    return out
