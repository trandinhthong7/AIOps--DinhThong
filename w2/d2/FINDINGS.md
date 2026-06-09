# FINDINGS.md

## RCA findings

Cluster chính là `c-000-000` với 15 alerts, trải trên `payment-svc`, `checkout-svc`, và `edge-lb`. RCA pipeline chọn root cause là `payment-svc` với class `connection_pool_exhaustion` và confidence `0.9`. Lý do cụ thể: alert đầu tiên xuất hiện ở `payment-svc` lúc 09:42 với `db_connection_pool_used_ratio` tăng từ warn lên crit, sau đó mới lan sang latency/error ở checkout và 5xx ở edge-lb. Graph cũng ủng hộ hướng này vì checkout gọi payment, còn edge-lb là entry point nên khả năng cao chỉ nhìn thấy propagation. Retrieval top-3 gồm INC-2025-11-08, INC-2025-09-05, INC-2026-05-10; incident gần nhất mô tả đúng pattern DB pool leak và cascade checkout.

Với confidence `0.9`, mình chưa dám deploy auto-remediation kiểu rollback hoàn toàn tự động. Nếu phải đặt threshold cho auto-rollback không cần SRE confirm, mình chọn `0.95`: cao hơn output hiện tại và đủ cao để chỉ chạy khi graph score và retrieval đều đồng thuận rất mạnh. Case không chắc nhất là `c-000-002`: root cause `cart-redis`, class `network_partition`, confidence `0.68`. Cluster này ít alert hơn nên bằng chứng temporal mỏng; retrieval có thể đang match theo service/metric keyword thay vì cùng cơ chế lỗi thật.

Mình không chọn bonus path vì yêu cầu chính đã đủ với retrieval-only: service map ổn định, incident history có nhiều pattern e-commerce lặp lại, và classifier kNN top-1 trả được class + action có thể audit được. Decision tree trên 30 incident dễ overfit, TF-IDF sẽ tốt hơn keyword nhưng chưa cần cho dataset nhỏ, còn LLM enrichment thêm chi phí và biến thiên trong khi không cần API key cho bài này.
