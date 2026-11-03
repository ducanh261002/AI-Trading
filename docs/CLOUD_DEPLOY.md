# Đưa Command Center lên website riêng

## Bạn sẽ dùng gì?

Chỉ mở website bằng Chrome/Edge trên PC hoặc điện thoại. Không cài Python,
Ollama hay ứng dụng desktop trên Windows. Các lệnh bên dưới chạy trong
**web console của máy chủ cloud**, không chạy trên PC.

Bộ giao gồm backend, frontend, Dockerfile, Compose, reverse proxy Caddy,
đăng nhập HTTPS, SQLite volume và hướng dẫn backup. Chưa có hosting account,
tên miền hoặc quyền truy cập của bạn nên chưa thể tạo URL riêng thay bạn.
Publish môi trường Codex là snapshot phát triển; không thay việc thuê hoặc
cấp máy chủ chạy website 24/7 và cấu hình DNS/TLS.

## 1. Chuẩn bị hosting và chi phí

Chọn Linux VM Ubuntu 24.04 LTS có persistent disk, tối thiểu 1 vCPU/1 GB RAM
(2 GB nếu bật nhiều tính năng), khoảng 10–20 GB đĩa. Cần quyền root trong web
console, IP công khai và outbound HTTPS/WSS hợp lệ tới Binance. Ollama tắt
trên cloud nhỏ; tính toán Agent/strategy vẫn chạy bằng Python.

Không chọn chỉ static hosting (GitHub Pages/Netlify) vì cần Python server,
WebSocket và SQLite. Không dùng free filesystem bị xóa khi restart cho DB.

Ước lượng lập ngân sách, chưa phải báo giá đã xác minh tại nhà cung cấp:

| Hạng mục | Dự trù |
|---|---:|
| Mã nguồn, thư viện, TLS Let's Encrypt | 0 VNĐ |
| Domain/subdomain thuộc domain đã có | 0 VNĐ nếu đã có |
| Domain mới, nếu cần | khoảng 200.000–350.000 VNĐ/năm |
| VM nhỏ | khoảng 120.000–200.000 VNĐ/tháng |
| LLM API | 0 VNĐ, không dùng |

Ngân sách 1.000.000 VNĐ đủ giai đoạn thử nghiệm khoảng 3–6 tháng tùy giá
VM/domain/thuế, không đủ hứa hosting miễn phí hoặc chạy vô thời hạn. Không
bao gồm vốn giao dịch, phí sàn hoặc dữ liệu trả phí. Nếu dùng free tier cần
xác minh quota, persistence và điều khoản cụ thể trước khi chọn.

Chọn dịch vụ có quyền truy cập Binance hợp lệ cho tài khoản/khu vực của
bạn. Cloud hiện tại trả HTTP 451; không xem đổi proxy/VPN để né hạn chế là
một bước triển khai hợp lệ.

## 2. Tạo máy chủ và DNS trong trình duyệt

1. Tạo VM Ubuntu 24.04 từ dashboard nhà cung cấp; mở web console của VM.
2. Trong quản trị DNS của domain, tạo A record `trading` trỏ tới IPv4 VM.
   Ví dụ bạn sở hữu `example.com` thì website là `trading.example.com`.
3. Chỉ giữ AAAA record nếu VM thật sự phục vụ IPv6 ở địa chỉ đó. Mở inbound
   TCP 80/443 ở cloud firewall; không mở 8000 ra Internet. Nếu dùng SSH,
   giới hạn 22 theo IP quản trị thay vì mở cho mọi nơi.
4. Dùng chức năng upload file của cloud console để đưa `AI-Trading-web.zip`
   lên VM. Nếu console không hỗ trợ upload, dùng storage/file manager của
   nhà cung cấp hoặc tải artifact lên kho riêng và tải từ VM. Không có URL
   công khai giả cho file trong cuộc trò chuyện này.

Không cần mua/cấu hình domain khi chỉ đọc mã, nhưng domain/IP và tài khoản
hosting là điều kiện cần để có website riêng ngoài môi trường Codex.

## 3. Cài Docker trên VM qua web console

Các lệnh sau dành cho VM mới Ubuntu 24.04, chạy với root hoặc sudo:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl unzip nano
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
printf '%s\n' 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable' | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

Dùng VM x86_64/amd64 cho lệnh repository trên. Nếu chọn ARM64, đổi `arch`
cho đúng và xác minh wheels Python; bản Docker đã test là amd64. Các lệnh
apt cài máy chủ chưa chạy trên VM của bạn; image ứng dụng đã build/test ở
môi trường phát triển, không đồng nghĩa domain của bạn đã được xuất bản.

## 4. Giải nén và tạo cấu hình bí mật

Giả sử upload ZIP ở thư mục hiện tại:

```bash
sudo mkdir -p /opt/ai-trading
sudo unzip AI-Trading-web.zip -d /opt/ai-trading
cd /opt/ai-trading/AI-Trading
sudo docker build -t ai-trading-web:latest .
sudo docker run --rm -it ai-trading-web:latest python -m app.ops hash-password
```

Nhập mật khẩu quản trị dài ít nhất 12 ký tự và nhập lại; terminal không hiện
mật khẩu. Lệnh chỉ in chuỗi hash dạng `scrypt:...:...`. Giữ mật khẩu trong
password manager; không đưa mật khẩu vào chat hoặc source code.

```bash
sudo cp deploy/cloud.env.example .env.cloud
sudo chmod 600 .env.cloud
sudo nano .env.cloud
```

Sửa bốn mục: DOMAIN, ACME_EMAIL, ATC_PUBLIC_ORIGIN và ATC_ADMIN_PASSWORD_HASH.
Ví dụ domain thật của bạn là trading.example.com thì DOMAIN bằng domain đó,
ATC_PUBLIC_ORIGIN bằng `https://trading.example.com` và email là email nhận
thông báo chứng chỉ. Dán hash vừa tạo vào ATC_ADMIN_PASSWORD_HASH, không dán
mật khẩu thô. `.env.cloud` không được commit/upload vào GitHub.

Giữ `ATC_HOSTED=true`, `ATC_MODE=paper`, `ATC_OLLAMA_ENABLED=false`,
`ATC_PAPER_AUTO=false`, `ATC_AGENT_AUTO_SECONDS=0` lúc chạy lần đầu. Không
cần BINANCE API key để xem market và dùng paper. Không có cấu hình Live.

## 5. Khởi động website

```bash
sudo docker compose --env-file .env.cloud config --quiet
sudo docker compose --env-file .env.cloud up -d --build
sudo docker compose --env-file .env.cloud ps
sudo docker compose --env-file .env.cloud logs --tail=100 web
sudo docker compose --env-file .env.cloud logs --tail=100 proxy
```

`config --quiet` kiểm tra cú pháp mà không in giá trị secrets. Caddy tự xin
và gia hạn TLS khi DNS đúng và 80/443 mở. App chưa có password hash/HTTPS
origin hợp lệ sẽ fail startup. Backend 8000 chỉ nằm trên mạng Compose.

Mở **https://domain-thật-của-bạn** bằng trình duyệt và đăng nhập. Bản giao
không tạo một URL đang hoạt động vì bạn chưa cung cấp/thiết lập hosting và
DNS. Hãy dùng domain đã cấu hình ở bước 2, không dùng địa chỉ loopback từ
môi trường phát triển.

## 6. Nghiệm thu website lần đầu

- Trang login hoạt động, HTTPS hợp lệ, chưa login không xem được portfolio.
- Balance 10.000 USDT có nhãn PAPER: đây là tiền giả lập, không phải tài sản.
- Market chỉ hiện LIVE khi cả hai WS và mọi nguồn đủ mới. HTTP 451/blocked
  nghĩa là chưa dùng realtime được; không bấm bật paper để bỏ qua.
- Bấm CEO chạy chu kỳ: 16 nhiệm vụ có ID/kết quả/log. News có thể Waiting
  khi chưa cấu hình RSS; không chặn technical strategies nhưng không có
  đánh giá news thật.
- Với tối thiểu 120 nến đã đóng, chạy backtest trên dashboard; từ 200 nến
  có holdout. Nếu không có tín hiệu thì 0 trade là kết quả hợp lệ, không là
  bằng chứng có lợi nhuận. Không có market trong cloud hiện tại nên các
  kết quả kiểm thử giao dịch của bản giao dùng fixtures, không là dữ liệu sàn.
- Bật 3D kiểm tra WebGL; nếu không có GPU/WebGL thì dùng 2D vẫn đủ điều khiển.
- Trước paper fill: tick xác nhận tiền mô phỏng, bấm “Bật quyền PAPER”. Lệnh
  mới vẫn qua risk và có thể bị từ chối/HOLD. Kill Switch chặn mở mới.

Để chạy paper tự động sau nghiệm thu:

```bash
sudo nano .env.cloud
```

Đặt `ATC_PAPER_AUTO=true`, tùy chọn `ATC_AGENT_AUTO_SECONDS=60`, rồi:

```bash
sudo docker compose --env-file .env.cloud up -d --force-recreate web
```

Đăng nhập lại nếu cần; restart luôn bật Kill Switch. Chỉ bấm bật PAPER khi
market fresh và đã hiểu kết quả backtest. Đây vẫn không gửi lệnh Binance.
Không có bước tự chuyển sang tiền thật. Chưa có account keys/Testnet
execution certification; đọc TRADING.md trước khi dự định tích hợp sàn.

## 7. Dữ liệu, backup và cập nhật

Named volume `trading_data` chứa SQLite; `caddy_data` chứa TLS state. App
chạy UID 10001, filesystem read-only trừ volume và /tmp. Không dùng nhiều
backend replicas: queue/SQLite/worker lock thiết kế một tiến trình.

App tạo backup SQLite nhất quán mỗi ngày vào `data/backups`, giữ 7 ngày;
report cập nhật mỗi phút cho giờ/ngày/tuần theo Asia/Ho_Chi_Minh; logs DB
và task cycles đã kết thúc cũ hơn 30 ngày được xóa; giữ 100 backtest đầy đủ gần nhất. Docker logs giới hạn 3×10 MB mỗi service. Trade
ledger không tự xóa; nút tải JSON trên UI xuất 500 bút toán gần nhất, backup DB giữ toàn bộ ledger. Backup trong cùng volume không bảo vệ khỏi mất VM:
phải tải bản backup ra storage riêng định kỳ.

Backup thủ công qua web console VM:

```bash
sudo docker compose --env-file .env.cloud exec web python -m app.ops backup /app/data/command_center.sqlite3 /tmp/command-center-backup.sqlite3
sudo docker compose --env-file .env.cloud exec web python -m app.ops check-backup /tmp/command-center-backup.sqlite3
sudo docker compose --env-file .env.cloud cp web:/tmp/command-center-backup.sqlite3 ./command-center-backup.sqlite3
```

Lệnh backup yêu cầu đích chưa tồn tại; nếu chạy lại hãy dùng tên file mới
hoặc xóa riêng bản tạm do bạn tạo sau khi đã tải bản tốt về nơi lưu trữ.
Kiểm tra `ok` rồi tải file qua file manager của nhà cung cấp. DB backup
chứa dữ liệu giao dịch và session hashes; lưu ở nơi riêng tư.

Khôi phục khi có sự cố (không làm khi chỉ cập nhật code):

```bash
sudo docker compose --env-file .env.cloud stop web
sudo docker compose --env-file .env.cloud cp ./command-center-backup.sqlite3 web:/app/data/restored.sqlite3
sudo docker compose --env-file .env.cloud run --rm --no-deps --user 0 --cap-add CHOWN web sh -c 'rm -f /app/data/command_center.sqlite3-wal /app/data/command_center.sqlite3-shm; cp /app/data/restored.sqlite3 /app/data/command_center.sqlite3; chown 10001:10001 /app/data/command_center.sqlite3'
sudo docker compose --env-file .env.cloud up -d web
```

Trước khôi phục, giữ bản DB hiện tại để có thể quay lại; chỉ làm sau khi
backup đích đã qua integrity check. Session trong backup có thể cũ; nếu
khôi phục từ nguồn không hoàn toàn tin cậy thì xóa auth_sessions trước mở
lại website và đổi mật khẩu hash. Để thu hồi session sau đổi mật khẩu, dừng
web, dùng Python/SQLite trong maintenance container xóa bảng auth_sessions,
rồi recreate web với hash mới. Không xóa volume để xử lý lỗi đăng nhập.

Cập nhật code: backup, tải ZIP mới vào thư mục mới, giữ `.env.cloud` cũ,
đứng tại project directory đúng và dùng cùng tên Compose project/volume.
Ví dụ đặt `COMPOSE_PROJECT_NAME=ai-trading` cố định trong `.env.cloud` ngay
lần đầu để các lần đổi thư mục không vô tình tạo volume khác. Chạy up --build.
Không chạy `docker compose down -v` nếu muốn giữ dữ liệu.

## Lỗi thường gặp

| Lỗi | Xử lý |
|---|---|
| Site không mở | Kiểm tra IP, A/AAAA, DNS propagation, firewall 80/443 và Caddy logs |
| Caddy TLS thất bại | Domain chưa trỏ đúng hoặc port challenge bị chặn; không tắt HTTPS để lách login |
| App unhealthy | Kiểm tra .env.cloud có hash scrypt và public origin đúng; xem logs không in secrets |
| 401 | Đăng nhập lại; session hết hạn sau 8 giờ |
| 403 CSRF | Dùng domain đúng HTTPS, refresh login; không gọi mutation từ origin khác |
| 429 login | Đợi 10 phút; kiểm tra password manager không tự gửi liên tục |
| Market 451 | Kiểm tra quyền truy cập hợp lệ với Binance; không bỏ freshness gate |
| Paper rejected | Xem lý do risk, market freshness, Kill Switch, lot filters và signal |
| Backtest thiếu nến | Chờ bootstrap thành công; không thêm dữ liệu giả vào dashboard production |
| GPU yếu/WebGL lỗi | Tắt 3D, dùng 2D; dữ liệu và điều khiển không phụ thuộc 3D |
| Account số dư về mặc định | Kiểm tra đã gắn đúng named volume/Compose project trước khi làm gì khác |

## Những việc vẫn cần bên ngoài bản code

Bạn cần hosting, domain/DNS và nhập password hash trong môi trường server.
Chưa có quyền đó nên tôi chưa thể thực hiện public deployment/cấp TLS thật.
Binance market phải truy cập hợp lệ; Testnet cần key riêng và nghiệm thu
trên sàn. Các bước này không thể được thay bằng mock hoặc một URL bịa.
