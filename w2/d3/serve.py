from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx
from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel, ConfigDict, Field


BASE_DIR = Path(__file__).resolve().parent
W2_DIR = BASE_DIR.parent
D1_DIR = W2_DIR / "d1"
D2_DIR = W2_DIR / "d2"
DATASET_DIR = D2_DIR / "dataset"

sys.path.insert(0, str(D1_DIR))
from correlate import correlate  # noqa: E402


APP_VERSION = "w2-d3-1.0"
GAP_SEC = 120
MAX_HOP = 2
USE_LLM = os.getenv("AIOPS_USE_LLM", "false").lower() == "true"

logger = logging.getLogger("aiops.serve")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

REQUEST_COUNT = Counter("aiops_incident_requests_total", "Incident requests", ["status"])
REQUEST_LATENCY = Histogram("aiops_incident_latency_seconds", "Incident request latency")
CLUSTERS_OUT = Histogram("aiops_clusters_per_request", "Clusters produced per request")
LLM_FAILURES = Counter("aiops_llm_failures_total", "LLM failures", ["reason"])

RCA_CACHE: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=512, ttl=300)


class Alert(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    ts: datetime
    service: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    severity: str = Field(pattern="^(info|warn|crit|critical|high|medium|low)$")
    value: float | int | str | None = None
    threshold: float | int | str | None = None
    labels: dict[str, Any] = Field(default_factory=dict)


class IncidentRequest(BaseModel):
    alerts: list[Alert] = Field(min_length=1)


class Candidate(BaseModel):
    service: str
    score: float


class RCAResult(BaseModel):
    cluster_id: str
    graph_top3: list[Candidate]
    root_cause: str
    root_cause_class: str
    confidence: float
    recommended_actions: list[str]
    reasoning: str
    similar_incidents: list[str]
    method: str


class IncidentResponse(BaseModel):
    clusters: list[dict[str, Any]]
    root_cause: str
    root_cause_class: str
    confidence: float
    recommended_actions: list[str]
    rca: RCAResult
    phase_ms: dict[str, float]
    graph_version: str
    method: str


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


SERVICES_DOC = load_json(DATASET_DIR / "services.json")
HISTORY_DOC = load_json(DATASET_DIR / "incidents_history.json")
HISTORY = HISTORY_DOC["incidents"]
GRAPH_LOADED_AT = datetime.now(timezone.utc)


def build_graph(services_doc: dict[str, Any]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for service in services_doc.get("services", []):
        graph.add_node(service["name"], kind="service", **service)
    for store in services_doc.get("stores", []):
        graph.add_node(store["name"], kind="store", **store)
    for edge in services_doc.get("edges", []):
        graph.add_edge(edge["from"], edge["to"], **edge)
    return graph


GRAPH = build_graph(SERVICES_DOC)
GRAPH_VERSION = hashlib.sha256(
    json.dumps(SERVICES_DOC, sort_keys=True).encode("utf-8")
).hexdigest()[:12]
ALERTS_BY_ID: dict[str, dict[str, Any]] = {}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def jsonable_alert(alert: Alert) -> dict[str, Any]:
    item = alert.model_dump(mode="json")
    if item["ts"].endswith("+00:00"):
        item["ts"] = item["ts"].replace("+00:00", "Z")
    return item


def token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def alert_score(alert: dict[str, Any]) -> float:
    severity_weight = {
        "info": 0.05,
        "low": 0.1,
        "medium": 0.2,
        "warn": 0.35,
        "high": 0.65,
        "crit": 1.0,
        "critical": 1.0,
    }
    sev = severity_weight.get(alert.get("severity", "warn"), 0.2)
    try:
        value = float(alert.get("value") or 0)
        threshold = float(alert.get("threshold") or 0)
    except (TypeError, ValueError):
        value = 0.0
        threshold = 0.0
    ratio = min(max((value - threshold) / abs(threshold), 0), 2.0) / 2.0 if threshold else 0.0
    metric = alert.get("metric", "")
    metric_boost = 0.25 if any(k in metric for k in ["connection", "error", "5xx", "drop", "queue"]) else 0.0
    return 0.55 * sev + 0.30 * ratio + metric_boost


def graph_temporal_score(cluster: dict[str, Any], alerts_by_id: dict[str, dict[str, Any]]) -> list[tuple[str, float]]:
    criticality_weight = {"low": 0.15, "medium": 0.35, "high": 0.65, "critical": 0.9}
    cluster_alerts = [alerts_by_id[a] for a in cluster.get("alert_ids", []) if a in alerts_by_id]
    observed = set(cluster.get("services", []))
    first_seen: dict[str, datetime] = {}
    direct_scores: dict[str, float] = defaultdict(float)

    for alert in cluster_alerts:
        service = alert["service"]
        ts = parse_ts(alert["ts"])
        first_seen[service] = min(first_seen.get(service, ts), ts)
        direct_scores[service] += alert_score(alert)

    candidates = set(observed)
    for service in list(observed):
        if service in GRAPH:
            candidates.update(GRAPH.predecessors(service))
            candidates.update(GRAPH.successors(service))

    min_ts = min(first_seen.values()) if first_seen else None
    raw: dict[str, float] = {}
    for candidate in candidates:
        if candidate not in GRAPH:
            continue
        node = GRAPH.nodes[candidate]
        score = direct_scores.get(candidate, 0.0)
        if candidate in observed:
            score += 0.45
        if min_ts and candidate in first_seen:
            delay_s = max((first_seen[candidate] - min_ts).total_seconds(), 0)
            score += max(0.0, 0.35 - delay_s / 180.0)
        score += criticality_weight.get(node.get("criticality", "medium"), 0.25) * 0.22
        if node.get("kind") == "store":
            score += 0.15
        for observed_service in observed:
            if observed_service == candidate:
                continue
            if observed_service in GRAPH and nx.has_path(GRAPH, observed_service, candidate):
                distance = nx.shortest_path_length(GRAPH, observed_service, candidate)
                score += 0.28 / max(distance, 1)
            elif observed_service in GRAPH and nx.has_path(GRAPH, candidate, observed_service):
                distance = nx.shortest_path_length(GRAPH, candidate, observed_service)
                score += 0.10 / max(distance, 1)
        raw[candidate] = score

    max_score = max(raw.values()) if raw else 1.0
    ranked = sorted(
        ((svc, round(score / max_score, 4)) for svc, score in raw.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked[:3]


def cluster_text(cluster: dict[str, Any]) -> str:
    pieces: list[str] = [cluster.get("cluster_id", ""), cluster.get("max_severity", "")]
    pieces.extend(cluster.get("services", []))
    for fingerprint in cluster.get("fingerprints", []):
        pieces.extend(fingerprint.split("|"))
    return " ".join(pieces)


def incident_text(incident: dict[str, Any]) -> str:
    return " ".join(
        [
            incident.get("id", ""),
            incident.get("severity", ""),
            " ".join(incident.get("services_involved", [])),
            incident.get("root_cause_service", ""),
            incident.get("root_cause_class", ""),
            incident.get("summary", ""),
            incident.get("remediation", ""),
        ]
    )


def keyword_similarity(query: str, doc: str) -> float:
    q_tokens = token_set(query)
    d_tokens = token_set(doc)
    if not q_tokens or not d_tokens:
        return 0.0
    jaccard = len(q_tokens & d_tokens) / len(q_tokens | d_tokens)
    important = {
        "payment",
        "payments",
        "checkout",
        "cart",
        "redis",
        "kafka",
        "connection",
        "pool",
        "queue",
        "latency",
        "error",
        "db",
    }
    weighted = sum(2.4 if tok in important or tok.endswith("svc") else 1.0 for tok in q_tokens & d_tokens)
    phrase_boost = 0.0
    q_lower, d_lower = query.lower(), doc.lower()
    for phrase in ["connection pool", "db connection", "queue lag", "queue depth", "cart redis", "payment timeout"]:
        words = phrase.split()
        if all(word in q_lower for word in words) and all(word in d_lower for word in words):
            phrase_boost += 0.22
    return jaccard + weighted / (len(q_tokens) + 8) + phrase_boost


def retrieve_similar(cluster: dict[str, Any], top_k: int = 3) -> list[tuple[dict[str, Any], float]]:
    query = cluster_text(cluster)
    cluster_services = set(cluster.get("services", []))
    scored: list[tuple[dict[str, Any], float]] = []
    for incident in HISTORY:
        score = keyword_similarity(query, incident_text(incident))
        incident_services = set(incident.get("services_involved", []))
        score += 0.16 * len(cluster_services & incident_services)
        if incident.get("root_cause_service") in cluster_services:
            score += 0.08
        if score > 0:
            scored.append((incident, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def split_actions(remediation: str) -> list[str]:
    parts = re.split(r"\.\s+|;\s+", remediation.strip())
    return [part.strip().rstrip(".") for part in parts if part.strip()]


def run_rca(cluster: dict[str, Any], alerts_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cache_key = hashlib.sha256(json.dumps(cluster, sort_keys=True).encode("utf-8")).hexdigest()
    if cache_key in RCA_CACHE:
        return RCA_CACHE[cache_key]

    graph_top3 = graph_temporal_score(cluster, alerts_by_id)
    similar = retrieve_similar(cluster, top_k=3)
    if similar:
        top_incident, similarity = similar[0]
        graph_services = [service for service, _ in graph_top3]
        retrieved_root = top_incident.get("root_cause_service")
        root_cause = retrieved_root if retrieved_root in graph_services else graph_top3[0][0]
        root_class = top_incident.get("root_cause_class", "unknown")
        actions = split_actions(top_incident.get("remediation", "Escalate to service owner"))
        evidence = min(1.0, math.log1p(cluster.get("alert_count", 1)) / math.log1p(15))
        sim_strength = min(1.0, similarity / 1.75)
        confidence = min(0.93, 0.34 + 0.25 * graph_top3[0][1] + 0.22 * sim_strength + 0.12 * evidence)
        reasoning = (
            f"Graph ranked {graph_top3[0][0]} first; keyword kNN retrieved {top_incident['id']} "
            f"with class {root_class}. Root cause reconciles graph candidates with incident history."
        )
        similar_ids = [incident["id"] for incident, _ in similar]
    else:
        root_cause = graph_top3[0][0] if graph_top3 else cluster.get("services", ["unknown"])[0]
        root_class = "unknown"
        actions = ["Escalate to owning service team", "Collect traces and recent deploy events"]
        confidence = 0.35
        reasoning = "No similar incident was retrieved; RCA fell back to graph and temporal scoring."
        similar_ids = []

    result = {
        "cluster_id": cluster["cluster_id"],
        "graph_top3": [{"service": svc, "score": round(float(score), 2)} for svc, score in graph_top3],
        "root_cause": root_cause,
        "root_cause_class": root_class,
        "confidence": round(float(confidence), 2),
        "recommended_actions": actions[:3],
        "reasoning": reasoning,
        "similar_incidents": similar_ids,
        "method": "graph+retrieval" if not USE_LLM else "graph+retrieval+llm-fallback",
    }
    RCA_CACHE[cache_key] = result
    return result


app = FastAPI(title="AIOps RCA Service", version=APP_VERSION)
app.mount("/metrics", make_asgi_app())


@app.middleware("http")
async def latency_middleware(request: Request, call_next):
    start = time.perf_counter()
    with REQUEST_LATENCY.time():
        response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.3f}"
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    checks = {
        "graph_loaded": GRAPH.number_of_nodes() > 0 and GRAPH.number_of_edges() > 0,
        "history_loaded": len(HISTORY) > 0,
        "correlate_loaded": callable(correlate),
        "llm_required": USE_LLM,
    }
    if not all(value for key, value in checks.items() if key != "llm_required"):
        raise HTTPException(status_code=503, detail=checks)
    return {
        "status": "ready",
        "checks": checks,
        "graph_version": GRAPH_VERSION,
        "graph_loaded_at": GRAPH_LOADED_AT.isoformat(),
    }


@app.post("/incident", response_model=IncidentResponse)
def incident(request: IncidentRequest) -> IncidentResponse:
    phase_start = time.perf_counter()
    alerts = [jsonable_alert(alert) for alert in request.alerts]
    validate_ms = (time.perf_counter() - phase_start) * 1000

    try:
        t0 = time.perf_counter()
        summary = correlate(alerts, SERVICES_DOC, gap_sec=GAP_SEC, max_hop=MAX_HOP)
        correlate_ms = (time.perf_counter() - t0) * 1000

        if not summary["clusters"]:
            raise HTTPException(status_code=422, detail="No clusters produced from alerts")

        t0 = time.perf_counter()
        alerts_by_id = {alert["id"]: alert for alert in alerts}
        primary = max(summary["clusters"], key=lambda cluster: cluster["alert_count"])
        rca = run_rca(primary, alerts_by_id)
        rca_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        if USE_LLM:
            LLM_FAILURES.labels(reason="not_configured").inc()
        llm_ms = (time.perf_counter() - t0) * 1000

        phase_ms = {
            "validate": round(validate_ms, 3),
            "correlate": round(correlate_ms, 3),
            "rca": round(rca_ms, 3),
            "llm": round(llm_ms, 3),
        }
        t0 = time.perf_counter()
        response = IncidentResponse(
            clusters=summary["clusters"],
            root_cause=rca["root_cause"],
            root_cause_class=rca["root_cause_class"],
            confidence=rca["confidence"],
            recommended_actions=rca["recommended_actions"],
            rca=rca,
            phase_ms=phase_ms,
            graph_version=GRAPH_VERSION,
            method=rca["method"],
        )
        response.phase_ms["serialize"] = round((time.perf_counter() - t0) * 1000, 3)
        REQUEST_COUNT.labels(status="ok").inc()
        CLUSTERS_OUT.observe(len(summary["clusters"]))
        return response
    except HTTPException:
        REQUEST_COUNT.labels(status="invalid").inc()
        raise
    except Exception as exc:
        REQUEST_COUNT.labels(status="error").inc()
        logger.exception("Pipeline failed")
        raise HTTPException(status_code=500, detail="Internal pipeline error") from exc
