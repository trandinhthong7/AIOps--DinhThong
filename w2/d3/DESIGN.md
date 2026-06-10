# DESIGN.md

## Pipeline architecture

Endpoint `POST /incident` nhận batch alerts qua Pydantic model, nên thiếu field hoặc sai type trả `422` tự động trước khi vào pipeline. Sau validation, service gọi real `correlate()` từ `w2/d1/correlate.py` với `gap_sec=120` và `max_hop=2`. Mình chọn `gap_sec=120s` vì dataset thật có cascade payment -&gt; checkout -&gt; edge trong vài phút; gap ngắn như 49s dễ tách notification hoặc edge symptoms ra cluster riêng, còn 120s vẫn đủ nhỏ để không gom các incident cách xa nhau. Cluster lớn nhất được đưa vào `run_rca`, dùng graph `networkx.DiGraph`, temporal scoring, keyword retrieval trên `incidents_history.json`, rồi lấy class/actions từ incident gần nhất kiểu kNN.

## Latency budget

Target p99 là dưới 10s. Với `AIOPS_USE_LLM=false`, đo thực tế trên 20 alerts cho thấy endpoint dưới vài ms. Budget production của mình là validate &lt; 2ms, correlate &lt; 10ms cho batch nhỏ, RCA retrieval &lt; 30ms, serialize &lt; 5ms. Nếu bật LLM sau này, LLM sẽ là phần chiếm đa số budget nên service có kill switch `AIOPS_USE_LLM=false` và cache RCA `TTLCache`.

## Production concern

Concern chính là concurrency với shared state. Graph và history được load một lần ở module import và chỉ đọc, nên an toàn trong single worker. RCA cache là in-process TTL cache; với nhiều worker cache không share nhau, nhưng kết quả vẫn đúng vì cache chỉ tối ưu latency. Fault tolerance: nếu LLM provider down, readiness vẫn pass vì graph+retrieval là fallback chính cho assignment này.

## Framework trade-off

Mình chọn FastAPI thay vì Flask vì FastAPI có Pydantic validation, OpenAPI, middleware rõ ràng và trả `422` tự động cho invalid input. So với BentoML, pipeline này chưa phải model-serving thuần; phần quan trọng là glue API + correlation + graph RCA, nên FastAPI nhẹ và dễ vận hành hơn.