# Detection Approach — DESIGN.md

## Approach em dùng

Em dùng rule-based streaming detector có state ngắn hạn. Pipeline giữ cửa sổ 30 mẫu gần nhất để quan sát xu hướng memory, đồng thời kiểm tra ngưỡng an toàn cho các tín hiệu đặc trưng của từng loại fault.

## Tại sao chọn approach này

Generator có baseline khá ổn định và mỗi fault có fingerprint rõ ràng, nên rule-based detection phù hợp hơn một mô hình phức tạp trong lab 3 giờ. Cách này chạy online từng event, không cần training trước, dễ giải thích, ít false alert trước khi fault xảy ra.

## Cách hoạt động

Mỗi request `POST /ingest` được parse thành `metrics`, `logs`, `timestamp`. Detector kiểm tra theo thứ tự:

1. `dependency_timeout`: `upstream_timeout_rate`, `http_5xx_rate`, và `http_p99_latency_ms` cùng tăng mạnh, hoặc log có bằng chứng timeout/circuit breaker.
2. `traffic_spike`: request/sec tăng rất cao kèm queue depth và latency tăng, hoặc log báo overload/queue high.
3. `memory_leak`: memory utilization tăng bất thường kèm GC pause cao và có xu hướng tăng trong cửa sổ gần nhất, hoặc log có OutOfMemory/GC pressure.

Khi phát hiện fault, pipeline ghi một dòng JSON vào `alerts.jsonl` với `timestamp`, `type`, `severity`, `message`. Mỗi loại alert chỉ fire một lần để tránh spam file output.

## Parameters em chọn

- Window size: 30 samples, đủ để nhìn xu hướng ngắn hạn nhưng vẫn nhẹ cho streaming.
- Memory leak:
  - `memory_util >= 55%`, `gc_pause >= 45ms`, và memory tăng ít nhất `20MB` trong 6 mẫu gần nhất.
  - Hoặc `memory_util >= 72%` và `gc_pause >= 35ms`.
- Traffic spike:
  - `http_requests_per_sec >= 300`, `queue_depth >= 40`, `http_p99_latency_ms >= 180ms`.
- Dependency timeout:
  - `upstream_timeout_rate >= 5%`, `http_5xx_rate >= 2%`, `http_p99_latency_ms >= 150ms`.

Các ngưỡng này cao hơn baseline bình thường trong đề bài, nhưng thấp hơn rất nhiều so với giá trị khi fault được inject, nên giúp giảm false positive và vẫn phát hiện nhanh.

## Cải thiện nếu có thêm thời gian

Em sẽ thêm adaptive baseline theo rolling median/MAD cho từng metric, lưu trạng thái detector ra file để restart không mất context, và thêm test tự động chạy generator ở tốc độ cao cho nhiều birthday khác nhau.
