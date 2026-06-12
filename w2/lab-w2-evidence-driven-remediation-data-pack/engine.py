from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from decision import parse_simple_actions_yaml, select_action
from features import extract_live_features
from retrieval import retrieve_and_vote


def incident_id_from_path(path: Path, incident: dict[str, Any]) -> str:
    stem = path.stem
    if stem.startswith("E") and stem[1:].isdigit():
        return stem
    raw = incident.get("incident_id", stem)
    return raw.split("-")[0] if raw.startswith("E") else stem


def decide(incident_path: Path, history_path: Path, actions_path: Path) -> dict[str, Any]:
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    history = json.loads(history_path.read_text(encoding="utf-8"))
    actions = parse_simple_actions_yaml(actions_path.read_text(encoding="utf-8"))

    features = extract_live_features(incident)
    retrieval = retrieve_and_vote(features, history, top_k=5)
    decision = select_action(features, retrieval, actions)

    return {
        "incident_id": incident_id_from_path(incident_path, incident),
        "selected_action": decision["selected_action"],
        "params": decision["params"],
        "confidence": decision["confidence"],
        "evidence": {
            "trigger_service": features.get("trigger_service"),
            "affected_services_rule": "trigger + log-mentioned services + top trace endpoints + anomalous metric services",
            "affected_services": features.get("affected_services", []),
            "keyword_counts": features.get("keyword_counts", {}),
            "root_service_votes": features.get("root_service_votes", [])[:5],
            "primary_log_service": features.get("primary_log_service"),
            "primary_trace_service": features.get("primary_trace_service"),
            "primary_metric_service": features.get("primary_metric_service"),
            "top_trace_edges": features.get("trace_edges", [])[:3],
            "top_metric_features": features.get("metric_features", [])[:3],
            "rationale": decision["rationale"],
        },
        "top_3_neighbors": retrieval["top_3_neighbors"],
        "candidate_actions": retrieval["candidates"][:5],
        "consensus_score": retrieval["consensus_score"],
        "max_similarity": retrieval["max_similarity"],
        "similarity_margin": retrieval["similarity_margin"],
        "selected_action_meta": decision["selected_action_meta"],
        "blast_radius_check": decision["blast_radius_check"],
        "alternatives": decision["alternatives"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    decide_parser = sub.add_parser("decide")
    decide_parser.add_argument("--incident", required=True)
    decide_parser.add_argument("--history", default="incidents_history.json")
    decide_parser.add_argument("--actions", default="actions.yaml")
    decide_parser.add_argument("--audit", default="audit.jsonl")
    args = parser.parse_args()

    if args.cmd != "decide":
        parser.print_help()
        return 1

    output = decide(Path(args.incident), Path(args.history), Path(args.actions))
    print(json.dumps(output, indent=2, ensure_ascii=False))
    with Path(args.audit).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(output, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
