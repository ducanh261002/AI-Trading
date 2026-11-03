# Dùng riêng qua Tailscale — không mua tên miền

Bạn dùng website trên trình duyệt; Tailscale chỉ tạo đường kết nối riêng
giữa thiết bị của bạn và VPS. Vẫn cần VPS nếu muốn website chạy 24/7 mà
không phụ thuộc PC. Không cần mua domain hoặc public website ra Internet.

Hướng dẫn này thay phần DNS/Caddy trong CLOUD_DEPLOY.md. Code paper, Risk,
database và đăng nhập không thay đổi. Chưa triển khai vào tailnet của bạn;
bạn chưa có VPS và chưa cấp quyền vào tài khoản Tailscale.

## Việc đầu tiên, chưa cần trả tiền

1. Mở https://login.tailscale.com/ và tạo/đăng nhập tài khoản cá nhân theo
   các lựa chọn trang hiển thị. Kiểm tra gói Personal và giá hiện hành tại
   https://tailscale.com/pricing trước khi chọn; không cần mua gói doanh nghiệp.
2. Cài Tailscale trên thiết bị dùng mở website, từ
   https://tailscale.com/download . Đăng nhập cùng tài khoản.
3. Chưa cần nhập IP, API Key hay mua domain. Sau bước này mới chọn VPS.

Tailscale là phần mềm kết nối mạng, không phải ứng dụng trading. Ứng dụng
trading vẫn được mở và sử dụng hoàn toàn trong trình duyệt. Nếu không muốn
cài thêm phần mềm trên thiết bị, phải chọn phương án hosting có HTTPS
subdomain thay cho hướng dẫn này.

## Sau khi đã có VPS Ubuntu 24.04

Các lệnh dưới đây chạy ở **web console của VPS**, không chạy trong môi
trường Codex và không cài vào PC Windows. Cần Docker và Git trên VPS;
hướng dẫn cài Docker ở bước 3 của CLOUD_DEPLOY.md vẫn áp dụng.

### 1. Cài Tailscale trên VPS

Dùng hướng dẫn Ubuntu chính thức tại https://tailscale.com/download/linux .
Tài liệu cài đặt phụ thuộc phiên bản Ubuntu, nên thực hiện đúng trang cho
24.04. Không tắt TLS hoặc tự lấy script từ nguồn không xác định.

Khi đã có lệnh tailscale:

```bash
sudo tailscale up
```

Mở liên kết đăng nhập mà lệnh in ra trong trình duyệt và đăng nhập đúng
tài khoản đang dùng trên PC/điện thoại. Không gửi liên kết đăng nhập, auth
key hoặc thông tin tài khoản cho người khác.

Trong admin console Tailscale, máy chủ và thiết bị cá nhân phải cùng tailnet.
Bật MagicDNS và HTTPS Certificates nếu Serve yêu cầu. Sau đó trên VPS:

```bash
sudo tailscale serve --bg http://127.0.0.1:8080
sudo tailscale serve status
```

Serve có thể yêu cầu bạn mở một liên kết để cho phép HTTPS; làm theo liên
kết chính thức lệnh cung cấp. Backend chưa chạy thì nhận 502 lúc này là
bình thường. Lấy chính xác URL HTTPS được in ra, ví dụ tên máy có đuôi
`.ts.net`; ví dụ trong tài liệu không phải địa chỉ thật của bạn.

**Dùng Serve, không bật Funnel.** Funnel công khai dịch vụ ra Internet.
Serve chỉ cho thiết bị được tailnet policy cho phép. HTTPS hostname có
thể xuất hiện trong certificate transparency logs; điều đó không tự mở
quyền vào website. Chọn tên máy không chứa thông tin nhạy cảm.

Không bật exit node cho mục đích này: Binance vẫn đi bằng kết nối bình
thường của VPS. Tailscale không giải quyết hạn chế truy cập Binance HTTP 451.

### 2. Lấy code từ GitHub, không cần tải ZIP về Windows

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/ducanh261002/AI-Trading.git
cd AI-Trading
sudo docker build -t ai-trading-web:latest .
sudo docker run --rm -it ai-trading-web:latest python -m app.ops hash-password
```

Nếu repository private, clone cần quyền GitHub của bạn. Dùng cách xác thực
chính thức của GitHub; không dán token vào URL, chat hay source. Đây là
repository của bạn, không yêu cầu chuyển public để deploy.

Lệnh hash-password hỏi mật khẩu quản trị website (ít nhất 12 ký tự), rồi
in hash `scrypt:...:...`. Mật khẩu này là lớp bảo vệ riêng, ngoài Tailscale.

```bash
cp deploy/private.env.example .env.private
chmod 600 .env.private
nano .env.private
```

Điền hai mục:

- `ATC_PUBLIC_ORIGIN`: URL HTTPS **đúng từ Serve**, không có đường dẫn hoặc
  dấu `/` cuối. Không nhập IP 100.x hoặc IP public thay cho HTTPS hostname.
- `ATC_ADMIN_PASSWORD_HASH`: chuỗi hash vừa tạo, không phải mật khẩu thô.

Giữ paper auto tắt và không nhập Binance key. Không cần DOMAIN/ACME_EMAIL,
không chạy Caddy hoặc Compose công khai trong phương án này.

### 3. Khởi động backend riêng

```bash
sudo docker compose -f compose.private.yaml --env-file .env.private config --quiet
sudo docker compose -f compose.private.yaml --env-file .env.private up -d --build
sudo docker compose -f compose.private.yaml --env-file .env.private ps
```

Port 8080 chỉ bind vào loopback của VPS. Không mở 8080 hoặc web ports
80/443 công khai cho cách này. Cấu hình kết nối Tailscale/firewall theo
tài liệu chính thức; mạng overlay có thể hoạt động qua relay khi cần.
Không dùng `0.0.0.0:8080` thay cho bind loopback trong Compose.

Trên thiết bị cá nhân, bật Tailscale rồi mở URL HTTPS từ Serve. Đăng nhập
bằng mật khẩu quản trị website đã tạo. Không cần PC bật để VPS tiếp tục
chạy; cần Tailscale bật trên thiết bị đang mở website.

Nếu tailnet có người khác, kiểm tra access grants/ACL vì quyền mặc định
có thể cho các thành viên khác kết nối. Với nhu cầu một người, không mời
thêm thành viên hoặc chia sẻ thiết bị. Website vẫn yêu cầu mật khẩu riêng.

## Kiểm tra và vận hành

- `tailscale status`: cả VPS và thiết bị của bạn đã đăng nhập/kết nối.
- `tailscale serve status`: URL HTTPS và backend 127.0.0.1:8080 đúng.
- `docker compose ... ps`: web healthy. Nếu unhealthy, xem logs web.
- Mở URL qua Tailscale: thấy login; chưa login không đọc được portfolio.
- Tắt kết nối Tailscale trên thiết bị: không còn truy cập riêng được.
- Không có dữ liệu Binance/HTTP 451: giữ Kill Switch, không bỏ freshness
  hoặc risk gate. Paper balance không phải tài sản sàn.

Serve --bg lưu cấu hình nền, nhưng vẫn phải kiểm tra lại sau reboot VPS.
Theo dõi key expiry/device approval trong admin console; không tự tắt hết
chính sách tài khoản để làm website truy cập được.

Backup vẫn dùng named volume trading_data và SQLite API. Thay mọi lệnh
Compose trong CLOUD_DEPLOY.md bằng tiền tố của cấu hình riêng:

```bash
sudo docker compose -f compose.private.yaml --env-file .env.private exec web python -m app.ops backup /app/data/command_center.sqlite3 /tmp/private-backup.sqlite3
sudo docker compose -f compose.private.yaml --env-file .env.private exec web python -m app.ops check-backup /tmp/private-backup.sqlite3
sudo docker compose -f compose.private.yaml --env-file .env.private cp web:/tmp/private-backup.sqlite3 ./private-backup.sqlite3
```

Giữ cùng COMPOSE_PROJECT_NAME khi cập nhật để không tạo volume khác. Không
chạy public và private stack cùng lúc với cùng database/worker. Chuyển
phương án phải backup và dừng backend cũ trước.

## Nguồn và phạm vi xác minh

- CLI Serve đối chiếu với source chính thức Tailscale:
  https://github.com/tailscale/tailscale/blob/main/cmd/tailscale/cli/serve_v2.go
- Proxy Host/HTTPS forwarding:
  https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go
- Tài liệu: https://tailscale.com/kb/1242/tailscale-serve

Đã kiểm tra Compose riêng chỉ có web, port loopback và không cần domain.
Chưa join tailnet, cấp HTTPS cho máy của bạn hoặc kiểm tra kết nối thiết
bị thật. Không cài hay cấu hình một VPN khác trong managed Codex executor.
