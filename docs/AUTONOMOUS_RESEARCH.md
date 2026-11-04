# CEO tự phân công — không phải chạy từng backtest

## Cách sử dụng

Trang chính là [văn phòng quan sát 3D](OBSERVER_MODE.md), tự bật nghiên cứu
khi nâng cấp lần đầu. Mở web rồi quan sát; không cần thao tác backtest.
Bảng điều khiển cũ chuyển tới `/operator`, dành cho dùng nâng cao.

CEO theo dõi các cặp trong cấu hình (mặc định BTCUSDT, ETHUSDT). Khi dữ liệu
LIVE và có đủ 120 nến đóng, CEO giao công việc cho các vai trò:

| Agent | Việc tự thực hiện |
|---|---|
| Market Analyst | Kiểm tra nguồn giá và độ mới |
| Technical Analyst | Tính RSI, MACD, EMA, ATR và Bollinger |
| Data Analyst | Kiểm tra nến thiếu và chất lượng dữ liệu |
| Backtest Agent | Chạy cả 3 chiến lược và chronological holdout nếu đủ nến |
| Strategy / Signal | Tổng hợp điều kiện, đưa LONG/SHORT/HOLD theo quy tắc |
| Risk Manager | Kiểm tra điều kiện hiện tại và Kill Switch bằng Python |
| Execution Agent | Ghi nhận chu kỳ chỉ phân tích; không gọi broker mở vị thế |
| Portfolio / Accounting / Performance | Đọc và tổng hợp tài khoản mô phỏng hiện có |
| Report Agent | Tạo bảng so sánh, cảnh báo và kết luận tiếng Việt từ evidence |
| CEO Agent | Đọc báo cáo, tổng kết trạng thái và bằng chứng các task |

News Agent dùng RSS nếu đã cấu hình; chưa có nguồn thì ghi Waiting. Monitor,
Security và các vai trò khác vẫn có tasks/logs như trước. Tin tức, prose hay
LLM không cấp được quyền giao dịch hoặc thay Risk Manager.

## Bạn nhìn thấy gì?

- Trạng thái CEO đang theo dõi/chờ nến/chờ LIVE/xử lý nhiệm vụ.
- Báo cáo riêng từng cặp và khung, có thời điểm và cửa sổ nến sử dụng.
- Ba chiến lược cùng một snapshot dữ liệu: số lệnh, PnL mô phỏng, drawdown,
  kết quả phần kiểm thử tách riêng.
- Cảnh báo mẫu ngắn, ít giao dịch, thiếu tin tức hoặc tool lỗi.
- Kết luận “chưa đủ bằng chứng” khi dữ liệu yếu; không chọn chiến lược chỉ
  vì nó có lãi trên vài lệnh. Ứng viên nghiên cứu (nếu có) không là phê duyệt
  thực thi hoặc cam kết lợi nhuận.

Kill Switch có thể giữ bật suốt quá trình nghiên cứu. Chu kỳ analysis-only
không mở cả lệnh paper, ngay cả khi chủ tài khoản đã arm PAPER. Chế độ quan sát mặc định chặn mở vị thế ở cả API/tool/broker; các điều khiển
paper chỉ dùng được khi chuyển sang profile operator một cách chủ động.

## Tự động nhưng có giới hạn rõ ràng

- Bộ điều phối kiểm tra tối thiểu mỗi 5s (hoặc chu kỳ env lớn hơn). Giá
  thay đổi từng tick không làm backtest chạy lại. Snapshot nến đóng hoặc
  giả định chi phí thay đổi mới tạo dữ liệu nghiên cứu mới.
- Một dataset được giữ bất biến cho mỗi chu kỳ; cả ba chiến lược dùng đúng
  cùng dữ liệu. Backtest chạy ở background thread để nhường event loop cho
  market data. Kết quả cache theo dữ liệu/strategy/phiên bản engine/chi phí.
- Không chạy chồng cùng cặp/khung khi chu kỳ trước chưa xong. Queue vẫn có
  giới hạn 4 chu kỳ; các lượt sau tự thử lại khi đầy.
- Bấm **Dừng tự phân tích** sẽ dừng giao việc mới; chu kỳ đang xử lý có thể
  hoàn tất và được ghi báo cáo. Không hủy bừa dữ liệu hoặc các process khác.
- Lựa chọn bật/tắt được lưu SQLite. Mở lại website sẽ tiếp tục phân tích
  nếu trước đó đã bật; khi chưa có LIVE sẽ chờ. Máy tắt/sleep thì không có
  hoạt động; không có máy chủ cloud đang âm thầm chạy thay.
- Dữ liệu 200 nến vẫn chỉ là mẫu ngắn. Agent tự thực hiện các kiểm tra này,
  nhưng không biến mẫu yếu thành một chứng nhận có lợi nhuận.

Đây là các vai trò phần mềm có công cụ và nhiệm vụ xác định, không phải
16 mô hình LLM đang suy nghĩ độc lập. Backtest và risk dùng phép tính Python
để có thể kiểm tra lại. Ollama tùy chọn chỉ viết thêm prose cho CEO; bản
hiện tại chưa có conversational agent tự sinh và thử code chiến lược mới.

## Cập nhật bản đang chạy trên Windows, giữ dữ liệu

1. Ở cửa sổ chương trình đang chạy, bấm **Ctrl+C** để dừng.
2. Tải ZIP mới từ https://github.com/ducanh261002/AI-Trading/archive/refs/heads/main.zip .
3. Giải nén ZIP vào một thư mục tạm. Mở **bên trong** thư mục `AI-Trading-main`
   mới để thấy các file `MO_WEBSITE.cmd`, `app`, `scripts`, `docs`.
4. Chọn các file/thư mục bên trong đó, copy vào thư mục dự án cũ bạn đang
   dùng và chọn thay thế các file trùng tên. **Không xóa thư mục dự án cũ.**
   GitHub ZIP không chứa `.env`, `data` hoặc `.venv-windows`, nên thao tác
   copy source này không thay mật khẩu/cấu hình/lịch sử đã có.
5. Mở `MO_WEBSITE.cmd`, refresh trình duyệt. Nếu launcher báo lockfile thay
   đổi thì chạy `CAI_DAT_WINDOWS.cmd` trước; bản thay đổi này không thêm
   dependency và giữ nguyên lockfile.
6. Mở trang chính để quan sát 3D; nghiên cứu tự khởi động.

Migration SQLite bổ sung bảng/cột, không xóa backtest và paper ledger cũ.
Nên copy thư mục `data` sang chỗ riêng làm backup khi server đã dừng trước
khi cập nhật. Không gửi DB hoặc file `.env` lên chat/GitHub.

## API cho kiểm thử/tích hợp

GET `/api/research` trả trạng thái và báo cáo đã hoàn tất.

POST `/api/research` với body:

```json
{"enabled": true, "interval": "5m"}
```

Hosted mode vẫn cần session/Origin/CSRF. Schema không cho thêm tool, prompt
hoặc quyền execution. POST `/api/agent-cycles` mặc định `analysis_only=true`;
job legacy đã lưu trước migration được giữ để không phá lịch sử. Không có
API nào trong tính năng này gửi production orders.

## Bằng chứng và giới hạn

Kiểm thử bao gồm: tự tạo nhiệm vụ, 3 backtest trên snapshot chung, cache,
không duplicate khi chưa có nến mới, không mở paper kể cả đã arm, chờ stale,
lưu lựa chọn qua restart và migration schema cũ. Chromium fixture kiểm tra
nút bật/dừng, bảng báo cáo desktop/mobile và kích hoạt khi thêm nến mới.
Fixture là DB tạm riêng, không đưa dữ liệu giả vào market thật của bạn.

Windows có market LIVE theo ảnh chủ máy đã cung cấp; bản cập nhật chế độ
mới vẫn cần được chạy trên chính máy đó để xác nhận môi trường thực tế.
