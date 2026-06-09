# SUBMIT.md

## EOD Checkpoint

1. Confidence của top-1 trong cluster lớn nhất `c-000-000` là `0.9`. Nếu phải set threshold để auto-rollback không cần SRE confirm, em chọn `0.95`. Lý do: cluster lớn có tín hiệu rất mạnh từ temporal order (`payment-svc` báo pool trước), graph dependency (checkout gọi payment, edge chỉ thấy downstream 5xx), và retrieval khớp các incident pool exhaustion cũ. Dù vậy rollback tự động là hành động rủi ro nên em muốn threshold cao hơn confidence hiện tại, trừ khi có thêm deploy-event evidence.

2. Variant classifier em chọn là A rule-based/kNN retrieval. Chạy thực tế ổn: top-1 incident cung cấp `root_cause_class`, remediation được tách thành action list, và fallback graph-only vẫn tồn tại khi retrieval rỗng. Trade-off với LLM là kNN ít linh hoạt hơn trong diễn giải ngôn ngữ, nhưng deterministic, không cần API key, dễ debug, và phù hợp auto-grader. Paid/free LLM có thể viết reasoning tốt hơn nhưng tăng latency, chi phí, và rủi ro output lệch schema.

3. Pipeline này gần nhóm product event-correlation/RCA dựa trên topology + historical retrieval nhất, giống hướng Moogsoft/BigPanda/Dynatrace hơn là một chatbot LLM thuần. Với GeekShop, lựa chọn đó hợp lý vì alert volume cao, service map tương đối ổn định, và các incident lặp lại theo pattern như connection pool, queue lag, cache/DB contention. em sẽ chỉ đổi sang LLM-heavy khi incident history ít cấu trúc hơn hoặc cần tổng hợp logs/traces dạng text dài.