# Chạy miễn phí trên máy Windows đang có

Không mua VPS hoặc tên miền. Windows chạy backend, còn bạn dùng Chrome/Edge
để mở giao diện website. Không cần Docker hoặc tài khoản DigitalOcean.
Tailscale đã cài có thể để nguyên, nhưng không cần dùng khi mở trên chính PC.

## 1. Cài Python một lần

Nếu chưa cài Python, mở **Windows PowerShell** (tìm từ menu Start), dán lệnh:

```powershell
winget install --exact --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
```

Lệnh dùng Windows Package Manager để cài Python chính thức. Nếu không có
winget hoặc báo lỗi, dừng và gửi thông báo lỗi để được hướng dẫn; không
tải installer từ các trang lạ. Có thể dùng Python 3.12 đã cài sẵn. Sau khi
cài xong, đóng cửa sổ terminal cũ; launcher tìm Python mới trong lần chạy sau.
Gói dependencies đã kiểm thử trên Linux/Python 3.12; Python/Windows thực
tế trên PC của bạn vẫn cần xác minh ở bước cài và khởi động bên dưới.

## 2. Tải code, giải nén

Mở https://github.com/ducanh261002/AI-Trading . Bấm **Code → Download ZIP**.
Nếu 404, đăng nhập GitHub bằng tài khoản có quyền đọc repository.

Trong Downloads, nhấp phải file ZIP → **Extract All / Giải nén tất cả**.
Đặt thư mục ở nơi bạn có quyền ghi, ví dụ Documents. Không chạy trực tiếp
trong cửa sổ đang xem ZIP, không đặt ở Program Files hoặc thư mục hệ thống.

Mở thư mục đã giải nén cho tới khi thấy hai file:

- `CAI_DAT_WINDOWS.cmd`
- `MO_WEBSITE.cmd`

## 3. Cài thư viện

Nhấp đúp **CAI_DAT_WINDOWS.cmd**. Đợi có dòng `Cai dat xong` rồi bấm một
phím để đóng cửa sổ. Lần đầu cần Internet. Script dùng môi trường riêng
`.venv-windows`, không thay Python toàn máy, không tắt TLS, không thay
ExecutionPolicy và không đòi mật khẩu/API Key.

Nếu có lỗi, giữ nguyên cửa sổ để đọc/chụp lỗi. Không tiếp tục coi là đã cài
thành công. Cửa sổ bị Windows chặn thì kiểm tra nguồn file đúng repository
của bạn; không tắt Windows Defender hoặc bảo vệ toàn hệ thống.

## 4. Mở website

Nhấp đúp **MO_WEBSITE.cmd**. Đợi backend sẵn sàng; trình duyệt sẽ mở
`http://127.0.0.1:8000`. Đây là website trên PC của bạn, không phải website
công khai. Giao diện có dark theme, Agent, chart và nút 3D/2D.

Giữ cửa sổ dòng lệnh đang chạy. Muốn dừng, chọn cửa sổ đó và bấm **Ctrl+C**.
Không cần bấm file cài đặt mỗi ngày, chỉ chạy `MO_WEBSITE.cmd`.

Nếu trình duyệt không tự mở, nhập địa chỉ loopback ở trên vào thanh địa chỉ.
Nếu port 8000 đang bận, đóng phiên website cũ. Script không tự kill ứng dụng
khác để chiếm port. Không mở hai backend dùng chung DB.

## Những điều cần biết

- Máy phải bật, có Internet, không sleep thì hệ thống mới chạy. Tắt máy
  hoặc sleep sẽ dừng xử lý; không hứa chạy 24/7 khi máy đã tắt.
- Chưa cần API Key Binance, không nạp tiền. Market công khai không dùng key.
  Tài khoản 10.000 USDT trên giao diện là **tiền mô phỏng**.
- Script ép PAPER/local-only và tắt tự động mở paper entries/lịch Agent ở
  mỗi lần chạy. Nó không sửa `.env`; lịch sử ở `data/` vẫn được giữ.
- Chạy CEO/backtest thủ công trên UI. Kill Switch bật sau restart; chưa có
  điều kiện market fresh thì không bật paper hoặc gửi lệnh mới được.
- Binance lỗi 451/blocked là chưa có dữ liệu thật; không dùng dữ liệu giả
  hoặc đổi proxy để bỏ qua. Gửi dòng lỗi để chẩn đoán kết nối hợp lệ.
- Nếu iGPU chậm, dùng 2D. Ollama mặc định tắt; không cần cài ở bước này.
- Không mở port router, không đổi host thành 0.0.0.0. Launcher local không
  có đăng nhập và chỉ cho loopback. Muốn truy cập bằng điện thoại sau này
  cần cấu hình hosted HTTPS riêng; chỉ bật Tailscale không tự expose app.
- Không xóa `data/` khi cập nhật. Chạy lại file cài đặt sau khi thay phiên
  bản code/dependencies; không tự ghi đè `.env` sẵn có.

Nếu muốn tự chạy bằng PowerShell thay cho nhấp đúp:

```powershell
py -3 scripts/windows.py setup
.\.venv-windows\Scripts\python.exe scripts/windows.py start
```

## Phạm vi kiểm tra

Logic helper và HTTP startup/shutdown có thể kiểm tra trong môi trường
Linux phát triển, nhưng file `.cmd`, Windows launcher, Microsoft Store/
winget và browser mặc định Windows chưa được thực thi trên PC của bạn.
Chỉ xác nhận Windows thành công khi bạn chạy và thấy website hoạt động.
