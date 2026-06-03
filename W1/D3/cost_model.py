from __future__ import annotations

from dataclasses import dataclass


DAYS_PER_MONTH = 30
HOURS_PER_MONTH = 730


@dataclass(frozen=True)
class ScaleTier:
    name: str
    services: int
    log_gb_per_day: float
    metric_events_per_sec: int


TIERS = [
    ScaleTier("Small", services=10, log_gb_per_day=50, metric_events_per_sec=100_000),
    ScaleTier("Medium", services=100, log_gb_per_day=500, metric_events_per_sec=1_000_000),
    ScaleTier("Large", services=1_000, log_gb_per_day=5_000, metric_events_per_sec=10_000_000),
]


def money(value: float) -> str:
    return f"${value:,.0f}"


def estimate_build_cost(tier: ScaleTier) -> dict[str, float]:
    log_gb_month = tier.log_gb_per_day * DAYS_PER_MONTH
    hot_log_gb = tier.log_gb_per_day * 7
    cold_log_gb = tier.log_gb_per_day * 23
    metric_million_events_sec = tier.metric_events_per_sec / 1_000_000

    # Storage assumptions:
    # - Elasticsearch hot logs: data plus replicas/index overhead, approximated at $0.18/GB-month.
    # - S3 Parquet cold logs: compacted to 50% of raw size at $0.023/GB-month.
    # - VictoriaMetrics metric store: $2,000/month per 1M metric events/sec for 30-day retention.
    # - Jaeger trace store: 1% sampling, scaled primarily by service count.
    hot_log_storage = hot_log_gb * 0.18
    cold_log_storage = cold_log_gb * 0.5 * 0.023
    metric_storage = metric_million_events_sec * 2_000
    trace_storage = max(250, tier.services * 15)
    storage = hot_log_storage + cold_log_storage + metric_storage + trace_storage

    # Compute assumptions:
    # - Kafka: 3 brokers baseline, then scales with log ingest and metric event rate.
    # - Flink: 16 cores per 1M metric events/sec, $75/core-month.
    # - OTel collectors and query nodes scale with service count and ingest volume.
    kafka = 1_200 + (tier.log_gb_per_day * 2.0) + (metric_million_events_sec * 1_300)
    flink = max(300, metric_million_events_sec * 16 * 75)
    collectors = max(150, tier.services * 8)
    query_nodes = max(300, tier.log_gb_per_day * 1.5)
    compute = kafka + flink + collectors + query_nodes

    # Network assumptions:
    # 20% of monthly log volume crosses AZ/region boundaries at $0.02/GB.
    # Metrics/traces add a smaller network component proportional to events/sec.
    network = (log_gb_month * 0.20 * 0.02) + (metric_million_events_sec * 500)

    total = storage + compute + network
    return {
        "Storage": storage,
        "Compute": compute,
        "Network": network,
        "Build total": total,
    }


def estimate_datadog_cost(tier: ScaleTier) -> float:
    log_gb_month = tier.log_gb_per_day * DAYS_PER_MONTH
    metric_million_events_sec = tier.metric_events_per_sec / 1_000_000

    infra_hosts = tier.services * 2
    infra_apm = infra_hosts * 55
    log_ingest = log_gb_month * 0.10
    indexed_logs = log_gb_month * 0.20 * 1.70
    custom_metrics = metric_million_events_sec * 12_000

    return infra_apm + log_ingest + indexed_logs + custom_metrics


def print_markdown_table(rows: list[dict[str, str]]) -> None:
    headers = [
        "Tier",
        "Services",
        "Log/day",
        "Metric events/sec",
        "Storage",
        "Compute",
        "Network",
        "Build total",
        "Datadog SaaS",
        "Buy/Build ratio",
    ]
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        print("| " + " | ".join(row[header] for header in headers) + " |")


def main() -> None:
    rows: list[dict[str, str]] = []
    for tier in TIERS:
        build = estimate_build_cost(tier)
        datadog = estimate_datadog_cost(tier)
        ratio = datadog / build["Build total"]

        rows.append(
            {
                "Tier": tier.name,
                "Services": f"{tier.services:,}",
                "Log/day": f"{tier.log_gb_per_day:,.0f} GB",
                "Metric events/sec": f"{tier.metric_events_per_sec:,}",
                "Storage": money(build["Storage"]),
                "Compute": money(build["Compute"]),
                "Network": money(build["Network"]),
                "Build total": money(build["Build total"]),
                "Datadog SaaS": money(datadog),
                "Buy/Build ratio": f"{ratio:.1f}x",
            }
        )

    print("# Monthly Observability Cost Estimate")
    print()
    print_markdown_table(rows)
    print()
    print("Assumptions:")
    print("- Build stack: OTel Collector, Kafka, Flink, VictoriaMetrics, Elasticsearch hot tier, S3 Parquet cold tier, Jaeger, Grafana.")
    print("- Logs: 7 days hot in Elasticsearch, 23 days cold in S3 Parquet with 50% compression.")
    print("- Metrics: 30-day retention in VictoriaMetrics, scaled from $2,000/month per 1M metric events/sec.")
    print("- Datadog estimate includes infrastructure/APM hosts, log ingest, 20% indexed logs, and custom metric volume.")
    print("- People cost is excluded; self-hosting usually needs SRE time that grows with scale.")


if __name__ == "__main__":
    main()
