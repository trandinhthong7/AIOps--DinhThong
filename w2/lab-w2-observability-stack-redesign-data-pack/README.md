# Lab — Observability + AIOps Stack Redesign — Data Pack

This pack contains the inputs you need to do the architecture lab.

## Contents

```
data-pack/
├── services.json              The 10-service topology + 4 stores + 17 edges
├── current-stack.md           Vendor inventory + monthly cost breakdown
├── incidents_history.json     29 historical incidents (MTTD / MTTR / class / actions)
├── pain_points.md             10 operational pain points to address in your design
├── current-architecture.png   Block diagram of how data flows today
└── README.md                  This file
```

## How to read these inputs

Start with `current-architecture.png` to see the data flow today. Then read `current-stack.md` to understand what each piece does and how much it costs. Then `pain_points.md` to understand what is actually broken. Finally browse `incidents_history.json` to ground your assumptions about what kind of incidents the system actually faces.

You are **not** expected to inspect `incidents_history.json` programmatically. Reading the file as JSON in your editor and skimming is sufficient.

## Inputs you are explicitly NOT given

This is design work, not measurement work. You will need to make scaling assumptions explicit and defend them. You will not find tables of latency percentiles or ingest rate timeseries here — make the assumption, write it down, defend it.

## What you produce

See the handout for the full deliverable list. In short: one target-state architecture diagram, one component-decision table, one cost model, three ADRs, one twelve-week migration plan, one risk register, one local POC, and `FINDINGS.md`.

## Completed submission

Read the completed design in this order:

1. `architecture-target.mmd` — target-state architecture diagram.
2. `components.md` — component decision table.
3. `cost-model.md` — visible monthly cost model and sensitivity analysis.
4. `adr/adr-001-replace-saas-hot-observability-with-otel-lgtm.md` and `adr/adr-002-keep-pagerduty-move-correlation-upstream.md`.
5. `migration-plan.md` and `risks.md`.
6. `FINDINGS.md` — required reflection plus the POC plan.

The target steady-state run rate is about `$14.2k/month` versus the current `$42k/month`, a 66.1% reduction. The design keeps PagerDuty for paging, replaces Datadog/Splunk hot observability with OTel + VictoriaMetrics/Loki/Tempo/Grafana, and adds service-graph alert correlation plus an incident evidence ledger.
