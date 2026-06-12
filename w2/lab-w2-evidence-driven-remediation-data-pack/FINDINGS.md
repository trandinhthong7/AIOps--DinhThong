# FINDINGS.md

## 1. Similarity function

I used a hybrid similarity function instead of a single metric-only score. The final score is `0.30 log token Jaccard + 0.18 keyword Jaccard + 0.25 trace edge similarity + 0.15 metric similarity + 0.12 affected-service overlap`. I chose this because the live incidents contain raw logs/traces while history contains aggregated signatures, so exact string matching is too brittle. For example, E01 matched the historical connection-pool incidents with top similarities `0.4964`, `0.4405`, and `0.4405`; all three had matching pool keywords plus checkout/payment trace shape. I considered metric-only similarity, but it would fail E06 because logs point toward payment pool exhaustion while traces point toward cart/cart-redis. Metrics are useful as supporting evidence, not the main signal.

## 2. Outcome-weighted voting

Outcome weighting changes candidate votes by reducing partial/failed precedent influence. In E05, pure similarity voting gave `rollback_service(payment-svc)=0.8107`, `increase_pool_size(payment-svc)=0.6732`, `restart_pod(payments-db)=0.0985`, and `page_oncall=0.0490`. After outcome weighting, the partial pool incident was discounted, so rollback dropped to `0.7351` and page dropped to `0.0221`, while the successful increase-pool precedent stayed `0.6732`. The selected action for E05 was still `page_oncall` because the decision layer detected log/trace conflict, but the evidence block keeps the weighted candidate list visible for audit.

## 3. EV-style decision example

For E01, the candidate set was `rollback_service(payment-svc)` vote `0.7827`, `increase_pool_size(payment-svc)` vote `0.7166`, and `page_oncall` vote `0.0737`. The top neighbors were `INC-2025-11-08` similarity `0.4964` success, `INC-2025-09-05` similarity `0.4405` success, and `INC-2026-05-10` similarity `0.4405` partial. I selected `increase_pool_size(payment-svc, 50->100)` despite rollback having a slightly higher vote because the action catalog says pool increase has `cost_min=1`, `downtime_min=0`, and blast radius `1`, while rollback costs `10` minutes and `2` minutes downtime. Confidence was `0.812`, and the blast-radius gate passed.

## 4. Escalation behavior

The engine escalated with `page_oncall` on E02, E04, E05, E06, and E07. E02 was correct because TLS/certificate rotation is marked manual in the evidence gate. E04 was acceptable because DNS/NXDOMAIN is infra-layer and the expected set allows page or DNS rollback. E05 and E06 escalated because `log_trace_conflict_gate` fired: pool/deadlock logs suggested payment, while trace/metric evidence made the situation ambiguous. E07 escalated because informer/cache-stale keywords looked novel/manual and the expected answer was page. Against `eval/expected.json`, all five escalations were accepted and no `must_not_action` was violated.

## 5. Likely failure mode

The most likely failure mode is a spoofed or generic log pattern where many incidents contain the same text such as `degraded behavior detected` while the real root cause is only visible in traces. E06 is the closest example: retrieval strongly favored connection-pool history (`max_similarity=0.5423`) and candidate votes wanted rollback/increase on payment, but the decision layer had to override with page because evidence conflicted. A concrete improvement would be to add a learned trace-first reranker or causal lead-lag scorer over trace edges. I did not implement it because the eval set is small and the current transparent gates already reached `8/8` with auditable evidence.

## Run result

`python3 grade.py --audit audit.jsonl --expected eval/expected.json` returned `Correct: 8/8`, `Forbidden: 0/8`, `Missing: 0/8`, with auto-rubric estimate `85/85` before manual FINDINGS review.
