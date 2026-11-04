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
    for agent in coordinator.registry():
        task = task_view(agent['latest_task'])
        agents.append({key: agent[key] for key in ('id','name','department','status')} | {
            'purpose': PURPOSES[agent['id']], 'task': task,
            'history': [task_view(t) for t in rows if t['agent_id']==agent['id']][:3]})
    source = market.snapshot()
    return {'as_of': current.isoformat(), 'agents': agents, 'activity': [task_view(t) for t in rows[:20]],
            'pending_tasks':pending, 'finished_today':finished,
            'market': {'connected': source['connected'], 'state': source['state'], 'symbols': [
                {k: row.get(k) for k in ('symbol','price','fresh')} for row in source.get('symbols',[])]},
            'research': coordinator.research_status(), 'observer_mode':settings.observer_mode,
            'ollama': {'enabled':settings.ollama_enabled,'last_request_ok':coordinator.summary.available},
            'new_positions_allowed':False if settings.observer_mode else None}
