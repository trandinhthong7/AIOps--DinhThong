# Hướng Dẫn Chạy Bài Lab

## 1. Cài thư viện cần thiết

Generator cần thư viện `requests`, nên chạy lệnh:

```bash
python3 -m pip install -r requirements.txt
```

Nếu dùng `uv`:

```bash
uv pip install -r requirements.txt
```

## 2. Chạy pipeline

Mở terminal tại thư mục bài:

```bash
cd /Users/trandinhthong/Downloads/AIOps/W1/student
```

Chạy HTTP server:

```bash
python3 pipeline.py --port 8000
```

Nếu chạy thành công sẽ thấy pipeline lắng nghe ở endpoint:

```text
http://localhost:8000/ingest
```

## 3. Chạy generator

Mở terminal thứ hai, vẫn ở thư mục bài:

```bash
cd /Users/trandinhthong/Downloads/AIOps/W1/student
```

Chạy generator với ngày sinh của mình:

```bash
python3 stream_generator.py --birthday YYYY-MM-DD --target http://localhost:8000/ingest
```

Ví dụ:

```bash
python3 stream_generator.py --birthday 2000-03-15 --target http://localhost:8000/ingest
```

## 4. Xem alert

Khi pipeline phát hiện anomaly, file `alerts.jsonl` sẽ được tạo hoặc cập nhật.

Xem nội dung alert:

```bash
cat alerts.jsonl
```

Mỗi dòng alert có dạng JSON:

```json
{"timestamp":"...","type":"memory_leak","severity":"warning","message":"..."}
```

## 5. Nếu gặp lỗi port 8000 đang được dùng

Lỗi thường gặp:

```text
OSError: [Errno 48] Address already in use
```

Nghĩa là đã có chương trình khác đang dùng port `8000`.

Kiểm tra process đang dùng port:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Nếu thấy process cũ của Python, có thể tắt bằng PID:

```bash
kill PID
```

Ví dụ:

```bash
kill 3943
```

Hoặc chạy pipeline bằng port khác:

```bash
python3 pipeline.py --port 8001
```

Khi đó generator cũng phải đổi target:

```bash
python3 stream_generator.py --birthday YYYY-MM-DD --target http://localhost:8001/ingest
```

## 6. Kiểm tra pipeline còn sống không

Chạy:

```bash
curl http://localhost:8000/health
```

Nếu trả về như sau là pipeline đang chạy:

```json
{"status":"ok"}
```

## 