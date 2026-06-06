# SUBMIT.md

## Group Reflection

In this lab, our group learned how to investigate an incident by combining metrics and logs instead of relying only on the final alert. At first, the official alert made the problem look like a simple cart-service 5xx spike and restart issue. However, after building a timeline from the raw telemetry, we found that the incident had several earlier warning signs. The most useful lesson was that different signals appear at different stages of the failure. Logs showed GC overhead and ProductCatalogCache eviction failures many hours before the alert, while metrics later showed JVM GC pause anomalies, p99 latency degradation, container restarts, HTTP 5xx errors, and downstream timeouts.

We also learned that anomaly detection methods need interpretation. Rolling Z-score was useful for detecting sudden changes such as restart count and 5xx spikes, but it also produced an early latency anomaly that looked like an isolated spike. MAD was better at finding broad degradation in latency, but it produced many anomaly points because latency data was skewed. This showed us that automated detection should be paired with service knowledge and log evidence.

The main takeaway is that an AIOps workflow should connect symptoms across layers: application logs, JVM behavior, container restarts, service latency, error rates, and downstream dependency failures. If alerts had existed for GC overhead and cache eviction failures, the team could have detected the problem much earlier than 23:04 UTC.

## Contributions

- Member 1: Loaded and validated metric datasets, checked timestamp intervals, missing values, and the 30-minute telemetry gap.
- Member 2: Created cart-service metric timeline analysis and identified latency, restart, and 5xx escalation times.
- Member 3: Analyzed downstream impact in api-gateway, order-service, and payment-service.
- Member 4: Implemented Rolling Z-score and MAD anomaly detection and compared their results.
- Member 5: Analyzed cart-service logs, grouped log patterns, and identified GC overhead, cache eviction failure, OOM, and restart-loop evidence.
- Member 6: Wrote the technical findings, root cause hypothesis, and recommendations.
- Member 7: Reviewed the notebook, validated evidence consistency, and prepared final submission files.
