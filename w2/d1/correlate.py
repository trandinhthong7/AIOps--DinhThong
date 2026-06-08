from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from typing import Any


SEVERITY_RANK = {"info": 0, "warn": 1, "crit": 2}
CRITICALITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fingerprint(alert: dict[str, Any]) -> str:
    return f"{alert['service']}|{alert['metric']}|{alert['severity']}"


def load_service_graph(services_doc: dict[str, Any]) -> dict[str, Any]:
    service_names = {svc["name"] for svc in services_doc["services"]}
    criticality = {svc["name"]: svc["criticality"] for svc in services_doc["services"]}
    callers_by_callee: dict[str, set[str]] = defaultdict(set)
    callees_by_caller: dict[str, set[str]] = defaultdict(set)

    for edge in services_doc["edges"]:
        src, dst = edge["from"], edge["to"]
        callers_by_callee[dst].add(src)
        callees_by_caller[src].add(dst)
        service_names.update([src, dst])

    return {
        "services": service_names,
        "criticality": criticality,
        "callers_by_callee": callers_by_callee,
        "callees_by_caller": callees_by_caller,
    }


def session_groups(alerts: list[dict[str, Any]], gap_sec: int = 49) -> list[list[dict[str, Any]]]:
    if not alerts:
        return []

    sorted_alerts = sorted(alerts, key=lambda alert: parse_ts(alert["ts"]))
    groups = [[sorted_alerts[0]]]

    for alert in sorted_alerts[1:]:
        gap = (parse_ts(alert["ts"]) - parse_ts(groups[-1][-1]["ts"])).total_seconds()
        if gap <= gap_sec:
            groups[-1].append(alert)
        else:
            groups.append([alert])

    return groups


def upstream_callers(service: str, graph: dict[str, Any], max_hop: int) -> set[str]:
    seen = {service}
    queue = deque([(service, 0)])

    while queue:
        current, depth = queue.popleft()
        if depth >= max_hop:
            continue
        for caller in graph["callers_by_callee"].get(current, set()):
            if caller not in seen:
                seen.add(caller)
                queue.append((caller, depth + 1))

    return seen


def seed_score(service: str, alerts: list[dict[str, Any]], graph: dict[str, Any]) -> tuple[int, int, int, datetime]:
    severities = [SEVERITY_RANK.get(alert["severity"], -1) for alert in alerts if alert["service"] == service]
    first_seen = min(parse_ts(alert["ts"]) for alert in alerts if alert["service"] == service)
    crit = CRITICALITY_RANK.get(graph["criticality"].get(service, "low"), 0)
    return (max(severities), crit, len(severities), first_seen)


def topology_groups(
    alerts: list[dict[str, Any]], graph: dict[str, Any], max_hop: int = 2
) -> list[list[dict[str, Any]]]:
    by_service: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alert in alerts:
        by_service[alert["service"]].append(alert)

    unassigned = set(by_service)
    groups: list[list[dict[str, Any]]] = []

    while unassigned:
        seed = max(unassigned, key=lambda svc: seed_score(svc, alerts, graph))
        affected = upstream_callers(seed, graph, max_hop)
        member_services = sorted(unassigned & affected)

        group: list[dict[str, Any]] = []
        for service in member_services:
            group.extend(by_service[service])
            unassigned.remove(service)

        groups.append(sorted(group, key=lambda alert: parse_ts(alert["ts"])))

    return groups


def summarize_cluster(cluster_id: str, alerts: list[dict[str, Any]]) -> dict[str, Any]:
    severest = max(alerts, key=lambda alert: SEVERITY_RANK.get(alert["severity"], -1))["severity"]
    return {
        "cluster_id": cluster_id,
        "alert_count": len(alerts),
        "services": sorted({alert["service"] for alert in alerts}),
        "time_range": [min(alert["ts"] for alert in alerts), max(alert["ts"] for alert in alerts)],
        "max_severity": severest,
        "fingerprints": sorted({fingerprint(alert) for alert in alerts}),
        "alert_ids": [alert["id"] for alert in alerts],
    }


def correlate(
    alerts: list[dict[str, Any]], services_doc: dict[str, Any], gap_sec: int = 49, max_hop: int = 2
) -> dict[str, Any]:
    graph = load_service_graph(services_doc)
    clusters: list[dict[str, Any]] = []

    for session_idx, session in enumerate(session_groups(alerts, gap_sec=gap_sec)):
        for group_idx, group in enumerate(topology_groups(session, graph, max_hop=max_hop)):
            clusters.append(summarize_cluster(f"c-{session_idx:03d}-{group_idx:03d}", group))

    clusters.sort(key=lambda cluster: (-cluster["alert_count"], cluster["time_range"][0], cluster["cluster_id"]))
    for idx, cluster in enumerate(clusters):
        cluster["cluster_id"] = f"c-000-{idx:03d}"

    input_alerts = len(alerts)
    output_clusters = len(clusters)

    return {
        "input_alerts": input_alerts,
        "output_clusters": output_clusters,
        "reduction_ratio": round(1 - output_clusters / input_alerts, 2) if input_alerts else 0,
        "clusters": clusters,
    }
