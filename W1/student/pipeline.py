#!/usr/bin/env python3
"""Streaming anomaly detection pipeline for the AIOps W1 individual lab."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock
from typing import Any


ALERTS_FILE = Path("alerts.jsonl")


class StreamingDetector:
    """Small stateful detector tuned to the generator's normal ranges."""

    def __init__(self, alerts_file: Path = ALERTS_FILE) -> None:
        self.alerts_file = alerts_file
        self.samples: deque[dict[str, Any]] = deque(maxlen=30)
        self.fired_types: set[str] = set()
        self.lock = Lock()

    def ingest(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        timestamp = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
        metrics = payload.get("metrics", {})
        logs = payload.get("logs", [])

        with self.lock:
            self.samples.append({"timestamp": timestamp, "metrics": metrics, "logs": logs})
            alert = self._detect(timestamp, metrics, logs)
            if alert is None or alert["type"] in self.fired_types:
                return []

            self.fired_types.add(alert["type"])
            self._write_alert(alert)
            return [alert]

    def _detect(
        self, timestamp: str, metrics: dict[str, Any], logs: list[dict[str, Any]]
    ) -> dict[str, str] | None:
        memory_used = float(metrics.get("memory_usage_bytes", 0))
        memory_limit = float(metrics.get("memory_limit_bytes", 1))
        memory_util = memory_used / memory_limit if memory_limit else 0
        gc_pause = float(metrics.get("jvm_gc_pause_ms_avg", 0))
        cpu = float(metrics.get("cpu_usage_percent", 0))
        rps = float(metrics.get("http_requests_per_sec", 0))
        latency = float(metrics.get("http_p99_latency_ms", 0))
        error_rate = float(metrics.get("http_5xx_rate", 0))
        queue_depth = float(metrics.get("queue_depth", 0))
        timeout_rate = float(metrics.get("upstream_timeout_rate", 0))

        text = " ".join(str(log.get("message", "")).lower() for log in logs)

        if timeout_rate >= 5 and latency >= 150 and error_rate >= 2:
            return self._alert(
                timestamp,
                "dependency_timeout",
                self._severity(timeout_rate >= 25 or error_rate >= 15 or latency >= 1000),
                f"Upstream timeout rate {timeout_rate:.1f}% with 5xx {error_rate:.1f}% and p99 {latency:.0f}ms",
            )

        if "upstream timeout" in text or "circuit breaker" in text:
            return self._alert(
                timestamp,
                "dependency_timeout",
                "critical" if "circuit breaker" in text else "warning",
                f"Dependency timeout evidence in logs; timeout rate {timeout_rate:.1f}%",
            )

        if rps >= 300 and queue_depth >= 40 and latency >= 180:
            return self._alert(
                timestamp,
                "traffic_spike",
                self._severity(rps >= 600 or queue_depth >= 120 or error_rate >= 10),
                f"Traffic spike: {rps:.0f} req/s, queue depth {queue_depth:.0f}, p99 {latency:.0f}ms",
            )

        if "server overloaded" in text or "queue depth high" in text:
            return self._alert(
                timestamp,
                "traffic_spike",
                "critical" if "server overloaded" in text else "warning",
                f"Traffic overload evidence in logs; queue depth {queue_depth:.0f}",
            )

        memory_growth = self._memory_growth_bytes()
        if (memory_util >= 0.55 and gc_pause >= 45 and memory_growth >= 20_000_000) or (
            memory_util >= 0.72 and gc_pause >= 35
        ):
            return self._alert(
                timestamp,
                "memory_leak",
                self._severity(memory_util >= 0.8 or gc_pause >= 120 or error_rate >= 10),
                "Memory usage growing abnormally, "
                f"utilization {memory_util * 100:.0f}% and GC pause {gc_pause:.0f}ms",
            )

        if "outofmemorywarning" in text or (gc_pause >= 80 and memory_util >= 0.5):
            return self._alert(
                timestamp,
                "memory_leak",
                "critical" if memory_util >= 0.8 else "warning",
                f"Memory pressure evidence: utilization {memory_util * 100:.0f}%, GC pause {gc_pause:.0f}ms",
            )

        return None

    def _memory_growth_bytes(self) -> float:
        if len(self.samples) < 6:
            return 0.0

        recent = list(self.samples)[-6:]
        first = float(recent[0]["metrics"].get("memory_usage_bytes", 0))
        last = float(recent[-1]["metrics"].get("memory_usage_bytes", 0))
        return last - first

    def _write_alert(self, alert: dict[str, str]) -> None:
        with self.alerts_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(alert, ensure_ascii=True) + "\n")

    @staticmethod
    def _alert(timestamp: str, alert_type: str, severity: str, message: str) -> dict[str, str]:
        return {
            "timestamp": timestamp,
            "type": alert_type,
            "severity": severity,
            "message": message,
        }

    @staticmethod
    def _severity(is_critical: bool) -> str:
        return "critical" if is_critical else "warning"


detector = StreamingDetector()


class PipelineHandler(BaseHTTPRequestHandler):
    server_version = "AIOpsPipeline/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"status": "ok"})
            return
        self._json_response(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/ingest":
            self._json_response(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body)
            alerts = detector.ingest(payload)
        except Exception as exc:
            self._json_response(400, {"status": "error", "message": str(exc)})
            return

        self._json_response(200, {"status": "ok", "alerts": len(alerts)})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _json_response(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AIOps streaming anomaly pipeline")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    ALERTS_FILE.touch(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), PipelineHandler)
    print(f"Pipeline listening on http://{args.host}:{args.port}/ingest")
    print(f"Writing alerts to {ALERTS_FILE.resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down pipeline")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
