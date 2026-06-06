# ShopX Incident Postmortem - Cart-Service Restart Loop

## Summary

On 2026-06-01, ShopX experienced a cart-service incident that triggered official alerts at 23:04 UTC. The alerts reported high cart-service HTTP 5xx rate, repeated cart-service pod restarts, and upstream timeout rates in order-service and payment-service.

Our analysis of 24-hour metrics and logs shows that the incident started much earlier than the alert time. The earliest incident-related log signal appeared at 2026-06-01 06:30:32 UTC, when cart-service started logging GC overhead warnings. ProductCatalogCache eviction failures started shortly after at 2026-06-01 06:33:57 UTC. Automated metric anomaly detection later identified JVM GC pause anomalies around 2026-06-01 16:18:00 UTC. The restart/OOM phase began around 2026-06-01 19:59 UTC, followed by visible 5xx errors and downstream timeouts.

## WHEN

The anomaly did not start at the official alert time. It had several earlier phases.

| Time UTC | Signal |
|---|---|
| 2026-06-01 06:30:32 | First `GC overhead limit warning` in cart-service logs |
| 2026-06-01 06:33:57 | First `ProductCatalogCache eviction failed` log |
| 2026-06-01 06:34:56 | First `Slow response detected` log |
| 2026-06-01 16:18:00 | Rolling Z-score detected JVM GC pause anomaly |
| 2026-06-01 18:59:30 | cart-service p99 latency first exceeded 500ms |
| 2026-06-01 19:59:15 | First `OutOfMemoryError imminent` log |
| 2026-06-01 19:59:31 | First `Container OOMKilled: memory limit exceeded` log |
| 2026-06-01 20:00:00 | cart-service `container_restart_count` first increased |
| 2026-06-01 20:46:00 | api-gateway `cart_upstream_error_rate` first exceeded 5% |
| 2026-06-01 20:55:00 | cart-service HTTP 5xx rate first exceeded 5% |
| 2026-06-01 20:55:00 | order-service upstream timeout rate first exceeded 5% |
| 2026-06-01 21:28:00 | payment-service upstream timeout rate first exceeded 5% |
| 2026-06-01 23:04:00 | Official alert time from assignment |

The earliest clear log signal was at 2026-06-01 06:30:32 UTC. The earliest credible metric signal was JVM GC pause anomaly around 2026-06-01 16:18:00 UTC. Therefore, there were silent signals several hours before the official alert.

## WHERE

The primary affected service was `cart-service`.

The earliest log indicators were in cart-service:

| Log Pattern | Count | First Seen UTC |
|---|---:|---|
| `GC overhead limit warning` | 2084 | 2026-06-01 06:30:32 |
| `ProductCatalogCache eviction failed` | 2671 | 2026-06-01 06:33:57 |
| `Slow response detected` | 1552 | 2026-06-01 06:34:56 |
| `OutOfMemoryError imminent` | 936 | 2026-06-01 19:59:15 |
| `Container OOMKilled` | 823 | 2026-06-01 19:59:31 |

The earliest metric indicators were also in cart-service:

| Metric | Signal |
|---|---|
| `jvm_gc_pause_ms_avg` | Rolling Z-score anomaly at 2026-06-01 16:18:00 UTC |
| `http_p99_latency_ms` | Exceeded 500ms at 2026-06-01 18:59:30 UTC |
| `container_restart_count` | First increased at 2026-06-01 20:00:00 UTC |
| `http_5xx_rate` | First exceeded 5% at 2026-06-01 20:55:00 UTC |

Downstream impact appeared after cart-service degradation:

| Service | Metric | First Impact UTC | Max Observed |
|---|---|---:|---:|
| api-gateway | `cart_upstream_error_rate` | 2026-06-01 20:46:00 | 20.12% |
| order-service | `upstream_timeout_rate` | 2026-06-01 20:55:00 | 27.05% |
| payment-service | `upstream_timeout_rate` | 2026-06-01 21:28:00 | 15.82% |

## WHAT

Our root cause hypothesis is that cart-service experienced JVM heap pressure caused by ProductCatalogCache eviction failure.

The likely mechanism was:

1. ProductCatalogCache eviction began failing under heap pressure.
2. JVM heap usage stayed high, causing frequent GC overhead warnings.
3. GC pressure and heap saturation increased cart-service latency.
4. Around 19:59 UTC, logs reported `OutOfMemoryError imminent`.
5. Containers were then OOMKilled, which matches the first restart count increase at 20:00 UTC.
6. Restarted pods experienced slow cache warm-up and unstable connectivity.
7. This created a restart loop and degraded cart-service availability.
8. Cart-service failures propagated to api-gateway, order-service, and payment-service as upstream errors and timeouts.

Although the `memory_usage_bytes` metric did not exceed 80% of the 2GB container memory limit, logs clearly showed heap pressure, OutOfMemoryError warnings, and OOMKilled events. This suggests that application-level JVM heap pressure was a more useful signal than container RSS memory percentage alone.

## Anomaly Detection Methods

We tested two anomaly detection methods: Rolling Z-score and MAD.

### Method 1: Rolling Z-score

Rolling Z-score compared each metric value against a rolling one-hour baseline. A value was marked anomalous when the absolute z-score exceeded 3.

| Metric | First Anomaly UTC | Count |
|---|---:|---:|
| `http_p99_latency_ms` | 2026-06-01 02:07:30 | 40 |
| `http_5xx_rate` | 2026-06-01 20:17:30 | 13 |
| `jvm_gc_pause_ms_avg` | 2026-06-01 16:18:00 | 14 |
| `container_restart_count` | 2026-06-01 20:00:00 | 35 |

The early p99 latency anomaly at 02:07:30 appears likely to be an isolated spike or false positive. The JVM GC pause anomaly at 16:18:00 is more credible because it aligns with the later heap pressure and OOMKilled log patterns.

### Method 2: MAD

MAD used median absolute deviation to detect values far from the global median.

| Metric | First Anomaly UTC | Count |
|---|---:|---:|
| `http_p99_latency_ms` | 2026-06-01 16:45:30 | 791 |
| `http_5xx_rate` | 2026-06-01 20:08:00 | 381 |
| `jvm_gc_pause_ms_avg` | 2026-06-01 17:59:00 | 101 |
| `container_restart_count` | Not detected | 0 |

MAD detected the broad latency degradation earlier than the visible 5xx spike, but it produced many latency anomalies because latency is naturally skewed. MAD did not work well for `container_restart_count` because restart count is a cumulative step-like counter.

### Comparison

Rolling Z-score was better for detecting sudden changes such as restart count and sharp 5xx spikes. MAD was better at highlighting sustained degradation in skewed metrics such as latency, but it produced more noisy results. Both methods agreed that cart-service degraded before the official alert.

The most credible automated early metric signal was JVM GC pause anomaly between 16:18 UTC and 17:59 UTC. The earliest overall signal came from logs at 06:30 UTC.

## Recommendations

- Add alerting for `GC overhead limit warning` and `ProductCatalogCache eviction failed` log patterns.
- Add JVM heap usage and GC overhead dashboards, not only container memory RSS.
- Alert on sustained cart-service p99 latency increase before 5xx crosses 5%.
- Add restart-loop detection based on `container_restart_count` derivative.
- Investigate ProductCatalogCache eviction policy, memory sizing, and cache warm-up behavior.
- Add protection around cache warm-up to avoid restart amplification.
- Review DB connection pool limits and behavior during restart storms.

## Bonus Pipeline Design

The proposed AIOps detection and triage pipeline is documented in [PIPELINE.md](PIPELINE.md). It explains how metrics and logs should flow through collection, feature extraction, anomaly detection, correlation, alerting, and postmortem evidence generation, including why each tool was selected.
