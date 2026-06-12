# Cost Model

## Assumptions and public-price anchors

- Current monthly cost comes from `current-stack.md`: about `$42,000/month`.
- Workload scale today: 300 hosts, 295 APM host equivalents, 1.05B Datadog-indexed log events/month, 52 GB/day Splunk indexed logs, 65 PagerDuty users, 270 synthetics.
- Target log plan: keep 18 GB/day structured logs in hot Loki for 14 days, archive all raw compressed logs to S3 for 365 days, and sample DEBUG/noisy request logs at the collector.
- Target trace plan: 10% baseline traces, 100% error/slow traces, 14-day hot Tempo, 90-day S3 blocks.
- Pricing anchors checked against public pages on 2026-06-12: AWS S3 Standard first 50TB is `$0.023/GB-month`; m7i.xlarge public listings are about `$0.2016/hour` or `$147/month`; PagerDuty Business list price is `$49/user/month`; Grafana Cloud docs list visualization as a per-active-user line item around `$15/user/month`. The model rounds up to include EBS, snapshots, cross-AZ traffic, and operational overhead.
- Reference URLs for reviewer spot checks: AWS S3 pricing (`https://aws.amazon.com/s3/pricing/`), AWS EC2 on-demand pricing (`https://aws.amazon.com/ec2/pricing/on-demand/`), PagerDuty pricing (`https://www.pagerduty.com/pricing/`), Grafana Cloud pricing (`https://grafana.com/pricing/`).

## Monthly target

| Cost line item | Today / month | Target / month | Unit driver | Current scale | Target-state assumption | Math / notes |
|---|---:|---:|---|---|---|---|
| Datadog APM hosts | $11,800 | $0 | host equivalents | 295 host equivalents | Replaced by OTel + Tempo | Remove APM-host tax after trace parity gate. |
| Datadog infrastructure metrics | $5,400 | $0 | hosts | 300 hosts | Replaced by OTel/Prometheus scrape -> VictoriaMetrics | Host metrics remain, storage moves self-hosted. |
| Datadog custom metrics overage | $2,200 | $0 | excess active series | ~440K excess active series | Collector drops `customer_id`/unbounded labels before ingest | Cardinality bot blocks repeat of pain point 4. |
| Datadog indexed logs | $1,800 | $0 | indexed events | 1.05B events/month | Replaced by Loki labels + S3 archive | No dual log hot tier after week 6. |
| Splunk Cloud log search | $13,900 | $0 after contract end; $13,900 during overlap | indexed GB/day | 52 GB/day, 30d hot | Exit at contract end; transition export capped at 100 GB/day | Month-six steady state assumes non-renewal notice filed in week 1. |
| PagerDuty Business | $3,900 | $1,715 | users | 65 users | 35 responders at `$49/user/month`; stakeholders use Statuspage/Slack | Paging retained, seats rationalized. |
| Grafana Cloud read-only mirror | $1,050 | $270 | active users | 12 viewers, 6 editors | 18 active users at `$15/user/month` for managed auth/plugins, or equivalent self-host support budget | Dashboards move to Grafana backed by VM/Loki/Tempo. |
| Statuspage | $290 | $290 | subscription | Business tier | Retain | Customer comms unchanged. |
| Datadog Synthetics | $1,360 | $250 | checks/compute | 270 checks | 40 blackbox/k6 critical checks from two regions | Drops redundant checks; alert coverage preserved. |
| Datadog tracing premium | $300 | $0 | add-on | current add-on | Replaced by Tempo | Included above. |
| OTel collector gateways | $0 | $450 | compute | none | 3 m7i.large-class gateways + buffer disks | Handles routing, filtering, tail-sampling. |
| VictoriaMetrics + vmalert | $0 | $2,200 | compute/storage | none | 6 m7i.xlarge-class nodes + 2TB gp3/EBS + snapshots | 90-day hot metrics, HA pair per AZ. |
| Loki log hot tier | $0 | $2,600 | compute/storage | none | 6 m7i.xlarge-class nodes, 14-day hot index, 18GB/day retained | Query p99 target < 10s for 14-day windows. |
| S3 raw log archive | $0 | $450 | GB-month + requests | none | 52GB/day raw compressed to ~9.5TB-month plus requests | Uses S3 Standard / lifecycle to IA after 30d. |
| Tempo trace tier | $0 | $900 | compute/storage | none | 3 m7i.xlarge-class nodes + S3 trace blocks | Tail sampling fixes 1% trace pain point. |
| AIOps correlation + evidence ledger | $0 | $1,100 | compute/storage | bash script today | 2 app nodes + small Postgres + S3 JSONL export | Groups alerts and stores decision audit. |
| OSS operational overhead | $0 in invoice | $4,000 | people-time | side responsibility today | 0.25 platform FTE equivalent | Explicitly accounts for self-hosted ownership. |
| **Total steady state** | **$42,000** | **$14,225** |  |  |  | **66.1% reduction** from invoice. |

## Six-month cash view

Splunk has seven months left and a 90-day non-renew notice, so the plan carries overlap while data is validated. During overlap, target operational cost is about `$28,125/month` (`$14,225 + $13,900` Splunk), only `33%` below current. The contractual cut lands after non-renewal. The design still satisfies the CTO's six-month target if the non-renew notice is filed in week 1 and the team negotiates a partial-volume transition credit or turns down Datadog first; otherwise finance sees the full saving in month 7. This is called out as a risk in `risks.md`.

## Sensitivity: data volume grows 2x faster

| Scenario | Expected target | 2x faster growth | Budget impact | First thing that breaks |
|---|---:|---:|---:|---|
| Metrics active series | 250K accepted series after label drops | 500K accepted series | VictoriaMetrics/EBS grows from `$2.2k` to about `$3.4k` | Cardinality guardrail and dashboard query latency before raw storage cost. |
| Structured logs hot tier | 18 GB/day retained hot | 36 GB/day hot | Loki grows from `$2.6k` to about `$4.4k` | Loki query latency and index size, not S3 archive cost. |
| Raw log archive | 9.5 TB-month compressed | 19 TB-month compressed | S3 line grows from `$450` to about `$850` | Still not budget-breaking; object storage is cheap. |
| Traces | 10% baseline + 100% error/slow | 20% effective baseline if traffic doubles | Tempo grows from `$900` to about `$1.5k` | Tail-sampling policy must tighten before compute doubles again. |

The budget breaks first on hot log tier compute, not cold storage. The mitigation is collector-side sampling and structured event promotion, not buying more Loki nodes by default.
