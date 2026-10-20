"""Safe synthetic log generator with injected, labelled incident scenarios.

No real data is used. Design choices that keep evaluation honest:
- benign ERROR/WARN messages exist (label 0) so a level filter is not trivially perfect;
- some anomalous messages are logged at INFO/WARN (subtle) so a level filter misses them;
- benign traffic bursts exist (label 0);
- the second half of the timeline contains one scenario ('disk_full') never present in the
  first half, so chronological train/test splits probe generalisation to a novel failure type.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SERVICES = ["gateway", "auth", "payment", "inventory", "db"]

NORMAL: dict[str, list[tuple[str, str]]] = {
    "gateway": [("INFO", "GET /api/orders/{n} 200 in {ms}ms"), ("INFO", "POST /api/checkout 201 in {ms}ms"),
                ("DEBUG", "routing request {uuid} to service payment"), ("INFO", "health check ok from {ip}")],
    "auth": [("INFO", "user user_{n} logged in from {ip}"), ("INFO", "token issued for user_{n} ttl={n}s"),
             ("DEBUG", "session {uuid} refreshed")],
    "payment": [("INFO", "payment {uuid} authorised amount={n}"), ("INFO", "payment {uuid} captured in {ms}ms"),
                ("DEBUG", "calling card processor for order {n}")],
    "inventory": [("INFO", "stock level checked sku_{n} qty={n}"), ("INFO", "reservation {uuid} created"),
                  ("DEBUG", "cache hit for sku_{n}")],
    "db": [("INFO", "query executed in {ms}ms rows={n}"), ("DEBUG", "connection pool active={n} max=100"),
           ("INFO", "checkpoint completed in {ms}ms")],
}
BENIGN_NOISE: dict[str, list[tuple[str, str]]] = {
    "gateway": [("WARN", "retrying request {uuid} attempt 1 of 3 succeeded"), ("ERROR", "GET /api/orders/{n} 404 order not found")],
    "auth": [("ERROR", "validation failed for field email on registration of user_{n}"), ("WARN", "password reset requested for user_{n}")],
    "payment": [("WARN", "card declined for payment {uuid} reason=insufficient_funds"), ("ERROR", "validation failed for field amount order {n}")],
    "inventory": [("WARN", "cache miss for sku_{n} reloading from db")],
    "db": [("WARN", "slow query tolerated took {ms}ms under threshold policy")],
}

SCENARIOS = ["db_pool_exhaustion", "auth_bruteforce", "memory_leak", "disk_full"]


def _fill(tpl: str, rng: np.random.Generator) -> str:
    return (tpl.replace("{uuid}", "%08x-%04x-%04x-%04x-%012x" % (rng.integers(1 << 32), rng.integers(1 << 16),
                        rng.integers(1 << 16), rng.integers(1 << 16), rng.integers(1 << 40)))
               .replace("{ip}", ".".join(str(int(x)) for x in rng.integers(1, 255, 4)))
               .replace("{ms}", str(int(rng.integers(3, 250)))).replace("{n}", str(int(rng.integers(1, 9000)))))


def _scenario_events(name: str, t0: pd.Timestamp, rng: np.random.Generator) -> list[tuple[pd.Timestamp, str, str, str]]:
    ev: list[tuple[pd.Timestamp, str, str, str]] = []
    def at(sec: float) -> pd.Timestamp:
        return t0 + pd.Timedelta(seconds=float(sec))
    if name == "db_pool_exhaustion":
        for s in np.sort(rng.uniform(0, 300, 22)):
            ev.append((at(s), "db", "ERROR", f"connection pool exhausted active=100 max=100 waiting={int(rng.integers(5, 80))}"))
        for s in np.sort(rng.uniform(0, 300, 8)):
            ev.append((at(s), "db", "WARN", f"slow query detected took {int(rng.integers(4000, 30000))}ms"))
        for s in np.sort(rng.uniform(45, 345, 18)):
            ev.append((at(s), "payment", "ERROR", "timeout calling db after 30000ms payment aborted"))
        for s in np.sort(rng.uniform(90, 390, 18)):
            ev.append((at(s), "gateway", "ERROR", "upstream payment returned 503 service unavailable"))
    elif name == "auth_bruteforce":
        for s in np.sort(rng.uniform(0, 240, 40)):
            ip = ".".join(["185", "22", str(int(rng.integers(1, 255))), str(int(rng.integers(1, 255)))])
            ev.append((at(s), "auth", "WARN", f"failed login for user admin from {ip}"))
        for s in np.sort(rng.uniform(120, 240, 4)):
            ev.append((at(s), "auth", "ERROR", "account admin locked after repeated failed login attempts"))
    elif name == "memory_leak":
        for k, s in enumerate(np.linspace(0, 280, 14)):
            ev.append((at(s), "inventory", "INFO", f"gc pause {1200 + 150 * k}ms heap usage {80 + k}%"))
        for s in np.sort(rng.uniform(250, 300, 4)):
            ev.append((at(s), "inventory", "FATAL", "java.lang.OutOfMemoryError heap space exhausted"))
        ev.append((at(305), "inventory", "ERROR", "service restarting after fatal error"))
        for s in np.sort(rng.uniform(260, 330, 6)):
            ev.append((at(s), "gateway", "ERROR", "upstream inventory connection refused"))
    elif name == "disk_full":
        for s in np.sort(rng.uniform(0, 240, 16)):
            ev.append((at(s), "db", "ERROR", "write failed no space left on device /var/lib/db"))
        for s in np.sort(rng.uniform(0, 240, 6)):
            ev.append((at(s), "db", "WARN", "checkpoint failed i/o error on volume"))
        for s in np.sort(rng.uniform(40, 300, 10)):
            ev.append((at(s), "payment", "ERROR", "timeout calling db after 30000ms payment aborted"))
    return ev


def generate_logs(seed: int = 0, minutes: int = 240, start: str = "2024-03-01T08:00:00Z",
                  rate_per_service_per_min: float = 5.0) -> pd.DataFrame:
    """Return a DataFrame [timestamp, level, service, message, label, scenario] sorted by time."""
    rng = np.random.default_rng(seed)
    t_start = pd.Timestamp(start)
    rows: list[tuple[pd.Timestamp, str, str, str, int, str]] = []

    burst_minute = int(rng.integers(int(minutes * 0.2), int(minutes * 0.8)))
    for minute in range(minutes):
        for svc in SERVICES:
            lam = rate_per_service_per_min * (3.0 if (svc == "gateway" and minute in (burst_minute, burst_minute + 1)) else 1.0)
            for _ in range(int(rng.poisson(lam))):
                ts = t_start + pd.Timedelta(minutes=minute, seconds=float(rng.uniform(0, 60)))
                pool = BENIGN_NOISE[svc] if rng.random() < 0.06 else NORMAL[svc]
                lvl, tpl = pool[int(rng.integers(len(pool)))]
                rows.append((ts, lvl, svc, _fill(tpl, rng), 0, ""))

    train_slots = ["db_pool_exhaustion", "auth_bruteforce", "memory_leak"]
    test_slots = list(SCENARIOS)
    rng.shuffle(train_slots)
    rng.shuffle(test_slots)
    for slots, lo, hi in ((train_slots, 0.05, 0.50), (test_slots, 0.62, 0.93)):
        width = (hi - lo) * minutes / len(slots)
        for i, name in enumerate(slots):
            offset = lo * minutes + i * width + float(rng.uniform(0, width * 0.3))
            t0 = t_start + pd.Timedelta(minutes=float(offset))
            for ts, svc, lvl, msg in _scenario_events(name, t0, rng):
                rows.append((ts, lvl, svc, msg, 1, name))

    df = pd.DataFrame(rows, columns=["timestamp", "level", "service", "message", "label", "scenario"])
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)


def to_csv(df: pd.DataFrame, include_label: bool = True) -> str:
    out = df[["timestamp", "level", "service", "message"] + (["label"] if include_label else [])].copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S.%f").str.slice(0, -3) + "Z"
    return out.to_csv(index=False)


def to_text(df: pd.DataFrame) -> str:
    lines = []
    for r in df.itertuples():
        stamp = r.timestamp.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        lines.append(f"{stamp} {r.level} [{r.service}] {r.message}")
        if "OutOfMemoryError" in r.message:
            lines.append("    at com.example.inventory.Cache.grow(Cache.java:212)")
    return "\n".join(lines) + "\n"
