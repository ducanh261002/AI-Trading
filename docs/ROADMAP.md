# Lộ trình nghiệm thu

## Giai đoạn 1 — Foundation

Kiến trúc: FastAPI một tiến trình, SQLite, dashboard 2D và registry Agent.
Đầu ra đã triển khai tại README và mã nguồn. Nghiệm thu: health, 16 vai trò,
nhiệm vụ chẩn đoán có log/kết quả lưu sau restart, Kill Switch, chặn orders,
chặn cấu hình live/risk vượt trần. LLM/market không phải điều kiện phase 1.

## Giai đoạn 2 — Binance realtime

Thêm Market Data Engine async, adapter REST/WS chính thức. Trước khi viết
endpoint phải đối chiếu tài liệu Binance USDⓈ-M hiện hành tại
https://developers.binance.com/docs/derivatives/usds-margined-futures/ và
ghi ngày kiểm tra, endpoint, hỗ trợ Testnet và contract test. Foundation
chưa xác minh endpoint và không tự giả định tính năng Testnet.

Nghiệm thu: giá, nến 5m/15m/1h/4h, volume, trades và depth có timestamps;
bootstrap nến và order book đúng snapshot/update ID; phát hiện gap/stale;
reconnect với exponential backoff/jitter, resubscribe và resync; xử lý
rate-limit/429 theo tài liệu; dữ liệu live hiển thị đúng nguồn, không seed giả.
Mất mạng phải hiện disconnected và chặn quyết định mới.

## Giai đoạn 3 — Agent orchestration

Scheduler và task state machine lưu SQLite; CEO điều phối Python, một hàng
đợi Ollama optional. Tools có allowlist riêng, prompt không chứa credentials.
Nghiệm thu 16 vai trò có nhiệm vụ thật, ID duy nhất, trạng thái/thời gian/
kết quả/log; timeout và retry hữu hạn, phục hồi task sau restart; prompt
injection từ news không cấp quyền tool và LLM không đổi risk.

## Giai đoạn 4 — Trading engine

Tính RSI, MACD, EMA, Bollinger, ATR bằng Python/pandas và kiểm tra fixtures.
Định nghĩa chiến lược versioned: EMA crossover + RSI; MACD + EMA + ATR;
Bollinger + volume + volatility. Mỗi chiến lược ghi rõ LONG/SHORT/HOLD,
entry, exit, stop, take profit, trailing khi dùng và R/R.

Sizing khởi đầu: risk budget = equity × 0.005; quantity bị giới hạn bởi
khoảng stop cộng dự phòng phí/slippage, exposure, margin và bộ lọc sàn.
Làm tròn quantity xuống theo step; sau làm tròn tính lại risk. Không tăng
khối lượng theo thua lỗ hoặc bình quân giá xuống. Liquidation buffer phải
dựa trên margin mode/maintenance brackets và dữ liệu sàn, không dùng công
thức leverage đơn giản thay cho kiểm tra thanh lý.

Nghiệm thu: backtest không look-ahead, warmup, train/test tách thời gian,
commission hai chiều, funding theo thời điểm và slippage; paper trading
không gửi sàn; giới hạn daily loss theo Asia/Ho_Chi_Minh, drawdown theo
high-water equity, vị thế, notional, leverage và liquidation buffer đều có
negative tests. Báo cáo số lệnh, return, drawdown, expectancy và giả định;
không đặt ngưỡng lợi nhuận giả hoặc kết luận hiệu quả trước kết quả thực tế.

## Giai đoạn 5 — Futures Testnet execution

Chỉ triển khai sau xác minh tài liệu chính thức hiện hành. Adapter tách
paper/testnet/live và cấu hình đích không do LLM cung cấp. Nghiệm thu đặt,
hủy, sửa theo đúng loại lệnh được hỗ trợ; SL/TP, One-way/Hedge, margin và
leverage; tick/step/min-notional; client order ID bền vững và đối soát khi
timeout trước retry, không mặc định timeout là sàn chưa nhận lệnh.

Test lỗi mất mạng lúc submit, partial fill, restart, lệch vị thế, API limit,
funding/phí và Kill Switch. Phải lưu bằng chứng test thực sự trên Testnet;
mock không thay bằng chứng sàn. Stop bảo vệ phía sàn và phục hồi trạng thái
phải được kiểm chứng trước khi xem xét live.

Chuyển live cần xác nhận rõ của chủ tài khoản ở bước riêng sau khi có kết
quả backtest/paper/Testnet; không tự chuyển sau khi test pass. Key không
quyền rút, cân nhắc IP allowlist nếu điều kiện kết nối hỗ trợ. Máy sleep,
tắt hoặc mất Internet sẽ ngừng điều phối: cần cấu hình Windows power và
kiểm thử tình huống này, không hứa vận hành khi máy đã tắt.

## Giai đoạn 6 — Three.js command center

7 phòng: CEO, Research, Strategy, Risk, Execution, Portfolio, Technology.
16 avatar đơn giản, trạng thái và animation theo event thật. Dashboard nến,
chỉ báo, vị thế, balance/equity/PnL/drawdown và nhật ký dùng cùng backend.
Nghiệm thu fallback 2D khi WebGL lỗi, chọn reduced motion, giới hạn FPS và
đo RAM/frame time trên iGPU Windows; không che dữ liệu rủi ro bằng 3D.

## Giai đoạn 7 — Vận hành

Báo cáo giờ/ngày/tuần với timezone rõ ràng; backup SQLite bằng API backup,
retention và diễn tập restore; log rotation, kiểm tra đĩa, clock drift,
dependency audit và secret redaction. Nghiệm thu chạy liên tục có đo tài
nguyên, phục hồi mạng/restart không trùng lệnh, đối chiếu ledger với sàn,
báo cáo phân biệt dữ liệu thiếu và PnL đã xác nhận.

Mỗi giai đoạn tiếp theo phải kèm code, dependencies, cấu hình, lệnh Windows,
kiểm thử và xử lý lỗi cập nhật đồng bộ trong cấu trúc đã chọn. Tài liệu lộ
trình không được hiểu là các module tương lai đã được triển khai.
