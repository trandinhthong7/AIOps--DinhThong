# FINDINGS.md

## 1. Hardest capability to replace

The hardest capability to replace is log search, not metrics or dashboards. The current stack spends `$13,900/month` on Splunk plus `$1,800/month` on Datadog indexed logs, and pain points show that on-call still waits more than 25 seconds for queries crossing seven days. My design compromises by not trying to make Loki a full Splunk clone. Loki becomes the 14-day hot incident search tier keyed by `service`, `env`, `severity`, and `incident_id`; raw logs move to S3 for 365 days. The compromise is that long-tail audit search becomes slower and more runbook-driven, but incident-time service-scoped search becomes cheaper and simpler.

## 2. Resilience traded for cost

The biggest resilience-for-cost trade is replacing managed Datadog/Splunk hot paths with self-hosted VictoriaMetrics, Loki, and Tempo. This saves roughly `$27.8k/month` at steady state: `$42.0k` current invoice down to `$14.2k` target. The cost is ownership risk. If Loki is unhealthy during a log-heavy incident, MTTR could gain 3-5 minutes while on-call falls back to S3/Splunk read-only. I accept that trade because historical median MTTR is `26m`, and the design cuts first-hypothesis time by grouping alerts and keeping traces richer than the current 1% sample. The migration plan keeps old paths live until week-8 gates pass.

## 3. If the cut requirement were 60%

The target design already models a 66.1% steady-state reduction, but the six-month cash view is weaker because Splunk has seven months left. If the requirement were a hard 60% by month six, I would change commercial sequencing: cut Datadog APM/log/custom-metric ingest first, reduce PagerDuty seats immediately from 65 to 35, and negotiate a Splunk partial-volume credit. I would not change the OTel + LGTM architecture or the decision to keep PagerDuty paging. This tells me the structure of cost is mostly ingest/index volume and contract timing, not dashboards or Statuspage.

## 4. Real-world pattern copied

The design copies the Grafana LGTM + OpenTelemetry Collector pattern used by many Kubernetes platforms: OTel as the vendor-neutral ingestion boundary, object storage as the durable backend, Grafana as the human surface, and sampling/label filtering before storage. I changed the pattern by adding an in-house evidence ledger and correlation service because the lab pain points are not only storage economics. Pain points 7 and 9 require a queryable record of actions like rollbacks/restarts, which plain LGTM does not provide.

## 5. Biggest unknown and first spike

The biggest unknown is whether Loki can hit the week-5 p99 target under realistic incident queries after reducing hot logs to 18GB/day. If that fails, the migration can derail around week 5 because Splunk cannot be exited safely. In the first week I would spike this specifically: replay two weeks of representative logs into Loki with the proposed label schema, run the top five Splunk saved searches rewritten as LogQL, and measure p50/p95/p99 query latency. The gate is p99 under 10 seconds for service/severity/incident windows and under 25 seconds for 14-day incident_id searches.

## A7. POC plan

The single most uncertain component is the Loki hot log tier. The first assumption to validate is: "service-scoped incident queries over 14 days remain under 10s p99 when hot retention is capped at 18GB/day and labels are limited to service/env/severity/incident_id." With three engineering days, I would export a representative 14-day log slice from Splunk, replay it through OTel Collector into a small Loki cluster, port the five most used Splunk queries, and record p50/p95/p99 latency plus index size. Passing measurement: p99 <10s for the top five incident queries and no query returns incomplete results compared with Splunk for the same time window.
