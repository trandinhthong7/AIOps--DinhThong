# ADR 002 — Keep PagerDuty, Move Correlation And Evidence Upstream

## Context

PagerDuty is trusted as the paging surface, but it is receiving ungrouped incidents from Datadog, Splunk, and custom scripts. Pain point 5 describes 47 PagerDuty incidents in 90 seconds during one cascade, with 43 manually closed. Pain points 7 and 9 show that the team lacks an audit trail of decisions and cannot query actions like "all rollbacks on payment-svc in 90 days." Historical incidents show repeated classes such as connection-pool exhaustion and slow query; those repetitions are exactly what an evidence ledger should learn from.

## Decision

Retain PagerDuty Business for paging, but reduce active seats from 65 to 35 and route only grouped incidents into it. Build an in-house correlation and evidence layer before PagerDuty. The correlation service consumes alerts from vmalert, Loki-derived log events, and Tempo trace exemplars; it groups by stable fingerprint plus service graph. It writes each incident, hypothesis, action, confidence, and postmortem link into a small Postgres/S3 evidence ledger. Grafana links to the ledger during incident review.

## Alternatives Considered And Rejected

1. **Replace PagerDuty with Alertmanager only.** This would reduce SaaS spend further, but paging reliability, mobile workflows, escalation policies, and rotation management are not the current bottleneck. Replacing paging during an observability migration adds avoidable operational risk.

2. **Buy a SaaS AIOps correlator.** This may deliver faster grouping, but it keeps the team dependent on vendor-specific event models and adds another contract while the CTO is asking for cost reduction. The service graph is only 10 services and 17 edges, so an in-house first version is feasible.

3. **Do grouping inside Grafana Alerting only.** Grafana can group alert notifications, but it is not an incident evidence store and does not naturally answer "which action did we take last time?" across logs, traces, topology, and postmortems.

## Consequences

Positive consequences:

- Pager noise drops because one service-graph incident reaches PagerDuty instead of dozens of symptom alerts.
- On-call still uses the paging tool they trust, reducing migration training risk.
- Evidence becomes queryable for repeated action patterns, closing pain points 7 and 9.
- Seat reduction saves about `$2.2k/month` without weakening critical paging.

Negative consequences:

- The correlation service becomes a new critical path; a bug can suppress or over-group incidents.
- The team must define ownership for fingerprint rules, graph freshness, and evidence schema migrations.
- Early versions will be less sophisticated than commercial AIOps products, especially for novel incidents.
- If PagerDuty later adds better native correlation, there may be duplicated concepts to reconcile.
