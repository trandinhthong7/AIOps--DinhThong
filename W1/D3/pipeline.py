from __future__ import annotations

import json
import queue
import statistics
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
SOURCE_CANDIDATES = [
    BASE_DIR / "realKnownCause" / "machine_temperature_system_failure.csv",
    BASE_DIR
    / "numenta NAB master data-realKnownCause"
    / "machine_temperature_system_failure.csv",
]
EVENTS_PATH = BASE_DIR / "events.jsonl"
PARQUET_PATH = BASE_DIR / "features.parquet"
JSON_PATH = BASE_DIR / "features.json"
STOP = object()


@dataclass(frozen=True)
class PipelineConfig:
    source_path: Path
    queue_size: int = 1_000
    rolling_window_points: int = 12  # 12 x 5 minutes = 1 hour


def find_source() -> Path:
    for candidate in SOURCE_CANDIDATES:
        if candidate.exists():
            return candidate
    searched = "\n".join(f"- {path}" for path in SOURCE_CANDIDATES)
    raise FileNotFoundError(f"CSV source not found. Searched:\n{searched}")


def producer(config: PipelineConfig, output_queue: queue.Queue[Any]) -> None:
    """Read telemetry rows and publish them to the in-process queue."""
    rows = pd.read_csv(config.source_path, parse_dates=["timestamp"])

    with EVENTS_PATH.open("w", encoding="utf-8") as event_log:
        for event_id, row in enumerate(rows.itertuples(index=False), start=1):
            event = {
                "event_id": event_id,
                "timestamp": row.timestamp.isoformat(),
                "metric_name": "machine_temperature",
                "value": float(row.value),
                "source": "nab.realKnownCause.machine_temperature_system_failure",
            }
            event_log.write(json.dumps(event) + "\n")
            output_queue.put(event)

    output_queue.put(STOP)


def consumer(config: PipelineConfig, input_queue: queue.Queue[Any]) -> list[dict[str, Any]]:
    """Consume events and compute streaming features from a rolling window."""
    window: deque[float] = deque(maxlen=config.rolling_window_points)
    previous_value: float | None = None
    features: list[dict[str, Any]] = []

    while True:
        event = input_queue.get()
        if event is STOP:
            input_queue.task_done()
            break

        value = float(event["value"])
        window.append(value)

        rolling_mean = statistics.fmean(window)
        rolling_std = statistics.pstdev(window) if len(window) > 1 else 0.0
        rate_of_change = 0.0 if previous_value is None else value - previous_value
        zscore = 0.0 if rolling_std == 0.0 else (value - rolling_mean) / rolling_std

        features.append(
            {
                "event_id": event["event_id"],
                "timestamp": event["timestamp"],
                "metric_name": event["metric_name"],
                "value": value,
                "rolling_mean_1h": rolling_mean,
                "rolling_std_1h": rolling_std,
                "rate_of_change_5m": rate_of_change,
                "zscore_1h": zscore,
                "is_anomaly_candidate": abs(zscore) >= 3.0,
            }
        )

        previous_value = value
        input_queue.task_done()

    return features


def write_features(features: list[dict[str, Any]]) -> Path:
    frame = pd.DataFrame(features)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])

    try:
        frame.to_parquet(PARQUET_PATH, index=False)
        return PARQUET_PATH
    except ImportError:
        frame.to_json(JSON_PATH, orient="records", lines=True, date_format="iso")
        return JSON_PATH


def main() -> None:
    config = PipelineConfig(source_path=find_source())
    event_queue: queue.Queue[Any] = queue.Queue(maxsize=config.queue_size)
    result_holder: dict[str, list[dict[str, Any]]] = {}

    producer_thread = threading.Thread(
        target=producer,
        args=(config, event_queue),
        name="mock-kafka-producer",
    )
    consumer_thread = threading.Thread(
        target=lambda: result_holder.setdefault(
            "features", consumer(config, event_queue)
        ),
        name="stream-feature-consumer",
    )

    consumer_thread.start()
    producer_thread.start()
    producer_thread.join()
    consumer_thread.join()

    features = result_holder["features"]
    output_path = write_features(features)
    anomaly_count = sum(1 for row in features if row["is_anomaly_candidate"])

    print(f"Source: {config.source_path}")
    print(f"Events emitted: {len(features):,} -> {EVENTS_PATH}")
    print(f"Features written: {len(features):,} -> {output_path}")
    print(f"Anomaly candidates (|zscore_1h| >= 3): {anomaly_count:,}")


if __name__ == "__main__":
    main()
