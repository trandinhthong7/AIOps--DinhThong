from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from statistics import median
from typing import Any


KEYWORDS = {
    "pool",
    "connectionpool",
    "exhausted",
    "deadlock",
    "lock",
    "tls",
    "certificate",
    "cert",
    "x509",
    "dns",
    "nxdomain",
    "outofmemoryerror",
    "oom",
    "gc",
    "retry",
    "rebalance",
    "partition",
    "informer",
    "cache",
    "stale",
    "network",
    "policy",
    "t24",
    "redis",
    "datapower",
    "esb",
}


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def normalize_log(msg: str) -> str:
    msg = msg.lower()
    msg = re.sub(r"\b\d+(\.\d+)?\b", "<num>", msg)
    msg = re.sub(r"0x[a-f0-9]+", "<hex>", msg)
    return re.sub(r"\s+", " ", msg).strip()


def service_from_metric_key(key: str) -> str:
    return key.rsplit(".", 1)[0]


def metric_name_from_key(key: str) -> str:
    return key.rsplit(".", 1)[1] if "." in key else key


def metric_delta(before_after: str) -> tuple[float, float]:
    parts = before_after.replace("->", "|").split("|")
    if len(parts) != 2:
        return (0.0, 0.0)
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return (0.0, 0.0)


def extract_live_features(incident: dict[str, Any]) -> dict[str, Any]:
    logs = incident.get("logs", [])
    traces = incident.get("traces", [])
    samples = incident.get("metrics_window", {}).get("samples", {})

    log_templates = [normalize_log(row.get("msg", "")) for row in logs]
    log_text = " ".join(log_templates)
    log_tokens = tokens(log_text)
    keyword_counts = {kw: log_text.count(kw) for kw in KEYWORDS if kw in log_text}

    log_service_counts: Counter[str] = Counter()
    for row in logs:
        if row.get("svc"):
            log_service_counts[row["svc"]] += 1
        msg = row.get("msg", "").lower()
        for service in re.findall(r"(?:target=|to\s+)([a-z0-9-]+(?:-svc|-service|-lb|redis|db|power|esb))", msg):
            log_service_counts[service] += 2

    edge_stats: dict[tuple[str, str], dict[str, float]] = {}
    for tr in traces:
        edge = (tr.get("from", ""), tr.get("to", ""))
        if not edge[0] or not edge[1]:
            continue
        bucket = edge_stats.setdefault(edge, {"count": 0.0, "errors": 0.0, "max_p99": 0.0, "p99_values": []})
        bucket["count"] += float(tr.get("count", 0) or 0)
        bucket["errors"] += float(tr.get("error_count", 0) or 0)
        bucket["max_p99"] = max(bucket["max_p99"], float(tr.get("p99_ms", 0) or 0))
        bucket["p99_values"].append(float(tr.get("p99_ms", 0) or 0))

    trace_edges = []
    trace_service_scores: Counter[str] = Counter()
    for (src, dst), stat in edge_stats.items():
        count = max(stat["count"], 1.0)
        err_rate = stat["errors"] / count
        p99_values = stat["p99_values"] or [0.0]
        base = median(p99_values[: max(3, len(p99_values) // 4)]) or 1.0
        ratio = stat["max_p99"] / base
        score = err_rate * 3.0 + min(ratio / 4.0, 1.5)
        trace_edges.append({"from": src, "to": dst, "error_rate": err_rate, "p99_ratio": ratio, "score": score})
        trace_service_scores[dst] += score * 1.4
        trace_service_scores[src] += score * 0.4
    trace_edges.sort(key=lambda item: item["score"], reverse=True)

    metric_features = []
    metric_service_scores: Counter[str] = Counter()
    for key, series in samples.items():
        if not series:
            continue
        values = [float(point[1]) for point in series if len(point) >= 2]
        if not values:
            continue
        n_base = max(5, len(values) // 4)
        baseline = values[:n_base]
        mu = sum(baseline) / len(baseline)
        sigma = math.sqrt(sum((v - mu) ** 2 for v in baseline) / max(1, len(baseline) - 1)) or 1e-6
        max_v = max(values)
        last_v = values[-1]
        z = (max_v - mu) / sigma
        ratio = max_v / max(mu, 1e-6)
        service = service_from_metric_key(key)
        metric = metric_name_from_key(key)
        metric_features.append({"service": service, "metric": metric, "z": z, "ratio": ratio, "delta": last_v - values[0]})
        metric_service_scores[service] += max(0.0, min(z / 5.0, 3.0)) + max(0.0, min(ratio / 3.0, 2.0))
    metric_features.sort(key=lambda item: (item["z"], item["ratio"]), reverse=True)

    services = set()
    trigger = incident.get("trigger_alert", {})
    if trigger.get("service"):
        services.add(trigger["service"])
    services.update(svc for svc, count in log_service_counts.items() if count >= 2)
    services.update(edge["from"] for edge in trace_edges[:3])
    services.update(edge["to"] for edge in trace_edges[:3])
    services.update(item["service"] for item in metric_features[:5] if item["z"] > 2 or item["ratio"] > 1.5)

    root_scores: Counter[str] = Counter()
    root_scores.update(log_service_counts)
    root_scores.update(trace_service_scores)
    root_scores.update(metric_service_scores)
    if trigger.get("service"):
        root_scores[trigger["service"]] += 1.0

    return {
        "incident_id": incident.get("incident_id", "unknown"),
        "trigger_service": trigger.get("service"),
        "trigger_rule": trigger.get("rule_id", ""),
        "log_templates": log_templates,
        "log_tokens": sorted(log_tokens),
        "keyword_counts": keyword_counts,
        "affected_services": sorted(services),
        "trace_edges": trace_edges[:8],
        "metric_features": metric_features[:8],
        "root_service_votes": root_scores.most_common(8),
        "primary_log_service": log_service_counts.most_common(1)[0][0] if log_service_counts else trigger.get("service"),
        "primary_trace_service": trace_edges[0]["to"] if trace_edges else trigger.get("service"),
        "primary_metric_service": metric_features[0]["service"] if metric_features else trigger.get("service"),
    }


def extract_history_features(incident: dict[str, Any]) -> dict[str, Any]:
    log_text = " ".join(normalize_log(s) for s in incident.get("log_signatures", []))
    trace_edges = []
    for tr in incident.get("trace_signatures", []):
        trace_edges.append(
            {
                "from": tr.get("from", ""),
                "to": tr.get("to", ""),
                "error_rate": float(tr.get("error_rate", 0.0) or 0.0),
                "p99_ratio": float(tr.get("p99_deviation_ratio", 0.0) or 0.0),
                "score": float(tr.get("error_rate", 0.0) or 0.0) * 3.0
                + float(tr.get("p99_deviation_ratio", 0.0) or 0.0) / 4.0,
            }
        )
    metric_features = []
    for sig in incident.get("metric_signatures", []):
        before, after = metric_delta(sig.get("delta", "0 -> 0"))
        ratio = after / max(abs(before), 1e-6)
        metric_features.append(
            {
                "service": sig.get("service"),
                "metric": sig.get("metric"),
                "ratio": ratio,
                "delta": after - before,
            }
        )
    return {
        "incident_id": incident.get("id"),
        "root_cause_class": incident.get("root_cause_class"),
        "affected_services": incident.get("affected_services", []),
        "log_tokens": sorted(tokens(log_text)),
        "keyword_counts": {kw: log_text.count(kw) for kw in KEYWORDS if kw in log_text},
        "trace_edges": trace_edges,
        "metric_features": metric_features,
        "actions_taken": incident.get("actions_taken", []),
        "outcome": incident.get("outcome", "partial"),
        "mttr_minutes": incident.get("mttr_minutes", 30),
    }
