"""Public, read-only task summaries. Never return raw tool results or secrets."""
import json
from datetime import datetime, timedelta, timezone

PURPOSES = {
    'ceo': 'Điều phối công việc và tổng hợp kết luận', 'market': 'Theo dõi dữ liệu thị trường Binance',
    'technical': 'Tính chỉ báo trên nến đã đóng', 'news': 'Đọc nguồn tin có cấu hình',
    'data': 'Kiểm tra chất lượng và độ mới của nến', 'strategy': 'So sánh ba chiến lược',
    'signal': 'Tổng hợp tín hiệu LONG / SHORT / HOLD', 'risk': 'Kiểm tra giới hạn bằng Python',
    'execution': 'Ghi nhận kết quả, không mở vị thế', 'portfolio': 'Theo dõi danh mục mô phỏng',
    'performance': 'Đánh giá hiệu suất đã đo', 'accounting': 'Đối soát phí, funding và PnL',
    'monitor': 'Kiểm tra sức khỏe hệ thống', 'backtest': 'Tự kiểm thử cả ba chiến lược',
    'report': 'Tạo báo cáo từ bằng chứng nhiệm vụ', 'security': 'Kiểm tra cấu hình an toàn',
}
DONE = {'market':'Đã đọc dữ liệu thị trường', 'technical':'Đã tính chỉ báo', 'data':'Đã kiểm tra nến',
        'strategy':'Đã so sánh chiến lược', 'risk':'Đã kiểm tra giới hạn', 'execution':'Chế độ quan sát · không mở vị thế',
        'backtest':'Đã kiểm thử ba chiến lược', 'portfolio':'Đã đọc danh mục mô phỏng',
        'accounting':'Đã đối soát phí và PnL', 'performance':'Đã tính hiệu suất',
        'monitor':'Đã kiểm tra hệ thống', 'security':'Đã kiểm tra an toàn'}


def task_view(task):
    if not task:
        return None
    agent = task['agent_id']
    status = task['status']
    activity = PURPOSES.get(agent, 'Đang xử lý nhiệm vụ')
    if status == 'Pending':
        activity = 'Đang xếp hàng · chờ nhiệm vụ trước hoàn tất'
    elif status == 'Waiting':
        activity = 'Chờ nguồn tin tức' if agent == 'news' else 'Chờ dữ liệu hoặc điều kiện sẵn sàng'
    elif status == 'Error':
        activity = 'Nhiệm vụ lỗi · chờ kiểm tra lại'
    elif status == 'Cancelled':
        activity = 'Nhiệm vụ đã hủy'
    elif status == 'Completed':
        result = task.get('result') or {}
        if isinstance(result, str):
            result = json.loads(result)
        activity = DONE.get(agent, 'Đã hoàn tất nhiệm vụ')
        if agent == 'signal':
            activity = 'Tín hiệu: ' + str(result.get('signal', 'HOLD'))
        elif agent == 'report':
            activity = (result.get('brief') or {}).get('summary', 'Đã tổng hợp báo cáo')
        elif agent == 'ceo':
            activity = 'Đã tổng kết nhiệm vụ và báo cáo'
    target = task.get('input_json') or {}
    if isinstance(target, str):
        target = json.loads(target)
    return {key: task.get(key) for key in ('id','agent_id','status','created_at','started_at','finished_at','tool')} | {
        'activity': activity, 'symbol': target.get('symbol'), 'interval': target.get('interval')}


def snapshot(coordinator, market, settings):
    current = datetime.now(timezone.utc)
    day_start = current.astimezone(timezone(timedelta(hours=7))).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat()
    with coordinator.database.connect() as con:
        rows = [dict(row) for row in con.execute('SELECT * FROM tasks WHERE run_id IS NOT NULL ORDER BY created_at DESC,rowid DESC LIMIT 64')]
        pending = con.execute("SELECT COUNT(*) FROM tasks WHERE status='Pending' AND run_id IS NOT NULL").fetchone()[0]
        finished = con.execute("SELECT COUNT(*) FROM tasks WHERE finished_at>=? AND run_id IS NOT NULL",(day_start,)).fetchone()[0]
    agents = []
    registry = coordinator.registry()
    full_tasks = {row['id']:row for row in rows}
    missing = [a['latest_task']['id'] for a in registry if a['latest_task'] and a['latest_task']['id'] not in full_tasks]
    if missing:
        with coordinator.database.connect() as con:
            for row in con.execute('SELECT * FROM tasks WHERE id IN ('+','.join('?' for _ in missing)+')', missing):
                full_tasks[row['id']]=dict(row)
    for agent in registry:
        raw = full_tasks.get((agent['latest_task'] or {}).get('id'))
        task = task_view(raw)
        if task:
            task['evidence'] = evidence_view(raw)
            task['run_id'] = raw['run_id']
        agents.append({key: agent[key] for key in ('id','name','department','status')} | {
            'purpose': PURPOSES[agent['id']], 'task': task,
            'history': [task_view(t) for t in rows if t['agent_id']==agent['id']][:3]})
    runs = coordinator.store.runs()[:12]
    active = next((r for r in runs if r['status'] in {'Working','Pending'}), runs[0] if runs else None)
    cycle = cycle_view(coordinator, active['id']) if active else None
    source = market.snapshot()
    return {'as_of': current.isoformat(), 'agents': agents, 'activity': [task_view(t) for t in rows[:20]],
            'pending_tasks':pending, 'finished_today':finished,
            'market': {'connected': source['connected'], 'state': source['state'], 'symbols': [
                {k: row.get(k) for k in ('symbol','price','fresh')} for row in source.get('symbols',[])]},
            'research': coordinator.research_status(), 'observer_mode':settings.observer_mode,
            'ollama': {'enabled':settings.ollama_enabled,'last_request_ok':coordinator.summary.available},
            'cycle':cycle, 'cycles':[{k:r[k] for k in ('id','symbol','interval','status','created_at','finished_at')} for r in runs],
            'new_positions_allowed':False if settings.observer_mode else None}

# Explicit projections keep credentials, model prose and untrusted tool payloads out
# of the observer workbench. Values shown here are recorded outputs, not live claims.
EVIDENCE_FIELDS = {
    'market': [('symbol','Cặp'),('price','Giá ghi nhận'),('fresh','Dữ liệu mới')],
    'technical': [('candle_count','Nến đóng'),('sma20','SMA 20'),('last_close','Giá đóng'),('change_20_candles_percent','Thay đổi 20 nến (%)')],
    'data': [('candle_count','Nến đã kiểm tra'),('gaps','Khoảng trống'),('market_fresh','Dữ liệu mới')],
    'news': [('available','Có nguồn tin'),('fetched_at','Thời điểm lấy tin')],
    'strategy': [('actionable','Dữ liệu đủ mới'),('paper_only','Chỉ mô phỏng')],
    'signal': [('signal','Tín hiệu'),('strategy','Chiến lược'),('entry','Giá tham chiếu'),('stop','Dừng lỗ'),('take_profit','Mục tiêu'),('actionable','Có thể xem xét')],
    'risk': [('approved','Đạt kiểm tra risk'),('risk_budget','Ngân sách rủi ro'),('quantity','Khối lượng mô phỏng'),('leverage','Đòn bẩy')],
    'execution': [('sent','Đã mở lệnh'),('analysis_only','Chỉ phân tích'),('exchange_order_sent','Đã gửi lệnh thật')],
    'portfolio': [('balance','Số dư mô phỏng'),('equity','Equity mô phỏng'),('daily_pnl','PnL hôm nay'),('free_margin','Margin khả dụng')],
    'performance': [('paper_trades','Giao dịch mô phỏng')],
    'accounting': [('simulated','Dữ liệu mô phỏng'),('history_in_database','Đã lưu lịch sử')],
    'monitor': [('database','Database sẵn sàng'),('market_connected','Kết nối thị trường'),('halted','Kill Switch bật'),('execution_available','Gửi lệnh thật')],
    'security': [('mode','Chế độ'),('execution_available','Gửi lệnh thật'),('risk_mutation_api','API sửa giới hạn risk'),('llm_tool_calls','LLM tự gọi tool')],
}
INDICATORS = [('rsi','RSI 14'),('ema9','EMA 9'),('ema21','EMA 21'),('macd','MACD'),('atr','ATR'),('bb_upper','Bollinger trên'),('bb_lower','Bollinger dưới')]


def evidence_view(task):
    result = task.get('result') or {}
    if isinstance(result, str):
        result = json.loads(result)
    fields = EVIDENCE_FIELDS.get(task['agent_id'], [])
    metrics = [{'label': label, 'value': result[key]} for key,label in fields
               if key in result and isinstance(result[key], (str,int,float,bool))]
    if task['agent_id'] == 'technical':
        source = result.get('indicators') or {}
        metrics += [{'label': label, 'value': source[key]} for key,label in INDICATORS
                    if key in source and isinstance(source[key], (int,float))]
    comparisons = []
    if task['agent_id'] == 'backtest':
        from app.orchestration.brief import NAMES
        for row in result.get('results', [])[:3]:
            testing = (row.get('holdout') or {}).get('testing') or {}
            comparisons.append({'name': NAMES.get(row['strategy'],row['strategy']),
                'trades': row['trade_count'], 'pnl': row['final_equity']-row['initial_equity'],
                'return_percent': row['net_return']*100, 'drawdown_percent':row['max_drawdown']*100,
                'test_return_percent': testing.get('net_return',0)*100 if testing else None,
                'test_trades': testing.get('trade_count'), 'cached':bool(row.get('cached'))})
    if task['agent_id'] == 'strategy':
        metrics += [{'label': str(row.get('strategy','Chiến lược')), 'value':str(row.get('signal','HOLD'))}
                    for row in result.get('proposals',[])[:3]]
    if task['agent_id'] == 'accounting':
        metrics.append({'label':'Bút toán gần nhất','value':len(result.get('recent_entries',[]))})
    if task['agent_id'] == 'portfolio':
        metrics.append({'label':'Vị thế mô phỏng đang mở','value':len(result.get('positions',[]))})
    if task['agent_id'] in {'report','ceo'}:
        metrics += [{'label': state, 'value': count} for state,count in (result.get('task_counts') or {}).items() if isinstance(count,int)]
    return {'metrics':metrics, 'comparisons':comparisons, 'recorded_at':result.get('as_of'),
            'has_result':bool(result), 'scope':'Kết quả nhiệm vụ đã ghi nhận; không phải dữ liệu trực tiếp hiện tại.'}


def cycle_view(coordinator, run_id):
    run = coordinator.store.run(run_id)
    if run is None:
        return None
    tasks=[]
    for raw in run['tasks']:
        task=task_view(raw)
        task.update(dependencies=raw.get('depends_on') or [], evidence=evidence_view(raw),
                    attempts=raw.get('attempts',0))
        tasks.append(task)
    terminal={'Completed','Waiting','Error','Cancelled'}
    processed=sum(t['status'] in terminal for t in tasks)
    counts={status:sum(t['status']==status for t in tasks) for status in ('Completed','Waiting','Error','Pending','Working','Thinking','Cancelled')}
    return {key:run[key] for key in ('id','symbol','interval','status','created_at','finished_at')} | {
        'tasks':tasks, 'processed':processed, 'total':len(tasks), 'counts':counts,
        'progress_percent':round(processed/len(tasks)*100) if tasks else 0,
        'analysis_only':bool(run['analysis_only'])}
