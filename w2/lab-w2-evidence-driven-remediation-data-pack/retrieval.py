from __future__ import annotations

from collections import defaultdict
from typing import Any

from features import extract_history_features


OUTCOME_WEIGHT = {"success": 1.0, "partial": 0.45, "failed": -0.25}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_history_action(action: str) -> dict[str, Any]:
    parts = action.split(":")
    name = parts[0] if parts else "page_oncall"
    params = parts[1:]
    if name == "rollback_service":
        return {"name": name, "params": {"service": params[0] if params else "unknown", "target_version": params[1] if len(params) > 1 else "previous"}}
    if name == "increase_pool_size":
        return {
            "name": name,
            "params": {
                "service": params[0] if params else "unknown",
                "from_value": params[1] if len(params) > 1 else "50",
                "to_value": params[2] if len(params) > 2 else "100",
            },
        }
    if name == "restart_pod":
        return {"name": name, "params": {"service": params[0] if params else "unknown", "pod_selector": params[1] if len(params) > 1 else "default"}}
    if name == "page_oncall":
        return {"name": name, "params": {"team": params[0] if params else "platform-team"}}
    return {"name": name, "params": {}}


def edge_similarity(query_edges: list[dict[str, Any]], hist_edges: list[dict[str, Any]]) -> float:
    if not query_edges or not hist_edges:
        return 0.0
    best_scores = []
    for qe in query_edges[:5]:
        best = 0.0
        for he in hist_edges:
            service_overlap = len({qe.get("from"), qe.get("to")} & {he.get("from"), he.get("to")}) / 2.0
            direction = 1.0 if qe.get("from") == he.get("from") and qe.get("to") == he.get("to") else 0.0
            err_close = 1.0 - min(abs(float(qe.get("error_rate", 0)) - float(he.get("error_rate", 0))), 1.0)
            ratio_close = 1.0 - min(abs(float(qe.get("p99_ratio", 0)) - float(he.get("p99_ratio", 0))) / 5.0, 1.0)
            best = max(best, 0.35 * service_overlap + 0.25 * direction + 0.2 * err_close + 0.2 * ratio_close)
        best_scores.append(best)
    return sum(best_scores) / len(best_scores)


def metric_similarity(query_metrics: list[dict[str, Any]], hist_metrics: list[dict[str, Any]]) -> float:
    if not query_metrics or not hist_metrics:
        return 0.0
    best_scores = []
    for qm in query_metrics[:5]:
        best = 0.0
        for hm in hist_metrics:
            service = 1.0 if qm.get("service") == hm.get("service") else 0.0
            metric_tokens = set(str(qm.get("metric", "")).split("_"))
            hist_tokens = set(str(hm.get("metric", "")).split("_"))
            metric = jaccard(metric_tokens, hist_tokens)
            ratio_close = 1.0 - min(abs(float(qm.get("ratio", 0)) - float(hm.get("ratio", 0))) / 10.0, 1.0)
            best = max(best, 0.45 * service + 0.35 * metric + 0.2 * ratio_close)
        best_scores.append(best)
    return sum(best_scores) / len(best_scores)


def similarity(query: dict[str, Any], hist: dict[str, Any]) -> tuple[float, dict[str, float]]:
    log_sim = jaccard(set(query.get("log_tokens", [])), set(hist.get("log_tokens", [])))
    keyword_sim = jaccard(set(query.get("keyword_counts", {})), set(hist.get("keyword_counts", {})))
    service_sim = jaccard(set(query.get("affected_services", [])), set(hist.get("affected_services", [])))
    trace_sim = edge_similarity(query.get("trace_edges", []), hist.get("trace_edges", []))
    metric_sim = metric_similarity(query.get("metric_features", []), hist.get("metric_features", []))
    score = 0.30 * log_sim + 0.18 * keyword_sim + 0.25 * trace_sim + 0.15 * metric_sim + 0.12 * service_sim
    parts = {
        "log": round(log_sim, 4),
        "keyword": round(keyword_sim, 4),
        "trace": round(trace_sim, 4),
        "metric": round(metric_sim, 4),
        "service": round(service_sim, 4),
    }
    return score, parts


def retrieve_and_vote(query: dict[str, Any], history: list[dict[str, Any]], top_k: int = 5) -> dict[str, Any]:
    hist_vectors = [(item, extract_history_features(item)) for item in history]
    scored = []
    for raw, vec in hist_vectors:
        score, parts = similarity(query, vec)
        scored.append({"id": raw["id"], "score": score, "parts": parts, "raw": raw, "features": vec})
    scored.sort(key=lambda item: item["score"], reverse=True)
    neighbors = scored[:top_k]

    action_votes: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
    action_evidence: dict[tuple[str, tuple[tuple[str, str], ...]], list[dict[str, Any]]] = defaultdict(list)
    for rank, neighbor in enumerate(neighbors):
        outcome_weight = OUTCOME_WEIGHT.get(neighbor["features"].get("outcome", "partial"), 0.25)
        rank_weight = 1.0 / (rank + 1)
        for action in neighbor["features"].get("actions_taken", []):
            parsed = parse_history_action(action)
            key = (parsed["name"], tuple(sorted((k, str(v)) for k, v in parsed.get("params", {}).items())))
            vote = neighbor["score"] * outcome_weight * rank_weight
            action_votes[key] += vote
            action_evidence[key].append(
                {
                    "incident_id": neighbor["id"],
                    "similarity": round(neighbor["score"], 4),
                    "outcome": neighbor["features"].get("outcome"),
                    "vote": round(vote, 4),
                }
            )

    candidates = []
    for (name, params_tuple), score in sorted(action_votes.items(), key=lambda item: item[1], reverse=True):
        params = dict(params_tuple)
        candidates.append({"name": name, "params": params, "vote": round(score, 4), "support": action_evidence[(name, params_tuple)]})

    top_score = neighbors[0]["score"] if neighbors else 0.0
    second_score = neighbors[1]["score"] if len(neighbors) > 1 else 0.0
    consensus_score = top_score / max(sum(max(n["score"], 0.0) for n in neighbors), 1e-9)
    return {
        "top_3_neighbors": [
            {
                "id": n["id"],
                "similarity": round(n["score"], 4),
                "class": n["raw"].get("root_cause_class"),
                "outcome": n["features"].get("outcome"),
                "parts": n["parts"],
            }
            for n in neighbors[:3]
        ],
        "candidates": candidates,
        "max_similarity": round(top_score, 4),
        "similarity_margin": round(top_score - second_score, 4),
        "consensus_score": round(consensus_score, 4),
    }
