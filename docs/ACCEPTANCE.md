# Bằng chứng nghiệm thu và trạng thái bản giao

Ngày ghi nhận: 03/11/2026, Asia/Ho_Chi_Minh. Đây là bản website paper,
không là chứng nhận hệ thống giao dịch tiền thật.

## Đã thực hiện

- Bộ test Python: 47 bài, gồm hồi quy Foundation/Market/Agents và các test
  mới cho indicators, strategy HOLD/warmup, risk rejects, sizing/costs,
  stop-first/next-open/holdout, paper dedup/close/ledger/restart, backup,
  hosted login/cookies/CSRF/rate-limit, Testnet signing/UNKNOWN/reconcile.
- Bổ sung helper Windows: bảo toàn `.env`, không đánh dấu setup thành công
  khi pip thất bại, phát hiện lockfile thay đổi, từ chối port đang bận và
  kiểm tra HTTP startup/cleanup đúng process. Logic chạy trong Linux; file
  CMD và setup trên Windows thực vẫn cần chủ máy kiểm tra.
- Bổ sung autonomous research: CEO tự enqueue, Backtest Agent chạy 3 chiến
  lược cùng snapshot, Report Agent tạo brief, không duplicate khi chưa có
  nến mới, cache theo chi phí, research không gọi paper.enter dù đã arm,
  preference qua restart và migration dữ liệu cũ. Chromium fixture có 2
  báo cáo/6 dòng chiến lược, tự chạy khi thêm nến, không overflow mobile
  và không JavaScript page errors.
- HTTP workflow: backend local, tạo chu kỳ 16 Agent, không duplicate cùng
  key, Risk/Execution bị chặn mặc định và `/api/orders` trả 403.
- Chromium: desktop 1440px, mobile 390px, 16 Agent cards, chu kỳ từ UI,
  Three.js WebGL software render hoạt động, không horizontal overflow
  và không page-level JavaScript errors trong lần kiểm tra.
- Docker image build; container non-root, read-only root filesystem,
  named data volume, public health 200 và chưa login portfolio 401.
- Backup bằng SQLite API trong container, đọc lại integrity_check = ok.
  Fixture restore vào DB mới giữ trade/PnL và bắt buộc Kill Switch khi mở lại.
- Chromium HTTPS fixture local: login, cookie Secure/HttpOnly, CSRF mutation
  và logout được kiểm tra. Chứng chỉ tự ký chỉ dùng ở fixture test; không
  thay đổi kiểm tra TLS của ứng dụng hoặc cấp chứng chỉ cho domain thật.
- Compose config --quiet và Caddy validate thành công; chưa xin chứng chỉ
  hoặc trỏ DNS/domain thật.
- Đối chiếu advisory PyPI cho lockfile. FastAPI/Starlette và pytest cũ đã
  được nâng lên bản được PyPI báo không có advisory lúc kiểm tra. Bằng
  chứng cuối nằm ở artifacts/dependency-advisories.json khi đóng gói.
  Đây chỉ là kiểm tra advisory dependency, không là penetration test hay
  kiểm toán toàn bộ base image/hệ điều hành.
- Three.js 0.160.1 từ npm đã kiểm tra integrity SHA-512, license MIT được giữ.

Các lần kiểm thử dùng thư mục DB tạm và dữ liệu fixture có chủ ý. Không
đưa dữ liệu fixture vào thị trường thật trên dashboard. CI/local tests
không cần key Binance; Testnet adapter dùng MockTransport khi test.

## Chưa có bằng chứng / bị chặn

1. Binance market API từ cloud hiện tại trả HTTP 451. Chưa xác nhận market
   REST+WS thật; không có backtest trên dữ liệu sàn thật hoặc forward paper
   dài ngày. Quyền allowlist đã enforced, nên không coi đây là thiếu miền.
2. Không có BINANCE_TESTNET_API_KEY/SECRET trong môi trường. Probe ghi nhận
   thiếu credentials, không gửi request hoặc lệnh. Đặt/sửa/hủy, SL/TP,
   partial fill, Hedge lifecycle, emergency recovery trên Testnet chưa chạy.
3. Chưa có hosting account, domain/DNS và quyền triển khai riêng của chủ
   website. Không có URL công khai hoặc chứng chỉ TLS thật đã cấp.
4. Ollama thật, RSS provider thật, chạy 24h, benchmark iGPU Windows và
   penetration testing chưa thực hiện. Không cần chúng để mở bản paper web
   nhưng không được gọi là đã nghiệm thu các khả năng tương ứng.
5. Không có production exchange execution; không tồn tại Live toggle. Để
   triển khai tiền thật phải có một đợt engineering và xác nhận riêng sau
   test thực tế; code hiện tại không thể tự chuyển Live.

## Tiêu chí sau khi cài lên cloud riêng

- Domain HTTPS hợp lệ, login và CSRF hoạt động, port 8000 không public.
- Volume còn dữ liệu sau recreate; restore rehearsal trên volume thử thành
  công; backup được tải ra ngoài VM, không chỉ cùng ổ đĩa.
- Market probe exit 0 qua nguồn được phép, freshness và reconnect thực tế
  được kiểm tra, 451/429/timeout không bị bỏ qua.
- Backtest trên dữ liệu dài hơn và holdout, forward paper đủ lịch sử, đối
  chiếu đầy đủ phí/funding; review output trước mọi quyết định vốn.
- Testnet integration có key riêng và test lifecycle đầy đủ; không mở
  execution chỉ nhờ có chữ “pass” từ mock tests.

## Chế độ quan sát 3D

Bổ sung kiểm thử tự bật nghiên cứu lần đầu sau migration, giữ lựa chọn dừng,
tạo báo cáo tự động không bấm lệnh và khóa mở vị thế tại API/tool/broker.
Kiểm tra trình duyệt dùng dữ liệu fixture, không phải kết quả giao dịch thực.
Chưa thử trực tiếp bản mới trên máy Windows của người dùng.

Chromium: 16 nhãn không chồng nhau, 16 thẻ Agent, hai báo cáo tự tạo,
bấm bàn mở chi tiết, chuyển 2D/3D thành công. Màn hình 390px không tràn ngang,
không có lỗi JavaScript. Evidence cục bộ: `artifacts/observer-verification.json`.
