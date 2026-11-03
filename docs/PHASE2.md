# Giai đoạn 2 — Market Data Engine

Cập nhật sau publication 03/11/2026: allowlist Binance đã enforced; probe
trong môi trường mới nhận HTTP 451 từ API. Chưa xác minh live market; đây
là access denial thay cho lỗi proxy CONNECT cũ mô tả bên dưới. Backend
hiện ở phase 3; endpoint health trả phase 3. Xem PHASE3.md.

## Phạm vi và trạng thái xác minh

Đã viết adapter REST/WS chỉ đọc cho Binance USDⓈ-M production public market
data. Dùng dữ liệu production không có nghĩa là bật live trading. Không cần
API key, không có endpoint tài khoản hoặc đặt lệnh trong adapter này.

Đã kiểm thử offline: bootstrap metadata/nến đóng, loại nến đang mở, parser,
dedup trades, retention, gap, timestamp stale, rate-limit và reconnect mô
phỏng/cancellation. Smoke test thật trong cloud chưa đạt: proxy từ chối
CONNECT tới Binance (403); không có bằng chứng nhận dữ liệu thật. Không coi
fixture là dữ liệu sàn. Chưa kiểm thử trình duyệt trên Windows hoặc chạy
liên tục 24h. Phải chạy live probe sau khi quyền mạng được áp dụng.

## Nguồn API đối chiếu ngày 03/11/2026

Tài liệu website Binance trực tiếp bị proxy chặn. Đã đối chiếu mã/tài liệu
SDK **hiện hành do Binance phát hành** tại commit
`13fda514bb2a4358712d849aa3163a0505d96da0` của
https://github.com/binance/binance-connector-python . Không dùng connector
`binance-futures-connector-python` cũ đã deprecated làm nguồn cuối cùng.

Các đường dẫn nguồn trong commit trên:

- `common/src/binance_common/constants.py`: REST `https://fapi.binance.com`,
  WS `wss://fstream.binance.com`.
- `clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py`:
  GET `/fapi/v1/exchangeInfo`, `/fapi/v1/time`, `/fapi/v1/klines`.
- `websocket_streams/streams/market_api.py` dưới cùng SDK: `symbol@aggTrade`
  và `symbol@kline_interval`, route `market`.
- `websocket_streams/streams/public_api.py`: `symbol@depth20@500ms`, route
  `public`; `common/src/binance_common/websocket.py` ghép `/{route}/stream`.

Tài liệu chính thức được SDK dẫn tới:

- https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market#aggregate-trade-streams
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public#partial-book-depth-streams

Không giả định Testnet hỗ trợ các tính năng này; Testnet là giai đoạn 5.

## Kiến trúc và dữ liệu

Backend lifespan khởi động một supervisor và hai kết nối WS: market cho
trade/nến, public cho partial book. Bootstrap REST tuần tự lấy exchangeInfo,
server time và tối đa 200 nến mỗi khung/cặp. Chỉ chấp nhận USDT perpetual
TRADING. Lưu các exchange filters nguyên bản để giai đoạn execution sử dụng.

Giá và quantity lưu chuỗi Decimal, không làm tròn theo float trong dữ liệu
gốc. Chart chỉ chuyển float để vẽ. Nến đóng lưu SQLite với khóa
`(symbol, interval, open_time)` và retention cấu hình; nến đang mở chỉ giữ
RAM. Giao dịch tổng hợp giữ tối đa 50/cặp, dedup theo aggregate trade ID.

Order book là **partial top-20 snapshot** thay thế toàn bộ view sau mỗi
event, không phải local full-depth book ghép từ diff. Không dùng REST depth
snapshot rồi áp quy tắc diff vào partial stream. Đây là giới hạn có chủ ý
của phase 2 để nhẹ tài nguyên; full depth snapshot + buffered diff + `pu`
resync sẽ cần module và test riêng nếu chiến lược sau này sử dụng full depth.

Supervisor reconnect exponential backoff 2–60s + jitter, hủy cả nhóm khi
một kết nối hỏng và bootstrap lại cửa sổ nến trước resubscribe. Định kỳ đổi
kết nối sau 23h. Watchdog kiểm tra đủ mọi nguồn sau grace 45s; mất nguồn sẽ
reconnect. Nến đóng bị gap cũng buộc backfill. Chỉ giữ cửa sổ gần nhất,
không cam kết khôi phục toàn bộ lịch sử ngoài retention sau nhiều ngày tắt.

`connected=true` chỉ khi cả hai channel đang mở và trade/book/4 khung nến
của mọi cặp có receive age và exchange event age dưới ngưỡng. Hệ thống có
thể bảo thủ đánh stale ở cặp kém thanh khoản; không tự bịa giá hoặc bỏ kiểm
tra chỉ để hiển thị LIVE. Clock offset được lấy từ server time khi bootstrap.
Chưa có đồng bộ NTP hoặc đo drift dài hạn (phase 7).

REST tôn trọng Retry-After với 418/429, lưu cooldown qua các lần supervisor
retry, tối đa 4 lần gọi trong một request; access 403/451 dừng ở blocked,
không đổi miền để né hạn chế. Header used-weight được trả về status. Bootstrap
tuần tự có delay và tối đa 5 cặp để tránh burst. Chưa phải bộ điều phối quota
cho giao dịch/tài khoản; cần bổ sung trước phase 5.

Kill Switch vẫn luôn bật; dữ liệu mới không mở quyền tạo lệnh. PnL, vị thế,
chỉ báo và worker Agent chưa có trong phase này.

## Cài đặt và vận hành Windows PowerShell

Tại gốc dự án, giữ nguyên `.env` sẵn có:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m app.market.probe --timeout 90
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Nếu chưa có `.venv`, làm bước cài Python/venv ở README trước.
Probe dùng SQLite tạm riêng, chỉ đọc dữ liệu sàn, xóa DB khi kết thúc và
trả exit code 0 **chỉ khi** đủ hai WS, mọi nguồn fresh và đã bootstrap nến.
Exit code 1 nghĩa là chưa xác minh realtime; không bỏ qua khi nghiệm thu.

Cấu hình `.env` bổ sung (hoặc dùng các mặc định tương đương):

```dotenv
ATC_MARKET_ENABLED=true
ATC_MARKET_SYMBOLS=BTCUSDT,ETHUSDT
ATC_MARKET_STALE_SECONDS=15
ATC_CANDLE_LIMIT=200
```

Chỉ 1–5 symbols khác nhau; nhập không có khoảng trắng. Hỗ trợ đổi khung
5m/15m/1h/4h bằng dashboard. Đổi symbols/config thì khởi động lại backend.
Không cần cài Ollama hay cung cấp key để chạy phase này.

API kiểm tra trong PowerShell thứ hai:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/market
Invoke-RestMethod 'http://127.0.0.1:8000/api/candles/BTCUSDT?interval=15m'
```

Dashboard lấy snapshot backend mỗi 2s; dữ liệu sàn vào backend qua WS.
Đây không phải giao diện đẩy mỗi tick tới trình duyệt. Khi mất backend,
dashboard có timeout và gỡ nhãn LIVE; chart còn dữ liệu cũ được ghi rõ.

## Nghiệm thu và lỗi thường gặp

1. Offline tests pass và probe thật exit 0; giá từ sàn, nến có thời gian,
   book có bids/asks, trades có ID; `/api/status` execution luôn false.
2. Ngắt mạng trong khi chạy: connected false, hiển thị stale/offline.
   Kết nối lại: backoff/resubscribe và dữ liệu trở lại; kiểm tra không có
   nến đóng trùng. Kiểm thử reconnect với sàn thực còn cần thực hiện.
3. Restart backend: nến còn SQLite; không gắn LIVE cho cache cho tới khi
   nhận đủ dữ liệu mới. Chọn khung/cặp khác vẫn đúng.

Cloud hiện cần cho phép `developers.binance.com`, `fapi.binance.com`,
`fstream.binance.com`. Đã thêm các miền này vào bản nháp, nhưng lưu nháp
không áp dụng quyền runtime. Xem và lưu cấu hình mạng trong Environment
Settings rồi chạy probe lại; publish là bước riêng.

Nếu 451/403 từ sàn, kiểm tra khu vực và quyền truy cập theo chính sách
Binance; không đổi miền hoặc proxy để né hạn chế. Nếu proxy CONNECT 403,
kiểm tra allowlist của môi trường. Nếu TLS lỗi, kiểm tra CA/proxy hợp lệ,
không tắt TLS. Nếu chỉ chậm/stale, kiểm tra mạng, giờ máy và chọn cặp thanh
khoản cao. Nếu cần chạy offline, đặt `ATC_MARKET_ENABLED=false` và restart.

## File mới và dependencies

`app/market/{__init__,models,rest,store,engine,probe}.py`, `tests/test_market.py`
và tài liệu này. Cập nhật config/main/dashboard/.env.example, giữ tên module
Foundation. Thêm `websockets==15.0.1` cho kết nối async có HTTP proxy/TLS;
HTTPX đã có. Dependencies và toàn bộ phiên bản ở requirements tương ứng.
