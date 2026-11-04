# AI Trading Center — phối hợp Agent và PAPER tự động

## Bắt đầu trên Windows

1. Cập nhật mã nguồn, giữ `data`, `.env`, `.venv-windows` và chạy **MO_WEBSITE.cmd**.
2. Web tự bật theo dõi mỗi **15 giây** (nếu trước đó chưa chủ động tạm dừng).
   Xem **Trao đổi** để đọc công việc và các lần bàn giao bằng chứng.
3. Muốn giao mục tiêu: bấm **＋ Giao việc cho CEO**, chọn cặp/khung và gửi.
   Hỗ trợ phân tích giá/chỉ báo, backtest ba chiến lược, kiểm tra risk và báo cáo.
   Nội dung mục tiêu là ghi chú chỉ thị, không phải chương trình hoặc lệnh mua bán tùy ý.
4. Muốn giao dịch mô phỏng: bấm **Khởi động PAPER tự động**. Chỉ bật được khi dữ liệu
   Binance LIVE đủ mới và tài khoản chưa chạm giới hạn lỗ/drawdown. Lệnh đi qua risk
   Python, kiểm tra giá fill và chống lệnh trùng. Không có tín hiệu thì ghi lý do chờ.

**Dừng mở lệnh** hoặc Kill Switch chặn lệnh mới. Vị thế paper cũ vẫn được quản lý
SL/TP theo quy tắc. Dừng nghiên cứu cũng tắt PAPER tự động. Khởi động lại chương trình
sẽ khóa PAPER; bấm khởi động để bật lại. Tiền mô phỏng, không phải số dư Binance.
Không có đường gửi lệnh production và không cần API key để đọc dữ liệu công khai.

## Bật mô hình AI thật một lần

Phần công cụ Python hoạt động khi chưa có mô hình. Các vai trò AI dùng chung một
mô hình Ollama local, không phải 16 model độc lập. Sáu vai trò market, technical,
strategy, risk, report và CEO lần lượt viết nhận xét từ số liệu và nhận xét trước;
các vai trò còn lại thực hiện công cụ/kiểm tra. AI không được gửi lệnh, nới risk
hoặc sửa mã. Nhận xét mô hình vẫn có thể sai; không phải kết quả đã kiểm chứng.

1. Chạy **CAI_AI_WINDOWS.cmd**. Nếu chưa có Ollama, file mở trang tải chính thức.
2. Cài và mở Ollama trên Windows, chạy lại file để tải **qwen2.5:3b**.
   Cần vài GB ổ đĩa trống và đủ RAM; tốc độ tùy máy. Không tự thu phí API.
3. Trong web, bấm **Kết nối AI → Kiểm tra & bật AI** với tên `qwen2.5:3b`.
   Kết nối chỉ thành công khi server và model thực sự có sẵn. Có thể chọn model
   local khác đã cài. Lựa chọn được lưu SQLite, không sửa file `.env`.

Các nhận xét sinh thành công có nhãn **AI**, tên model và thời điểm. Khi model
không có/lỗi, công cụ vẫn theo dõi nhưng giao diện không giả rằng AI đang suy nghĩ.
Mỗi lúc chỉ có một lượt trao đổi AI nền, tối đa một lượt khởi tạo mỗi 30 giây.

## Các nhịp hoạt động

| Công việc | Nhịp / bằng chứng |
|---|---|
| Giá Binance | REST/WS realtime, giao diện đọc trạng thái khoảng 1,5 giây |
| Theo dõi các vai trò | Mỗi 15 giây, có `checked_at`, giá/chỉ báo/risk thực |
| Nghiên cứu chuyên sâu | Khi nến đóng đổi hoặc có nhiệm vụ mới; snapshot bất biến |
| Backtest | Cả ba chiến lược; dữ liệu không đổi dùng cache có ghi nhận |
| Bàn giao | Khi task ghi kết quả, gửi ID bằng chứng tới Agent phụ thuộc |
| Nhận đầu vào | Worker đọc kết quả phụ thuộc, ghi receipt và ID đầu vào |
| Báo cáo | Kết thúc chu kỳ và bản cập nhật theo dõi định kỳ |
| PAPER autopilot | Kiểm tra mỗi 5 giây khi đã bật; không ép có giao dịch |
| Nghiên cứu cải tiến | Lưu đánh giá sau Report Agent; mẫu yếu = cần kiểm chứng thêm |

**Đang theo dõi** là dịch vụ giám sát đang bật, không đồng nghĩa đang suy luận LLM.
**Đang làm** là công cụ đang chạy; **đang tổng hợp** có thể là một lượt mô hình thực.
Hiệu ứng bàn giao trong 3D dựa trên thông điệp có thật, không phát hội thoại ngẫu nhiên.
Tin RSS chưa có nguồn thì vẫn ghi rõ chờ; không tự bịa tin mới.

## Cải tiến có kiểm chứng

Mỗi báo cáo lưu so sánh ba chiến lược, số giao dịch, PnL, drawdown và holdout nếu có.
Bảng cải tiến giữ lịch sử đánh giá, phân biệt cần kiểm chứng và ứng viên nghiên cứu.
Điều kiện ứng viên tối thiểu vẫn gồm đủ nến, đủ giao dịch kiểm thử và không có task lỗi.
Không tự đổi chiến lược đang chạy, sửa code, cài phiên bản mới hoặc triển khai khi
chưa có quy trình kiểm chứng/phê duyệt. Bản này chưa phải hệ thống tự viết và tự
triển khai mã nguồn. Không chứng nhận chiến lược có lợi nhuận.

Hộp thư giữ khoảng 2.000 thông điệp gần nhất; đánh giá giữ 1.000 bản. Lịch sử task,
báo cáo và backtest tiếp tục nằm SQLite theo cơ chế lưu/retention hiện có.

## PnL, nguyên nhân chưa mở lệnh và Agent bổ sung

Mở tab **PnL & lệnh**:

- Equity, PnL đã ghi sổ ròng, PnL chưa chốt, tổng PnL ròng, phí và funding đều
  tính từ sổ/positions PAPER. Đây **không phải** số dư/PnL tài khoản Binance thật.
- Biểu đồ ghi một điểm khoảng mỗi 5 giây, giữ 24 giờ, tồn tại sau restart.
  Giao diện hiển thị tối đa khoảng 480 điểm đã lấy mẫu. Giá cũ/mất kết nối được
  đánh dấu; PnL chưa chốt là ước tính theo giá tham chiếu PAPER, không phải chứng
  nhận mark/PnL của một tài khoản trên sàn.
- Mục **Vì sao chưa mở lệnh?** đọc trạng thái từng chiến lược, số nến, bộ lọc sàn,
  độ lệch điểm vào, risk và kết quả thử gần nhất. Chưa khởi động, HOLD, dữ liệu cũ,
  thiếu metadata, lệch giá và giới hạn tài khoản có lý do riêng.
- **Tải chẩn đoán lệnh** xuất JSON từ phiên đang chạy, không có API key. Có thể
  gửi file/ảnh mục chẩn đoán để xác định lỗi trên máy bạn; môi trường phát triển
  không tự đọc được trạng thái tại `127.0.0.1` của máy Windows khác.

Bấm **＋ Agent** để thêm tối đa bốn Agent chuyên biệt: market, technical, risk hoặc
report. Các Agent này đọc quan sát có thật, có bàn trong 3D, được lưu qua restart
và tham gia nhận xét nếu mô hình kết nối. Đây là Agent cấu hình theo chuyên môn
có sẵn, không phải tạo công cụ/code tùy ý. Luồng task nghiên cứu lõi vẫn có 16 vai trò.
Tên/nhiệm vụ ghi chú không được thực thi như mã hoặc lệnh giao dịch.

Khả năng tự viết tính năng mới, kiểm thử rồi tự triển khai mã nguồn **chưa có**.
Bản hiện tại tự nghiên cứu/đánh giá chiến lược và cho phép mở rộng Agent chỉ đọc;
không nên coi các đánh giá đó là một hệ thống tự lập trình đã hoàn chỉnh.
