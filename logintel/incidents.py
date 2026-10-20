"""Incident grouping by service, time window and log pattern, with rule-based root-cause hints.

IMPORTANT: hypotheses are heuristics (earliest anomalous activity + keyword categories).
They suggest where to look first; they are not causal proof.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

import pandas as pd

from .config import LEVEL_ORDER
from .logging_setup import get_logger

log = get_logger("incidents")

CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("resource/memory", re.compile(r"out ?of ?memory|oom|heap|gc pause|memory", re.I)),
    ("resource/disk", re.compile(r"no space|disk|inode|i/o error|checkpoint failed", re.I)),
    ("database", re.compile(r"connection pool|pool exhausted|deadlock|slow query|\bsql\b|\bdb\b|database", re.I)),
    ("auth/security", re.compile(r"failed login|authentication failed|unauthori[sz]ed|forbidden|invalid token|locked|brute", re.I)),
    ("network/timeout", re.compile(r"timeout|timed out|connection refused|unreachable|reset by peer|\bdns\b", re.I)),
    ("upstream/dependency", re.compile(r"upstream|\b50[234]\b|bad gateway|circuit breaker|unavailable", re.I)),
    ("crash/exception", re.compile(r"exception|traceback|segfault|panic|fatal|restarting", re.I)),
]


def infer_category(messages: list[str]) -> str:
    votes: Counter[str] = Counter()
    for m in messages:
        for cat, rx in CATEGORY_RULES:
            if rx.search(m):
                votes[cat] += 1
                break
    return votes.most_common(1)[0][0] if votes else "unclassified"


@dataclass
class Incident:
    group_id: int
    rank_in_group: int
    service: str
    start: str
    end: str
    n_events: int
    max_score: float
    max_level: str
    category: str
    top_templates: list[list[object]] = field(default_factory=list)
    hypothesis: str = ""
    signature: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class IncidentGrouper:
    def __init__(self, gap_seconds: int = 120, group_gap_seconds: int = 120, min_events: int = 3) -> None:
        self.gap = pd.Timedelta(seconds=gap_seconds)
        self.group_gap = pd.Timedelta(seconds=group_gap_seconds)
        # Episodes with fewer anomalous events are treated as isolated alerts, not incidents:
        # scattered false positives would otherwise chain into spurious multi-service "incidents".
        self.min_events = max(1, min_events)

    def group(self, flagged: pd.DataFrame) -> list[Incident]:
        """`flagged`: columns timestamp, service, level, message, template, score (anomalous rows only)."""
        dated = flagged[flagged["timestamp"].notna()].copy()
        skipped = len(flagged) - len(dated)
        if skipped:
            log.warning("undated anomalies skipped from incident grouping", extra={"count": skipped})
        if dated.empty:
            return []
        episodes: list[dict[str, object]] = []
        for svc, sub in dated.sort_values("timestamp").groupby("service"):
            ep = (sub["timestamp"].diff() > self.gap).cumsum()
            for _, part in sub.groupby(ep):
                if len(part) < self.min_events:
                    continue
                tpl = Counter(part["template"]).most_common(3)
                episodes.append({
                    "service": str(svc), "start": part["timestamp"].min(), "end": part["timestamp"].max(),
                    "n": len(part), "max_score": float(part["score"].max()),
                    "max_level": max(part["level"], key=lambda l: LEVEL_ORDER.get(l, 2)),
                    "category": infer_category(part["message"].tolist()),
                    "top_templates": [[t, c] for t, c in tpl],
                })
        if not episodes:
            return []
        episodes.sort(key=lambda e: (e["start"], -int(e["n"])))  # type: ignore[arg-type,operator]
        groups: list[list[dict[str, object]]] = []
        group_end = None
        for ep in episodes:
            if group_end is not None and ep["start"] <= group_end + self.group_gap:  # type: ignore[operator]
                groups[-1].append(ep)
                group_end = max(group_end, ep["end"])  # type: ignore[type-var]
            else:
                groups.append([ep])
                group_end = ep["end"]
        incidents: list[Incident] = []
        for gid, members in enumerate(groups, start=1):
            origin = members[0]
            for rank, ep in enumerate(members, start=1):
                incidents.append(Incident(
                    group_id=gid, rank_in_group=rank, service=str(ep["service"]),
                    start=ep["start"].isoformat(), end=ep["end"].isoformat(),  # type: ignore[attr-defined]
                    n_events=int(ep["n"]), max_score=round(float(ep["max_score"]), 4),  # type: ignore[arg-type]
                    max_level=str(ep["max_level"]), category=str(ep["category"]),
                    top_templates=ep["top_templates"],  # type: ignore[arg-type]
                    hypothesis=self._hypothesis(rank, ep, origin, members),
                    signature=f"{ep['service']}|{ep['top_templates'][0][0]}",  # type: ignore[index]
                ))
        return incidents

    @staticmethod
    def _hypothesis(rank: int, ep: dict[str, object], origin: dict[str, object],
                    members: list[dict[str, object]]) -> str:
        top = ep["top_templates"][0][0]  # type: ignore[index]
        if len(members) == 1:
            return (f"Isolated anomaly cluster in '{ep['service']}' (category hint: {ep['category']}). "
                    f"Dominant pattern: \"{top}\". No correlated anomalies in other services.")
        if rank == 1:
            others = ", ".join(sorted({str(m["service"]) for m in members[1:]} - {str(ep["service"])})) or "the same service"

            return (f"Candidate origin: '{ep['service']}' showed the earliest anomalous activity "
                    f"(category hint: {ep['category']}); dominant pattern \"{top}\". "
                    f"Later anomalies in: {others}. Heuristic ordering only - verify before acting.")
        lag = (ep["start"] - origin["start"]).total_seconds()  # type: ignore[operator]
        return (f"Possible downstream effect: '{ep['service']}' began {lag:.0f}s after '{origin['service']}' "
                f"(category hint: {ep['category']}); dominant pattern \"{top}\".")
