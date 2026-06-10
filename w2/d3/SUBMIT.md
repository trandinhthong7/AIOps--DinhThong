# SUBMIT.md

## EOD Checkpoint

1. Mình chạy 20 request liên tiếp với dataset 20 alert thật qua `POST /incident`, đọc header `X-Response-Time-Ms`. Kết quả warm path: p50 `0.576ms`, p99 `0.841ms`; wall-clock client p50 khoảng `1.056ms`, p99 có một spike `13.920ms`. Phase trung bình trong body: validate `0.034ms`, correlate `0.087ms`, RCA `0.016ms`, LLM `0.000ms`, serialize `0.008ms`. Request cold trước đó có RCA khoảng `1.361ms`; sau đó cache làm RCA gần như mất khỏi critical path. Nếu input gấp 10 lần, validate, correlate và serialize scale gần tuyến tính theo số alert; graph/history load là fixed cost ở startup, còn LLM đang bypass bằng `AIOPS_USE_LLM=false`.

2. Mình test concurrency bằng Python `ThreadPoolExecutor(max_workers=4)`, tổng 20 request. Kết quả không có lỗi, elapsed `15.304ms`, p50 header `1.706ms`, p99 header `2.080ms`, p50 wall `2.447ms`, p99 wall `3.036ms`. Bottleneck đầu tiên quan sát được là single worker phải xử lý CPU-bound correlation/RCA tuần tự trong event loop/threadpool, nhưng dataset nhỏ nên chưa thành vấn đề. Fallback path có sẵn: LLM bị bypass mặc định, RCA dùng graph+retrieval; nếu bật `AIOPS_USE_LLM=true` nhưng chưa cấu hình provider, service vẫn trả graph+retrieval và tăng metric `aiops_llm_failures_total`.

3. `/healthz` chỉ check process còn sống và trả `{"status":"ok"}`. `/readyz` check graph đã load, history đã load, và hàm `correlate` import được; response còn có `graph_version` để debug drift. Tách hai endpoint vì liveness dùng để restart process khi chết, còn readiness dùng để quyết định service có nên nhận traffic không. Khi LLM API down, `/readyz` vẫn pass vì trong thiết kế này LLM không phải dependency bắt buộc; dependency bắt buộc là graph + incident history + correlate function.
