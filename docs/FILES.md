# Các file trong bản giao

Source, tests, deploy và tài liệu; không liệt kê venv, DB hoặc secret files.

```text
app/orchestration/brief.py
docs/AUTONOMOUS_RESEARCH.md
tests/test_research.py
CAI_DAT_WINDOWS.cmd
MO_WEBSITE.cmd
scripts/windows.py
tests/test_windows_helper.py
docs/WINDOWS_LOCAL.md
compose.private.yaml
deploy/private.env.example
docs/PRIVATE_ACCESS.md
.dockerignore
.env.example
.gitignore
Dockerfile
README.md
app/__init__.py
app/agents.py
app/config.py
app/db.py
app/execution/__init__.py
app/execution/testnet.py
app/main.py
app/market/__init__.py
app/market/engine.py
app/market/models.py
app/market/probe.py
app/market/rest.py
app/market/store.py
app/news.py
app/ops.py
app/orchestration/__init__.py
app/orchestration/llm.py
app/orchestration/lock.py
app/orchestration/manager.py
app/orchestration/store.py
app/orchestration/tools.py
app/security.py
app/static/dashboard.js
app/static/index.html
app/static/login.html
app/static/login.js
app/static/scene.js
app/static/style.css
app/static/vendor/SOURCE.txt
app/static/vendor/THREE-LICENSE.txt
app/static/vendor/three.module.js
app/trading/__init__.py
app/trading/backtest.py
app/trading/indicators.py
app/trading/paper.py
app/trading/risk.py
app/trading/service.py
app/trading/strategies.py
compose.yaml
deploy/Caddyfile
deploy/cloud.env.example
docs/ACCEPTANCE.md
docs/CLOUD_DEPLOY.md
docs/PHASE2.md
docs/PHASE3.md
docs/ROADMAP.md
docs/TRADING.md
requirements.lock.txt
requirements.txt
tests/test_agents.py
tests/test_foundation.py
tests/test_hosted.py
tests/test_market.py
tests/test_testnet.py
tests/test_trading.py
docs/FILES.md
```

Mã nguồn từng file nằm nguyên vẹn trong ZIP; không có function TODO hoặc pseudocode thay cho module chạy. Phạm vi chưa được chứng nhận được nêu tại ACCEPTANCE.md.

## Chế độ quan sát 3D

- `app/observatory.py`: snapshot nhiệm vụ thực, không trả raw results hay secrets.
- `app/static/index.html`, `observer.js`, `observer.css`: văn phòng tự cập nhật.
- `app/static/scene.js`: bàn/nhân vật 3D, nhãn nhiệm vụ, picking và fallback 2D.
- `app/static/operator.html`: bảng điều khiển cũ dành cho dùng nâng cao.
- `tests/test_observatory.py`: tự nghiên cứu, migration, giữ trạng thái dừng, khóa mở vị thế.
- `docs/OBSERVER_MODE.md`: hướng dẫn quan sát và cập nhật Windows.

- `app/static/workbench.js`, `workbench.css`: đội ngũ, bàn làm việc, dependency graph, chọn chu kỳ và đọc bằng chứng.
- `docs/images/agent-office.png`: ảnh xem trước đã ghi rõ dữ liệu fixture.

- `app/orchestration/live.py`: chỉ thị, hộp thư có bằng chứng, theo dõi định kỳ, kết nối model, đánh giá cải tiến.
- `app/static/collaboration.js`, `collaboration.css`: giao việc/AI/PAPER, phòng trao đổi và cập nhật theo dõi.
- `CAI_AI_WINDOWS.cmd`: hướng dẫn cài Ollama và tải model local trên Windows.
- `docs/AI_TRADING_CENTER.md`: cách dùng và giới hạn tự động hóa.
- `tests/test_collaboration.py`: kiểm thử phối hợp, model và PAPER autopilot.

- `app/trading/telemetry.py`: PnL PAPER từ ledger/positions, lịch sử 24h và chẩn đoán lệnh.
- `app/static/analytics.js`, `analytics.css`: PnL, chẩn đoán và tạo Agent chuyên biệt.
- `tests/test_telemetry.py`: kiểm tra PnL, lịch sử và quyền Agent bổ sung.
- `docs/images/paper-pnl.png`: ảnh fixture của PnL/chẩn đoán.
