# ADR 001 — Replace SaaS Hot Observability With OTel + LGTM

## Context

The current observability invoice is about `$42,000/month`. The largest controllable lines are Datadog APM/metrics/logs and Splunk Cloud log search, together about `$35,100/month`. Pain points show that spend is not translating into faster diagnosis: Splunk queries crossing seven days take more than 25 seconds, traces are sampled at only 1%, and on-call still switches across Datadog, Splunk, PagerDuty, and Grafana during multi-service incidents. Historical incidents show recurring patterns in payment, checkout, catalog-db, and search; this is a workload where graph-aware traces and hot, service-scoped logs matter more than retaining every raw line in an expensive indexed tier.

## Decision

Adopt OpenTelemetry Collector as the ingestion control plane and move the hot query tier to the Grafana LGTM-style stack: VictoriaMetrics for metrics, Loki for structured logs, Tempo for traces, and Grafana as the primary human surface. Keep raw logs in S3 cold archive with lifecycle rules. Apply tail sampling for traces: retain 100% of error/slow traces and 10% baseline. Apply collector-side log filtering and cardinality guardrails before storage.

## Alternatives Considered And Rejected

1. **Stay on Datadog and negotiate a discount.** This is lowest migration risk but does not solve fragmentation with Splunk, does not give us label/cardinality guardrails in developer workflow, and a 40% cut would require a large commercial concession rather than an architectural fix.

2. **Move everything to Splunk Observability Cloud.** This consolidates with the existing Splunk contract, but Splunk is already the source of log query latency and lock-in pain. It also keeps cost tied to ingest volume rather than forcing sampling and retention discipline.

3. **Use Grafana Cloud for all signals.** This reduces operational burden compared with self-hosting, but the target cost is less predictable because log and trace ingest still become vendor-metered. It is a fallback if the three-day POC shows self-hosted Loki/Tempo cannot hit query SLOs.

## Consequences

Positive consequences:

- Estimated steady-state spend falls from `$42k/month` to about `$14.2k/month`, a 66% reduction.
- Tracing improves from 1% random sampling to tail sampling that keeps the traces most useful for RCA.
- On-call gets one query surface in Grafana and one ingestion policy layer in OTel Collector.
- Cardinality controls move left, preventing another `customer_id` metric explosion.

Negative consequences:

- The platform team now owns more stateful systems: VictoriaMetrics, Loki, Tempo, and their storage.
- Splunk power users lose SPL and some compliance-search ergonomics unless archived logs are hydrated into a separate audit workflow.
- During the migration there is an overlap period where both Splunk and Loki run, so finance may not see the full saving until the Splunk notice period clears.
- Query behavior changes; saved dashboards and runbooks must be ported and verified rather than mechanically copied.
