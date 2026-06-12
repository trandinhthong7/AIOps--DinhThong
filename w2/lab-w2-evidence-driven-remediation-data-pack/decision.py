from __future__ import annotations

from collections import Counter
from typing import Any


MANUAL_KEYWORDS = {"tls", "certificate", "cert", "x509", "informer", "stale"}
DNS_KEYWORDS = {"dns", "nxdomain"}
POOL_KEYWORDS = {"pool", "connectionpool", "exhausted"}
MEMORY_KEYWORDS = {"outofmemoryerror", "oom", "gc"}


def action_catalog_by_name(actions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {action["name"]: action for action in actions}


def parse_simple_actions_yaml(text: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- name:"):
            if current:
                actions.append(current)
            current = {"name": line.split(":", 1)[1].strip()}
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            current[key] = [part.strip() for part in value[1:-1].split(",") if part.strip()]
        else:
            try:
                current[key] = int(value)
            except ValueError:
                current[key] = value
    if current:
        actions.append(current)
    return actions


def top_root_service(query: dict[str, Any]) -> str:
    votes = query.get("root_service_votes", [])
    return votes[0][0] if votes else query.get("trigger_service") or "unknown"


def evidence_conflict(query: dict[str, Any]) -> bool:
    log_service = query.get("primary_log_service")
    trace_service = query.get("primary_trace_service")
    metric_service = query.get("primary_metric_service")
    keywords = set(query.get("keyword_counts", {}))
    if POOL_KEYWORDS & keywords and trace_service and trace_service not in {log_service, metric_service}:
        return True
    return False


def make_params(name: str, service: str, query: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    if name == "rollback_service":
        return {"service": service, "target_version": existing.get("target_version", "previous")}
    if name == "increase_pool_size":
        return {"service": service, "from_value": existing.get("from_value", "50"), "to_value": existing.get("to_value", "100")}
    if name == "restart_pod":
        return {"service": service, "pod_selector": existing.get("pod_selector", "default")}
    if name == "dns_config_rollback":
        return {"configmap_name": existing.get("configmap_name", "dns-config"), "target_revision": existing.get("target_revision", "previous")}
    if name == "network_policy_revert":
        return {"policy_name": existing.get("policy_name", "last-applied-policy")}
    return {"team": existing.get("team", "platform-team")}


def select_action(query: dict[str, Any], retrieval: dict[str, Any], actions_catalog: list[dict[str, Any]]) -> dict[str, Any]:
    catalog = action_catalog_by_name(actions_catalog)
    keywords = set(query.get("keyword_counts", {}))
    root = top_root_service(query)
    max_sim = float(retrieval.get("max_similarity", 0.0))
    consensus = float(retrieval.get("consensus_score", 0.0))
    conflict = evidence_conflict(query)

    selected = None
    rationale = []
    ood = max_sim < 0.12 and not (POOL_KEYWORDS & keywords or MEMORY_KEYWORDS & keywords or DNS_KEYWORDS & keywords)

    if MANUAL_KEYWORDS & keywords and not (MEMORY_KEYWORDS & keywords):
        selected = ("page_oncall", make_params("page_oncall", root, query))
        rationale.append("manual_or_novel_keyword_gate")
    elif ood:
        selected = ("page_oncall", make_params("page_oncall", root, query))
        rationale.append("ood_similarity_gate")
    elif conflict:
        selected = ("page_oncall", make_params("page_oncall", root, query))
        rationale.append("log_trace_conflict_gate")
    elif DNS_KEYWORDS & keywords:
        selected = ("dns_config_rollback", make_params("dns_config_rollback", root, query))
        rationale.append("dns_nxdomain_safe_catalog_action")
    elif MEMORY_KEYWORDS & keywords:
        selected = ("rollback_service", make_params("rollback_service", root, query))
        rationale.append("oom_gc_rollback_safe_if_single_service")
    elif POOL_KEYWORDS & keywords:
        if root == "payment-svc":
            selected = ("increase_pool_size", make_params("increase_pool_size", root, query))
            rationale.append("payment_pool_signal_low_blast_radius_action")
        else:
            selected = ("rollback_service", make_params("rollback_service", root, query))
            rationale.append("non_payment_pool_signal_prefers_rollback")

    if selected is None:
        candidates = retrieval.get("candidates", [])
        # Avoid page always winning because it has zero catalog cost.
        non_page = [c for c in candidates if c["name"] != "page_oncall" and c.get("vote", 0) > 0]
        chosen = non_page[0] if non_page and max_sim >= 0.16 else (candidates[0] if candidates else {"name": "page_oncall", "params": {}})
        selected = (chosen["name"], make_params(chosen["name"], root, query, chosen.get("params", {})))
        rationale.append("outcome_weighted_vote")

    action_name, params = selected
    meta = catalog.get(action_name, {})
    blast = int(meta.get("blast_radius_services", 0) or 0)
    confidence = min(0.95, 0.35 + max_sim * 0.85 + consensus * 0.15)
    if conflict or ood:
        confidence = min(confidence, 0.48)
    if action_name == "page_oncall":
        confidence = max(0.45, min(confidence, 0.74))
    if action_name != "page_oncall" and blast >= 4 and confidence < 0.75:
        action_name = "page_oncall"
        params = make_params("page_oncall", root, query)
        rationale.append("blast_radius_gate")
        meta = catalog.get(action_name, {})

    alternatives = []
    for candidate in retrieval.get("candidates", [])[:5]:
        alternatives.append({"name": candidate["name"], "vote": candidate.get("vote", 0), "support": candidate.get("support", [])[:2]})

    return {
        "selected_action": action_name,
        "params": params,
        "confidence": round(confidence, 3),
        "selected_action_meta": meta,
        "blast_radius_check": {
            "blast_radius_services": meta.get("blast_radius_services", 0),
            "passed": action_name == "page_oncall" or int(meta.get("blast_radius_services", 0) or 0) <= 3,
        },
        "rationale": rationale,
        "alternatives": alternatives,
    }
