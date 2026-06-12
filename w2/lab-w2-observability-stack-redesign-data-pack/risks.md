# Risk Register

| Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|
| Splunk contract saving misses the six-month window because there are seven months left and 90-day notice is required. | High | High | File non-renew notice in week 1, request partial-volume transition credit, and cut Datadog ingest first so invoice run-rate still drops before Splunk exits. | Platform lead + Finance |
| Loki hot-tier queries exceed 10s p99 under 36GB/day growth. | Medium | High | Run week-5 load test at 2x expected volume, cap hot labels to service/env/severity/incident_id, and keep Splunk fallback until p99 passes for 7 days. | Observability owner |
| OTel Collector drops or redacts useful incident evidence while filtering PII/cardinality. | Medium | Medium | Shadow compare dropped spans/logs for two weeks, sample denied labels to a quarantine bucket, and require service-owner approval for new denylist rules. | Security + Platform |
| Correlation service over-groups unrelated incidents and suppresses distinct pages. | Medium | High | Start non-paging shadow mode, compare grouped output against current PagerDuty for one week, and enforce "split if root services differ or first alerts are >120s apart." | AIOps engineer |
| Team skill gap operating VM/Loki/Tempo creates longer MTTR during the first quarter. | Medium | Medium | Assign weekly rotation owner, run two game days before cut-over, and keep vendor read-only fallbacks for 30 days after official switch. | SRE manager |
| Compliance/security teams reject S3 archive workflow after Splunk decommission plan. | Low | High | Produce audit search runbook in week 5, validate 10 known compliance queries, and keep 100GB/day Splunk export window until sign-off. | Security lead |
