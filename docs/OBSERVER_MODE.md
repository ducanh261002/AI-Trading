# Văn phòng 3D — bạn chỉ quan sát

Chạy `MO_WEBSITE.cmd`, mở `http://127.0.0.1:8000`. Trang chính tự vào 3D
và tự bật nghiên cứu ở lần nâng cấp đầu tiên. Không cần bật PAPER hoặc bấm backtest.

- Kéo để xoay, cuộn để phóng to; bấm bàn Agent để xem nhiệm vụ và lịch sử.
- CEO tự giao việc khi có dữ liệu LIVE và ít nhất 120 nến đã đóng. Backtest Agent
  kiểm thử cả ba chiến lược; Report Agent tạo báo cáo tiếng Việt dưới văn phòng.
- Đang làm là nhiệm vụ thật. Xử lý xong thì chờ nến đóng mới; không làm giả
  trạng thái bận hoặc báo cáo lặp mỗi giây. Khung mặc định 5 phút.
- Thiếu nguồn tin, chưa đủ nến hoặc mất kết nối thì hiển thị trạng thái chờ.
- Máy không hỗ trợ WebGL vẫn có 16 thẻ 2D và báo cáo tự cập nhật.
- Máy phải bật, có Internet và không sleep. Không cần mua VPS, tên miền hoặc API key Binance.

Các Agent là 16 vai trò phần mềm với công cụ Python và hàng đợi nhiệm vụ,
không phải 16 mô hình LLM độc lập. Ollama tùy chọn; giao diện ghi rõ trạng thái.

## Cập nhật Windows

1. Dừng web đang chạy bằng **Ctrl+C**, sao lưu thư mục `data`.
2. Tải ZIP mới trên GitHub, giải nén và chép mã nguồn mới vào thư mục dự án cũ.
   Giữ nguyên **`data`, `.env`, `.venv-windows`**; không xóa dữ liệu cũ.
3. Chạy **MO_WEBSITE.cmd**, vào trình duyệt nhấn **Ctrl+F5**.

Không thay đổi thư viện nên không cần cài lại Python/dependencies.
Migration giữ lịch sử. Sau khi chủ động tạm dừng trong **Điều khiển quan sát**,
lựa chọn đó được giữ khi khởi động lại.

## Chế độ mặc định

`ATC_OBSERVER_MODE=true`, kể cả khi `.env` cũ chưa có dòng này. Chặn mở vị thế
paper ở API, Agent tool và broker. `paper_auto` không được mở lệnh mới.
Vị thế paper cũ vẫn được cập nhật/đóng theo quy tắc hiện có. Không gửi lệnh production.

Bảng công cụ cũ ở `/operator`. Người dùng nâng cao có thể đặt
`ATC_OBSERVER_MODE=false` rồi khởi động lại để quay về điều khiển thủ công;
không cần làm điều này để quan sát.

## Bố cục văn phòng và theo dõi công việc

- **Đội ngũ bên trái:** tìm theo tên, nhiệm vụ hoặc chỉ báo; lọc Agent đang làm.
  Trạng thái chờ nến không có nghĩa là chương trình bị lỗi.
- **Văn phòng 3D ở giữa:** nhân vật, bàn và khu làm việc của 16 Agent.
  Nhãn công việc ưu tiên Agent đang xử lý và Agent đang chọn; **Nhãn: tất cả**
  hiển thị toàn bộ. Có xoay, zoom, thu gọn đội ngũ và toàn màn hình.
- **Bàn làm việc bên phải:** chọn Agent để xem công việc, các bước thực thi,
  kết quả công cụ và lịch sử. Chỉ báo/backtest là giá trị nhiệm vụ đã ghi nhận,
  có thời điểm cụ thể; không phải số liệu trực tiếp hiện tại.
- **Luồng giao việc:** 16 nút nối theo dependency thật, không phải sơ đồ tự do.
  Bấm nút để xem bằng chứng. Thanh tiến độ đếm nhiệm vụ đã xử lý; số hoàn tất,
  chờ nguồn và lỗi được tách rõ, không coi 100% xử lý là tất cả đều thành công.
- **Kết quả:** báo cáo tổng hợp, cảnh báo, so sánh và nhật ký. Có thể chọn chu kỳ
  cũ; **Theo dõi mới nhất** quay lại chu kỳ tự động đang quan sát.

Phong cách giao diện lấy cảm hứng từ video tham khảo, giữ nội dung AI Trading.
Đây là workflow Python tự động với Ollama tùy chọn, không phải các mô hình
độc lập có khả năng điều khiển trình duyệt/máy tính như mọi tác vụ trong video.
Không tự sinh dữ liệu hoặc giả trạng thái bận để làm văn phòng trông sống động.
