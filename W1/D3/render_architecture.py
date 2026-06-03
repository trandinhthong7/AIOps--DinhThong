from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUTPUT_PATH = Path(__file__).resolve().parent / "architecture.png"


def add_box(ax, xy, text, color):
    x, y = xy
    box = FancyBboxPatch(
        (x, y),
        2.45,
        0.78,
        boxstyle="round,pad=0.03,rounding_size=0.05",
        linewidth=1.4,
        edgecolor="#263238",
        facecolor=color,
    )
    ax.add_patch(box)
    ax.text(
        x + 1.225,
        y + 0.39,
        text,
        ha="center",
        va="center",
        fontsize=9,
        color="#111827",
        weight="semibold",
    )


def add_arrow(ax, start, end):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=1.3,
            color="#374151",
        )
    )


def main() -> None:
    fig, ax = plt.subplots(figsize=(14, 7), dpi=180)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.axis("off")
    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#f8fafc")

    ax.text(
        0.5,
        6.55,
        "E2E AIOps Data Layer: Payment Service Anomaly Detection",
        fontsize=16,
        weight="bold",
        color="#0f172a",
    )

    boxes = {
        "service": ((0.5, 3.25), "Payment Service\nOTel SDK"),
        "collector": ((3.1, 3.25), "Collection\nOTel Collector"),
        "kafka": ((5.7, 3.25), "Transport\nKafka Topics"),
        "flink": ((8.3, 3.25), "Processing\nFlink Streaming"),
        "metrics": ((11.0, 5.35), "Metrics\nVictoriaMetrics"),
        "logs": ((11.0, 4.15), "Logs\nElasticsearch + S3"),
        "traces": ((11.0, 2.95), "Traces\nJaeger"),
        "features": ((11.0, 1.75), "Features\nRedis + S3"),
        "query": ((11.0, 0.55), "Query / ML\nGrafana + Alerts"),
    }
    colors = {
        "service": "#dbeafe",
        "collector": "#dcfce7",
        "kafka": "#fef3c7",
        "flink": "#fde68a",
        "metrics": "#e0f2fe",
        "logs": "#fae8ff",
        "traces": "#fee2e2",
        "features": "#ccfbf1",
        "query": "#e5e7eb",
    }

    for key, (xy, text) in boxes.items():
        add_box(ax, xy, text, colors[key])

    add_arrow(ax, (2.95, 3.64), (3.1, 3.64))
    add_arrow(ax, (5.55, 3.64), (5.7, 3.64))
    add_arrow(ax, (8.15, 3.64), (8.3, 3.64))

    for y in [5.74, 4.54, 3.34, 2.14]:
        add_arrow(ax, (10.75, 3.64), (11.0, y))

    for y in [5.35, 4.15, 2.95, 1.75]:
        add_arrow(ax, (12.25, y), (12.25, 1.33))

    ax.text(
        0.65,
        0.75,
        "Flow: services emit telemetry -> collectors batch and enrich -> Kafka buffers/replays -> Flink computes rolling features -> storage and ML drive alerts.",
        fontsize=9,
        color="#334155",
    )

    fig.tight_layout(pad=1.0)
    fig.savefig(OUTPUT_PATH, bbox_inches="tight")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
