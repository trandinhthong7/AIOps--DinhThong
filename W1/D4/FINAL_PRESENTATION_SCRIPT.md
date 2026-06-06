# FINAL PRESENTATION SCRIPT - AIO1 W1

## Slide 1 - Cover

Chào thầy/cô và các bạn. Nhóm em trình bày bài W1 về anomaly detection và RCA cho ShopX. Mục tiêu của phần này là trả lời ba câu hỏi chính: khi nào tín hiệu đáng tin bắt đầu, service nào là nơi có khả năng phát sinh lỗi gốc, và chuỗi bằng chứng nào giải thích được sự cố.

## Slide 2 - Timeline Tóm Tắt

Slide này là timeline rút gọn của toàn bộ kết luận. Điểm đầu tiên cần phân biệt là `06:08`: đây là raw crossing của MAD trên `cart http_5xx_rate`, nhưng bị loại khỏi RCA vì baseline false positive rất cao, `297/720`.

Tín hiệu đáng tin đầu tiên là log của cart-service: `06:30` GC overhead warning với heap `93%`, sau đó `06:33` ProductCatalogCache eviction failed vì heap pressure quá cao. Metric đáng tin bắt đầu muộn hơn: p99 latency lúc `14:40`, memory lúc `16:26`, GC pause lúc `17:50`, OOMKilled lúc `19:59`, restart lúc `20:00`, và sustained 5xx impact lúc `20:41`.

Ý chính: 5xx xuất hiện trong timeline, nhưng không phải mốc root cause. Root cause chain bắt đầu từ GC/cache/memory evidence của cart-service.

## Slide 3 - Answer First

Nếu trả lời ngắn gọn: WHEN là `06:30/06:33` ở log và `14:40` ở metric. WHERE là `cart-service`, vì các template GC/cache/OOM xuất hiện trước downstream. HOW là heap/cache pressure: cache eviction thất bại, GC pressure tăng, sau đó OOMKilled và restart làm lỗi lan ra caller.

Một caveat quan trọng là `memory_usage_bytes` không tự chứng minh vượt limit, vì max khoảng `1.70GB` trong khi limit là `2.15GB`. Bằng chứng vượt limit đến từ log `Container OOMKilled: memory limit exceeded`.

## Slide 4 - EDA

Slide này cho thấy dữ liệu đã được load đầy đủ: mỗi service có `2,820` dòng, interval 30 giây, bao phủ đủ một ngày từ `2026-06-01 00:00` đến `23:59:30`. Notebook cũng cho thấy missing chính là `0%`, nên mình có thể dùng baseline 6 giờ đầu một cách nhất quán.

Phần phân phối cho thấy nhiều metric cart-service bị right-skewed và heavy-tail. Ví dụ p99 latency skew `3.31`, 5xx rate skew `2.77`, restart count skew `3.20`. Đây là lý do không dùng mean/std đơn giản làm detector chính; median và MAD phù hợp hơn vì robust hơn với tail/outlier.

## Slide 5 - EDA Baseline 6 Giờ Cho 5xx

Slide này giải thích riêng baseline của `cart-service/http_5xx_rate`. 6 giờ đầu được dùng vì đây là cửa sổ trước OOM/restart, có `720` điểm ở interval 30 giây, đủ để tính median, MAD và percentile.

Figure bên trái cho thấy trong chính baseline, 5xx đã rất noisy. Median chỉ `0.065`, nhưng p75 là `1.06`, p95/p99 là `2.00`. Ngưỡng MAD cũ chỉ `0.354`, tức nằm quá thấp so với vùng nhiễu bình thường. Vì vậy MAD flag `297/720` điểm trong baseline.

Kết luận audit: `06:08` chỉ là lần vượt ngưỡng thô của MAD, không phải mốc RCA đáng tin.

## Slide 6 - Anomaly Detectors & Why

Nhóm dùng ba hướng detector. Thứ nhất là robust MAD, đây là primary detector cho RCA vì dễ giải thích: với từng metric, threshold bằng `median + 3 * 1.4826 * MAD` trên baseline 6 giờ đầu. Nó map trực tiếp về service, metric, value và threshold.

Thứ hai là Isolation Forest. IF được train trên 6 giờ đầu cho từng service, với input là vector numeric metrics tại từng timestamp sau RobustScaler. Nó dùng để phát hiện trạng thái đa biến bất thường, nhưng không dùng làm RCA anchor vì khó giải thích rõ bằng từng metric và hiện tại chưa model hóa time-series window.

Thứ ba là EWMA. EWMA dùng `span=20` để smooth noise và nhìn drift/trend. Trong code, EWMA cũng được so với robust MAD threshold trên chuỗi đã smooth. Tuy nhiên EWMA chỉ dùng làm trend visualization, không làm decision rule chính.

## Slide 7 - Metric Evidence Chart

Slide này nhìn vào chart metric của cart-service. Memory bắt đầu tăng và vượt MAD lúc `16:26`. GC pause vượt ngưỡng lúc `17:50`, với giá trị khoảng `131.8ms` so với threshold `104.3ms`. Restart count tăng từ `0` lên `1` lúc `20:00`, ngay sau OOMKilled.

Điểm quan trọng là thứ tự: memory/GC/latency xấu đi trước, restart và 5xx đến sau. Vì vậy cart-service là origin candidate tốt hơn các downstream service.

## Slide 8 - Exact MAD Evidence

Bảng này là evidence định lượng từ robust MAD. `http_p99_latency_ms` vượt threshold lúc `14:40`, value `148.70` so với median baseline `50.10` và threshold `122.82`. `memory_usage_bytes` vượt lúc `16:26`, khoảng `0.62GB` so với threshold `0.57GB`. `jvm_gc_pause_ms_avg` vượt lúc `17:50:30`, value `131.80` so với threshold `104.33`. Restart count tăng lúc `20:00`.

Dòng `http_5xx_rate` lúc `06:08` vẫn được giữ trong bảng để minh bạch, nhưng đây là detector failure case vì baseline FP quá cao.

## Slide 9 - Auditing: MAD Fails For 5xx

Slide này trả lời câu hỏi “mình có mishandle gì không?”. Công thức MAD không sai. Sai là ban đầu dùng MAD một điểm cho metric 5xx quá noisy.

Detector sửa lại là `http_5xx_sustained`. Đây là rule, không phải ML. Với cart-service, baseline p99 của 5xx là `2.00`; threshold thực chất đến từ `p99 * 1.5 = 3.00`. Detector cần `5/10` điểm gần nhất vượt threshold, tức 5 phút vì interval là 30 giây. Ngoài ra có volume guard: chỉ xét khi request rate lớn hơn hoặc bằng baseline p50.

Kết quả: baseline FP giảm từ `297/720` ở MAD xuống `0`. Detector phát hiện sustained impact lúc `20:41`, với `impact_signal=True` và `supports_rca_chain=False`.

## Slide 10 - Sustained 5xx Impact

Chart này cho thấy detector 5xx mới hoạt động như thế nào. Vùng baseline 6 giờ nằm dưới threshold `3.00`, nên không tạo false positive. Sau restart/downstream symptoms, 5xx tăng rõ và duy trì trên threshold. Đường decision ở `20:41:30` là lúc rule đủ điều kiện `5/10`.

Ý nghĩa của slide này: 5xx sustained là bằng chứng tác động người dùng, không phải mốc bắt đầu nguyên nhân gốc. Nó xác nhận sự cố đã lan ra thành lỗi user-facing.

## Slide 11 - Log + Drain3 Evidence

Logs khá có cấu trúc, nhưng vẫn có tham số động như userId, status, duration, heap, pause. Drain3 được dùng để template hóa các tham số này và đếm pattern theo thời gian.

Các template quan trọng gồm ProductCatalogCache eviction failed, GC overhead limit warning, cart timeout, OOMKilled, và cart returned 5xx. Điểm mạnh của Drain3 ở đây là biến log raw thành evidence đếm được: mình thấy GC/cache template xuất hiện sớm hơn timeout/5xx downstream.

## Slide 12 - RCA Drill Down: Hypothesis

Hypothesis chính là cart heap/cache pressure xảy ra trước OOM và restart. Bằng chứng root cause gồm GC warning và cache eviction failure xuất hiện sớm, sau đó memory/GC/latency xấu đi, rồi OOMKilled.

Ở slide này, phần log root-cause evidence cho thấy OOMKilled là bằng chứng mạnh cho việc container bị kill vì memory limit, còn GC/cache warning là tín hiệu sớm hơn cho pressure bên trong cart-service.

## Slide 13 - RCA Drill Down: Impact Evidence

Slide này chuyển sang impact evidence. Sau khi cart-service unhealthy và restart, downstream bắt đầu thấy timeout và 5xx. Đây là phần giải thích vì sao order-service, payment-service và api-gateway có anomaly nhưng không phải origin chính.

Nói cách khác, downstream metrics/logs giúp chứng minh blast radius, không chứng minh root cause bắt đầu ở downstream.

## Slide 14 - RCA Drill Down: More Impact Evidence

Slide này tiếp tục phần impact evidence bằng log records sau giai đoạn cart-service đã suy giảm. Các dòng timeout/5xx xuất hiện sau OOM/restart nên phù hợp với mô hình lan truyền: cart bị restart hoặc không ổn định, caller gọi vào cart bắt đầu timeout hoặc nhận 5xx.

Đây là lý do timeline được đọc theo ordering, không đọc từng alert rời rạc.

## Slide 15 - RCA Drill Down: Exclusions

Slide này nói rõ những gì bị loại trừ. `06:08` 5xx MAD crossing bị loại vì baseline FP quá cao. EWMA early flags cũng bị loại khỏi RCA start vì EWMA chỉ dùng để xem trend.

Product-service cũng không phải RCA chính. Product-service có dao động latency/5xx và có log connection refused liên quan catalog, nhưng không tạo được chuỗi memory -> OOMKilled -> restart rõ như cart-service. Vì vậy product-service được xem là yếu tố phụ hoặc nhiễu, trừ khi có thêm telemetry chứng minh ngược lại.

## Slide 16 - Real World Data Pipeline

Slide này mô tả pipeline production tương ứng. Trong production, telemetry sẽ đi từ OpenTelemetry SDK/Collector vào Kafka, sau đó Flink xử lý window và chạy detector như MAD hoặc IF. Metrics có thể lưu ở VictoriaMetrics, logs ở Loki hoặc ClickHouse, object storage ở S3, và dashboard đọc từ RCA service.

Ý chính là repo hiện tại là offline simulation, còn production cần ingest liên tục, buffer/replay được, và detector chạy theo window.

## Slide 17 - Real World Data Pipeline: Flow

Flow production gồm 5 bước: Emit, Ingest, Buffer, Detect, RCA. Service emit metrics/logs/traces; Collector normalize; Kafka buffer để chống mất dữ liệu và replay; detector chạy theo window; cuối cùng RCA service ghép metric anomaly với log template evidence theo thứ tự thời gian.

Early alert target nên là composite signal: memory slope, GC pause, cache eviction template count, cart p99, và 5xx sustained. Không nên chỉ dựa vào một raw threshold crossing.

## Slide 18 - Closing

Kết luận cuối: metrics trả lời WHEN, log templates trả lời WHERE/HOW, còn evidence ordering giúp phân biệt root cause với symptom.

Với incident này, cart-service là origin candidate chính vì chuỗi GC/cache/memory/OOM/restart xuất hiện trước downstream timeout/5xx. MAD là detector chính cho RCA-supported anomalies; EWMA dùng để nhìn trend; IF dùng làm confirmation; và 5xx dùng sustained detector riêng để xác nhận impact người dùng.
