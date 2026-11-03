# Trading engine và giới hạn nghiệm thu

## Chỉ báo

Tính trên nến đã đóng: EMA 9/12/21/26/50, RSI Wilder 14, MACD 12/26/9,
ATR Wilder 14, Bollinger 20 với 2 độ lệch chuẩn tổng thể. Warmup 60 nến;
EMA khởi tạo bằng close đầu tiên, không đòi hỏi khớp tuyệt đối mọi nền tảng
chart khác có warmup/seed khác. Các phép sizing dùng Decimal, hiển thị và
mô phỏng PnL dùng float; không dùng float làm hệ thống kế toán tiền thật.

## Ba chiến lược version 1

| Chiến lược | LONG | SHORT | HOLD |
|---|---|---|---|
| ema_rsi | EMA9 vừa cắt lên EMA21 và 50 < RSI < 70 | EMA9 vừa cắt xuống EMA21 và 30 < RSI < 50 | Không có crossover hoặc RSI ngoài ngưỡng |
| macd_atr | MACD histogram vừa qua 0 lên, close > EMA50, RSI < 75 | Histogram vừa qua 0 xuống, close < EMA50, RSI > 25 | Không đủ cả trend/crossover |
| bollinger_volume | Close > BB upper, volume > 1.5× trung bình 20 nến trước, 0.1% < ATR/close < 5% | Close < BB lower và cùng điều kiện volume/volatility | Không có breakout được volume xác nhận |

Entry đề xuất là close nến phát tín hiệu; backtest vào open nến kế tiếp,
paper dùng giá quan sát lúc xử lý cộng slippage và từ chối khi lệch quá
0.2% so với tín hiệu. Stop cách entry đề xuất 2 ATR, target 4 ATR, R/R ban
đầu 2; Risk yêu cầu R/R sau round ít nhất 1.5. Thoát stop, target hoặc giữ
quá 24h. Không bật trailing stop ở ba chiến lược này.

Chế độ consensus chọn tín hiệu đầu tiên theo thứ tự bảng nếu các tín hiệu
cùng hướng, HOLD nếu xung đột hoặc không có tín hiệu. Không có LLM tự đổi
tham số. Khung hỗ trợ: 5m, 15m, 1h, 4h. Paper auto mặc định dùng 5m.

## Risk độc lập

Sizing không vượt 0.5% equity dựa trên stop distance cộng hai chiều phí,
slippage và dự phòng ba kỳ funding; thêm 2% khoảng đệm sizing rồi round
quantity xuống. Giới hạn: daily loss 2%, drawdown high-water 10%, 3 vị thế,
notional tổng 1× equity và leverage tối đa 2. Không mở thêm cùng symbol,
không martingale, không tự nâng risk. Thiếu filters hoặc dữ liệu fresh thì
reject. Mô hình sử dụng PRICE_FILTER, LOT_SIZE, MIN_NOTIONAL/NOTIONAL.

Risk chạy lại khi paper fill; không tin approval trong task, request hay
prose của mô hình. Paper kiểm tra giá fill/slippage không làm vượt budget.
Liquidation buffer dùng proxy bảo thủ `entry × (1/leverage − 0.05)` và stop
phải cách xa vùng đó. Đây **không** phải giá thanh lý thực của Binance.
Trước Testnet/live cần account reconciliation, maintenance brackets,
margin mode và liquidation price thực; bản web không cho phép gửi sàn.

## Backtest

Tối thiểu 120 nến, tối đa cửa sổ nến được giữ (cloud mẫu 500). Không tối ưu
tham số. Signal chỉ nhìn prefix trước nến entry. Cả stop và target xuất
hiện trong cùng nến thì stop thắng; gap qua stop được fill giá bất lợi hơn.
Không re-enter sau khi biết exit trong cùng nến. Có fee/slippage cả hai
chiều, funding giả định mỗi 8h, daily/drawdown gates và đóng cuối mẫu.

Từ 200 nến trở lên có split thời gian 70/30: test dùng 60 nến trước split
làm warmup, không dùng future bars cho signal và không tuning theo holdout.
Cache 500 nến không đủ chứng minh lợi thế bền vững, đặc biệt khung 5m.
Cần dữ liệu dài hơn và forward paper theo dõi trước mọi quyết định vốn.
Backtest không mô phỏng order queue, partial fills, liquidation, maintenance
brackets hay exchange lot filters: không tương đương execution thực tế.

Không gắn lợi nhuận vào Agent chỉ vì task Completed. Performance có trade
metrics theo strategy và task/error counts theo Agent, ghi rõ operational
metrics không phải attribution lợi nhuận nhân quả.

## Paper broker

Vốn mặc định 10.000 USDT **giả lập**, không cần nạp tiền. SQLite giữ account,
positions, intent IDs và ledger. Có entry fee, exit fee, realized PnL,
funding và unrealized PnL; intent key từ symbol/khung/nến/strategy/side
chống lặp sau restart. Kill Switch chặn mới, không tắt quản lý vị thế.

Mỗi 5s kiểm tra nến đóng mới và giá quan sát fresh, fill stop/target theo
mô hình bất lợi. Không có tick lịch sử trong thời gian server mất mạng;
không dùng cả nến entry vì không biết đường đi giá trước entry. Khi gap
vượt dữ liệu giữ, broker halt thay vì khẳng định đã tái dựng đúng vị thế.
Đây là mô phỏng cấp nến/giá lấy mẫu, không là simulator từng tick.

Phí mặc định 0.05%/chiều, slippage 0.02%/chiều, funding giả định +0.01%/8h
(long trả, short nhận). Thay theo biểu phí thực tài khoản khi cần; không
coi funding cố định là rate thực từ sàn. Giá trị được ghi vào kết quả.

Daily loss dùng Asia/Ho_Chi_Minh (UTC+7); drawdown dùng peak equity từ đầu
account. Khởi động lại buộc re-arm qua giao diện. Chưa có reset tài khoản
paper từ UI để tránh xóa lịch sử vô ý; muốn thử vốn khác dùng DB/volume mới.

## Futures Testnet — chưa chứng nhận execution

`app/execution/testnet.py` là thư viện/harness tách rời, không được web hoặc
LLM gọi. Host cố định `https://testnet.binancefuture.com`, nguồn là SDK
Binance chính thức tại commit `13fda514bb2a4358712d849aa3163a0505d96da0`.
Connector production order không được triển khai.

Có HMAC signing, timestamp sync, read position mode/positions/open orders,
submit regular/algo, query/reconcile, modify LIMIT, cancel; durable client
ID journal trước submit, timeout -> UNKNOWN + halt, tuyệt đối không tự POST
lại intent không rõ trạng thái. SL/TP dùng `/fapi/v1/algoOrder` và
closePosition, không trộn quantity/reduceOnly; One-way dùng BOTH, Hedge
LONG/SHORT. Đây là builder tham số, chưa bảo đảm Testnet chấp nhận mọi loại
lệnh hoặc lifecycle bracket an toàn khi partial fill.

Probe đọc cần `BINANCE_TESTNET_API_KEY` và `BINANCE_TESTNET_API_SECRET` trong
môi trường server, không nhập vào chat/frontend. Không có credentials trong
bản giao. Cần hostname Testnet được môi trường cho phép nếu chạy trong
sandbox có allowlist. Chưa yêu cầu thêm domain vì hiện không có key.

Chưa chạy đặt/hủy/sửa/SL/TP/partial-fill trên sàn. Thư viện không phải engine
autonomous Testnet đã được risk-certified: integration gate còn thiếu bằng
chứng thực tế, đối soát tài khoản, emergency close/recovery và bảo vệ bracket
khi có lỗi giữa các bước. Không bật Testnet mutations chỉ dựa vào mock tests.
Live trading chỉ có thể là đợt triển khai tiếp theo với xác nhận riêng của
chủ tài khoản sau nghiệm thu đầy đủ; bản này không có nút bật Live.
