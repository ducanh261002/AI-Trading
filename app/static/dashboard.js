async function api(path, method = 'GET', body = undefined) {
  const csrf = document.cookie.split('; ').find(row => row.startsWith('atc_csrf='))?.split('=')[1];
  const response = await fetch(path, {method, signal: AbortSignal.timeout(8000),
    headers: {...(body === undefined ? {} : {'Content-Type': 'application/json'}), ...(csrf ? {'X-CSRF-Token': csrf} : {})},
    body: body === undefined ? undefined : JSON.stringify(body)});
  if (response.status === 401) { location.assign('/login'); throw new Error('Cần đăng nhập'); }
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    throw new Error(typeof failure.detail === 'string' ? failure.detail : `HTTP ${response.status}`);
  }
  return response.json();
}
async function refresh() {
  await refreshResearch();
  const [status, agents, tasks, events] = await Promise.all(['/api/status', '/api/agents', '/api/tasks', '/api/events'].map(p => api(p)));
  for (const [id, value] of Object.entries({status, tasks, events})) document.getElementById(id).textContent = JSON.stringify(value, null, 2);
  const container = document.getElementById('agents');
  container.replaceChildren();
  agents.forEach(agent => {
    const card = document.createElement('div'); card.className = 'agent';
    const title = document.createElement('strong'); title.textContent = agent.name;
    const detail = document.createElement('small'); detail.textContent = `${agent.department} · ${agent.status}`;
    const activity = document.createElement('small');
    activity.textContent = agent.latest_task ? `Công cụ: ${agent.latest_task.tool} · Task: ${agent.latest_task.id}` : 'Chưa có nhiệm vụ';
    card.dataset.state = agent.status;
    card.append(title, detail, activity); container.append(card);
  });
  window.dispatchEvent(new CustomEvent('agent-states', {detail: agents}));
  document.getElementById('safety-status').textContent = status.halted ? 'Kill Switch đang bật — chặn mở vị thế mới.' : 'Đã bật quyền mô phỏng; lệnh thật luôn bị khóa.';
  document.getElementById('logout').hidden = !status.hosted;
  await refreshMarket();
  const cycles = await api('/api/agent-cycles');
  document.getElementById('cycles').textContent = JSON.stringify(cycles, null, 2);
  const selected = activeRun || cycles[0]?.id;
  if (selected) document.getElementById('cycle-result').textContent = JSON.stringify(await api(`/api/agent-cycles/${selected}`), null, 2);
  await refreshTrading();
}

const money = value => Number(value).toLocaleString('en-US', {maximumFractionDigits: 2});
async function refreshTrading() {
  const [portfolio, performance] = await Promise.all([api('/api/portfolio'), api('/api/performance')]);
  for (const [id, value] of Object.entries({balance: portfolio.balance, equity: portfolio.equity, 'daily-pnl': portfolio.daily_pnl})) document.getElementById(id).textContent = `${money(value)} USDT`;
  document.getElementById('drawdown').textContent = `${money(portfolio.drawdown * 100)}%`;
  const positions = document.getElementById('positions'); positions.replaceChildren();
  for (const position of portfolio.positions) {
    const row = document.createElement('tr');
    for (const value of [`${position.symbol} / ${position.strategy}`, position.side, position.quantity, money(position.entry), `${money(position.stop)} / ${money(position.take_profit)}`, money(position.unrealized_pnl)]) {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    }
    positions.append(row);
  }
  if (!portfolio.positions.length) {const row = document.createElement('tr'), cell = document.createElement('td');cell.colSpan=6;cell.textContent='Chưa có vị thế mô phỏng';row.append(cell);positions.append(row);}
  document.getElementById('performance').textContent = JSON.stringify({paper_trades: performance.trade_count, by_strategy: performance.by_strategy}, null, 2);
  const symbol = document.getElementById('symbol').value;
  if (symbol) {
    const strategy = await api(`/api/strategies/${symbol}?interval=${document.getElementById('interval').value}`);
    const {proposals, indicators, ...brief} = strategy;
    document.getElementById('strategy-result').textContent = JSON.stringify(brief, null, 2);
    const technical = indicators || proposals?.find(row => row.indicators)?.indicators;
    document.getElementById('indicator-summary').textContent = technical
      ? `RSI ${money(technical.rsi)} · MACD ${money(technical.macd)} · ATR ${money(technical.atr)} · BB ${money(technical.bb_lower)} – ${money(technical.bb_upper)}`
      : 'Đang chờ đủ nến để tính chỉ báo';
  }
}

for (const id of ['arm-paper', 'paper-run', 'run-backtest', 'logout']) document.getElementById(id).addEventListener('click', async event => {
  event.target.disabled = true;
  const feedback = document.getElementById(id === 'run-backtest' ? 'backtest-feedback' : 'paper-feedback');
  try {
    const body = {symbol: document.getElementById('symbol').value, interval: document.getElementById('interval').value};
    let result;
    if (id === 'arm-paper') {
      if (!document.getElementById('paper-confirm').checked) throw new Error('Hãy xác nhận bạn chỉ sử dụng tiền mô phỏng.');
      result = await api('/api/paper/arm', 'POST', {confirmation: 'ENABLE PAPER ONLY'});
    } else if (id === 'paper-run') result = await api('/api/paper/run', 'POST', body);
    else if (id === 'logout') {await api('/auth/logout', 'POST'); location.assign('/login'); return;}
    else {
      result = await api(`/api/backtests?strategy=${document.getElementById('backtest-strategy').value}`, 'POST', body);
      const {trades, equity_curve, ...summary} = result;
      document.getElementById('backtest-result').textContent = JSON.stringify(summary, null, 2);
    }
    feedback.textContent = id === 'run-backtest' ? 'Đã chạy mô phỏng. Kết quả không bảo đảm lợi nhuận tương lai.' : JSON.stringify(result);
  } catch (error) { feedback.textContent = error.message; }
  finally { event.target.disabled = false; }
});
for (const [id, endpoint, filename] of [['download-reports','/api/reports','paper-reports.json'],['download-ledger','/api/ledger','paper-ledger.json']]) document.getElementById(id).addEventListener('click', async () => {
  try {
    const result = await api(endpoint); const url = URL.createObjectURL(new Blob([JSON.stringify(result,null,2)], {type:'application/json'}));
    const link = document.createElement('a'); link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch(error) {document.getElementById('feedback').textContent=error.message;}
});

let activeRun = null;
let pendingCycleRequest = null;
document.getElementById('run-cycle').addEventListener('click', async event => {
  const symbol = document.getElementById('symbol').value;
  if (!symbol) return;
  event.target.disabled = true;
  const interval = document.getElementById('interval').value;
  if (!pendingCycleRequest || pendingCycleRequest.symbol !== symbol || pendingCycleRequest.interval !== interval) {
    pendingCycleRequest = {symbol, interval, request_key: crypto.randomUUID(), analysis_only: true};
  }
  try {
    const result = await api('/api/agent-cycles', 'POST', pendingCycleRequest);
    activeRun = result.run_id; pendingCycleRequest = null;
    document.getElementById('agent-feedback').textContent = 'Đã giao việc cho 16 Agent. Theo dõi bảng báo cáo tự động phía trên.';
  } catch (error) {
    document.getElementById('agent-feedback').textContent = `${error.message}. Bấm lại để kiểm tra cùng request ID.`;
  } finally { event.target.disabled = false; }
});

let researchEnabled = false;
let researchConfigLoaded = false;
let researchUpdating = false;
async function refreshResearch() {
  const state = await api('/api/research');
  researchEnabled = state.enabled;
  const selector = document.getElementById('research-interval');
  if (!researchConfigLoaded || state.enabled) selector.value = state.interval;
  researchConfigLoaded = true;
  selector.disabled = state.enabled || researchUpdating;
  const toggle = document.getElementById('research-toggle');
  toggle.disabled = !state.worker_running || researchUpdating;
  toggle.textContent = state.enabled ? 'Dừng tự phân tích' : 'Bật CEO tự phân tích';
  const mode = !state.worker_running ? 'WORKER CHƯA SẴN SÀNG' : state.enabled ? 'ĐANG THEO DÕI' : 'ĐÃ DỪNG';
  document.getElementById('research-status').textContent = `${mode} · ${state.symbols.join(', ')} · ${state.interval} · ${state.message}`;
  const container = document.getElementById('research-reports');
  container.replaceChildren();
  if (!state.reports.length) {
    const text = document.createElement('p');text.textContent='Bật CEO tự phân tích. Khi có đủ nến LIVE, Agent sẽ làm việc và đưa báo cáo tại đây.';container.append(text);
  }
  for (const report of state.reports) {
    const card = document.createElement('article'); card.className = 'research-report';
    const heading = document.createElement('h3');heading.textContent=`${report.symbol} · ${report.interval} · ${report.sample_candles} nến`;
    const date = document.createElement('small');date.textContent=report.finished_at ? `Báo cáo: ${new Date(report.finished_at).toLocaleString('vi-VN')}` : 'Đang xử lý';
    if(report.data_start!==null && report.data_end!==null) date.textContent+=` · Dữ liệu: ${new Date(report.data_start).toLocaleString('vi-VN')} – ${new Date(report.data_end).toLocaleString('vi-VN')}`;
    const summary = document.createElement('p');summary.textContent=report.summary;
    card.append(heading,date,summary);
    const scroll = document.createElement('div');scroll.className='table-scroll';
    const table = document.createElement('table'), head = document.createElement('thead'), titleRow=document.createElement('tr');
    for(const text of ['Chiến lược','Số lệnh','Lãi/lỗ mô phỏng','Drawdown','Lợi suất phần kiểm thử']){
      const cell=document.createElement('th');cell.textContent=text;titleRow.append(cell);
    }
    head.append(titleRow);table.append(head);
    const body=document.createElement('tbody');
    for(const result of report.comparisons){
      const row=document.createElement('tr');
      for(const text of [result.name,result.trades,`${money(result.pnl)} USDT (${money(result.return_percent)}%)`,`${money(result.drawdown_percent)}%`,result.test_return_percent===null?'Chưa đủ dữ liệu':`${money(result.test_return_percent)}% · ${result.test_trades} lệnh`]){
        const cell=document.createElement('td');cell.textContent=text;row.append(cell);
      }
      body.append(row);
    }
    table.append(body);scroll.append(table);card.append(scroll);
    const conclusion=document.createElement('p');conclusion.className='research-conclusion';conclusion.textContent=report.conclusion;card.append(conclusion);
    const warnings=document.createElement('ul');for(const warning of report.warnings){const item=document.createElement('li');item.textContent=warning;warnings.append(item);}card.append(warnings);
    const safety=document.createElement('small');safety.textContent=report.execution;card.append(safety);container.append(card);
  }
}
document.getElementById('research-toggle').addEventListener('click',async()=>{
  const targetEnabled=!researchEnabled;
  researchUpdating=true;
  document.getElementById('research-toggle').disabled=true;
  try {
    await api('/api/research','POST',{enabled:targetEnabled,interval:document.getElementById('research-interval').value});
    document.getElementById('research-feedback').textContent=targetEnabled ? 'Đã bật CEO. Các Agent sẽ tự xử lý khi dữ liệu sẵn sàng.' : 'Đã dừng giao việc mới. Chu kỳ đang chạy có thể hoàn tất.';
  } catch(error){document.getElementById('research-feedback').textContent=error.message;}
  finally {researchUpdating=false;await refreshResearch().catch(()=>{});}
});

function drawCandles(rows) {
  const canvas = document.getElementById('chart'), ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!rows.length) { ctx.fillStyle = '#a6b6ca'; ctx.fillText('Chưa có nến từ Binance', 20, 30); return; }
  const candles = rows.slice(-70), lows = candles.map(c => Number(c.low)), highs = candles.map(c => Number(c.high));
  const min = Math.min(...lows), max = Math.max(...highs), range = max - min || 1;
  const y = price => 260 - (Number(price) - min) / range * 235;
  const width = 880 / candles.length;
  ctx.fillStyle = '#a6b6ca'; ctx.font = '12px sans-serif';
  ctx.fillText(max.toPrecision(8), 890, 25); ctx.fillText(min.toPrecision(8), 890, 260);
  candles.forEach((c, i) => {
    const x = 10 + i * width + width / 2;
    ctx.strokeStyle = ctx.fillStyle = Number(c.close) >= Number(c.open) ? '#64dbc1' : '#f47791';
    ctx.beginPath(); ctx.moveTo(x, y(c.high)); ctx.lineTo(x, y(c.low)); ctx.stroke();
    ctx.fillRect(x - width * .3, Math.min(y(c.open), y(c.close)), width * .6, Math.max(1, Math.abs(y(c.close) - y(c.open))));
  });
  for (const [period, color] of [[9, '#9bc8ff'], [21, '#d7b077']]) {
    let value = Number(rows[0].close); const values = [];
    rows.forEach((row, index) => { if(index) value=Number(row.close)*2/(period+1)+value*(1-2/(period+1)); values.push(value); });
    const visible = values.slice(-candles.length); ctx.strokeStyle=color;ctx.beginPath();
    visible.forEach((v,i)=> {const x=10+i*width+width/2;if(i===0)ctx.moveTo(x,y(v));else ctx.lineTo(x,y(v));});ctx.stroke();
  }
  ctx.fillStyle = '#a6b6ca';
  ctx.fillText(new Date(candles[0].open_time).toISOString(), 10, 290);
  ctx.fillText(new Date(candles.at(-1).open_time).toISOString(), 590, 290);
}

async function refreshMarket() {
  const market = await api('/api/market');
  document.getElementById('market-status').textContent = `${market.connected ? 'LIVE' : 'KHÔNG SẴN SÀNG / STALE'} · ${market.state} · ${market.error || market.source}`;
  const prices = document.getElementById('prices'); prices.replaceChildren();
  const selector = document.getElementById('symbol');
  if (!selector.options.length) market.symbols.forEach(row => {
    const option = document.createElement('option'); option.value = option.textContent = row.symbol; selector.append(option);
  });
  market.symbols.forEach(row => {
    const p = document.createElement('p');
    p.textContent = `${row.symbol}: ${row.price ?? '—'} USDT · ${row.fresh && market.connected ? 'LIVE' : 'STALE / chờ dữ liệu'}`;
    prices.append(p);
  });
  const selected = market.symbols.find(row => row.symbol === selector.value);
  document.getElementById('book').textContent = selected?.book ? `Order book top 20 (không phải full depth)\n${JSON.stringify(selected.book, null, 2)}` : 'Chưa có order book';
  document.getElementById('trades').textContent = `Giao dịch tổng hợp gần nhất\n${JSON.stringify(selected?.trades.slice(-5) ?? [], null, 2)}`;
  const candles = await api(`/api/candles/${encodeURIComponent(selector.value)}?interval=${document.getElementById('interval').value}`);
  drawCandles(candles.candles);
}
for (const id of ['symbol', 'interval']) document.getElementById(id).addEventListener('change', () => refreshMarket().catch(error => {
  document.getElementById('market-status').textContent = `Mất kết nối: ${error.message}`;
}));
for (const [id, endpoint] of [['diagnostic', '/api/diagnostics'], ['halt', '/api/kill-switch']]) {
  document.getElementById(id).addEventListener('click', async event => {
    event.target.disabled = true;
    try { await api(endpoint, 'POST'); await refresh(); document.getElementById('feedback').textContent = 'Đã hoàn tất.'; }
    catch (error) { document.getElementById('feedback').textContent = error.message; }
    finally { event.target.disabled = false; }
  });
}
async function poll() {
  try { await refresh(); }
  catch (error) {
    document.getElementById('research-status').textContent='Không kết nối được backend; chưa thể xác nhận trạng thái Agent.';
    document.getElementById('feedback').textContent = `Mất kết nối: ${error.message}`;
    document.getElementById('market-status').textContent = 'OFFLINE — không thể xác minh độ mới dữ liệu';
    document.getElementById('prices').replaceChildren();
  }
  setTimeout(poll, 2000);
}
poll();
