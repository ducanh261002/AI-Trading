"""Persistent mission board, measured watch observations and artifact handoffs."""
import asyncio
import json
import time
from uuid import uuid4

import httpx

from app.db import now
from app.trading.indicators import series


class LiveDesk:
    def __init__(self, coordinator):
        self.owner = coordinator
        self.observations = {}
        self.checked_at = None
        self.next_check = 0
        self.next_model_probe = 0
        self.next_reflection = 0
        self.model_job = None
        self.thinking = None
        self.model_state = 'Chưa kết nối mô hình AI; công cụ Python vẫn hoạt động.'
        self.model_ready = False
        self.reflection_role = 0

    def initialize(self):
        with self.owner.database.connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS agent_missions(
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, objective TEXT NOT NULL,
                    symbols TEXT NOT NULL, interval TEXT NOT NULL, active INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_improvements(
                    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL,
                    interval TEXT NOT NULL, status TEXT NOT NULL, conclusion TEXT NOT NULL,
                    comparisons TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    sender TEXT NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL,
                    body TEXT NOT NULL, run_id TEXT, task_id TEXT, model TEXT,
                    dedupe TEXT UNIQUE);
            ''')
            con.execute('CREATE TABLE IF NOT EXISTS agent_live_config(id INTEGER PRIMARY KEY CHECK(id=1), model_enabled INTEGER NOT NULL, model TEXT NOT NULL)')
            configuration=con.execute('SELECT * FROM agent_live_config WHERE id=1').fetchone()
            if configuration:
                self.owner.settings.ollama_enabled=bool(configuration['model_enabled'])
                self.owner.settings.ollama_model=configuration['model']
            if not con.execute('SELECT 1 FROM agent_missions LIMIT 1').fetchone():
                con.execute('INSERT INTO agent_missions VALUES(?,?,?,?,?,1)',(
                    str(uuid4()),now(),'Theo dõi thị trường, kiểm thử ba chiến lược và báo cáo rủi ro; không mở lệnh.',
                    json.dumps(self.owner.market.symbols),self.owner.research_interval))
        self.message('ceo','team','system','Bộ điều phối đã khởi động. Theo dõi dữ liệu thường xuyên; nghiên cứu nến mới và báo cáo từ công cụ thực.')

    def message(self, sender, recipient, kind, body, run_id=None, task_id=None, model=None, dedupe=None):
        with self.owner.database.connect() as con:
            con.execute('''INSERT OR IGNORE INTO agent_messages
                (created_at,sender,recipient,kind,body,run_id,task_id,model,dedupe) VALUES(?,?,?,?,?,?,?,?,?)''',
                (now(),sender,recipient,kind,body[:2500],run_id,task_id,model,dedupe))
            con.execute('DELETE FROM agent_messages WHERE id < (SELECT COALESCE(MAX(id),0)-2000 FROM agent_messages)')

    def missions(self):
        with self.owner.database.connect() as con:
            rows=[dict(r) for r in con.execute('SELECT * FROM agent_missions ORDER BY created_at DESC LIMIT 12')]
        for row in rows: row['symbols']=json.loads(row['symbols'])
        return rows

    def symbols(self):
        mission=next((r for r in self.missions() if r['active']),None)
        return [s for s in (mission['symbols'] if mission else self.owner.market.symbols) if s in self.owner.market.symbols]

    def assign(self, objective, symbols, interval):
        mission_id=str(uuid4())
        with self.owner.database.connect() as con:
            con.execute('UPDATE agent_missions SET active=0')
            con.execute('INSERT INTO agent_missions VALUES(?,?,?,?,?,1)',(mission_id,now(),objective,json.dumps(symbols),interval))
        self.message('user','ceo','assignment',objective)
        self.message('ceo','team','assignment',f'Đã nhận chỉ thị cho {", ".join(symbols)} / {interval}. Phạm vi: nghiên cứu, backtest và báo cáo; không mở vị thế.')
        self.owner.configure_research(True,interval)
        # A deliberate assignment is a new analysis request, even on unchanged data;
        # the backtest engine still reuses its dataset cache transparently.
        submitted=[]
        for symbol in symbols:
            if not self.owner.store.active(symbol,interval):
                try:submitted.append(self.owner.submit(symbol,interval,'mission-'+mission_id+'-'+symbol))
                except OverflowError:pass  # Scheduler will retry the configured mission.
        self.next_check=0
        return {'mission_id':mission_id,'runs':submitted,'scope':'analysis_only','accepted':True}

    def queued(self, run_id, symbol, interval):
        self.message('ceo','team','assignment',f'Giao 16 nhiệm vụ: {symbol} / {interval}. Market → Technical/Data → Backtest → Strategy/Risk → Report → CEO.',run_id=run_id,dedupe='queued-'+run_id)

    def received(self, task):
        run=self.owner.store.run(task['run_id'])
        ids=json.loads(task.get('depends_on') or '[]') if isinstance(task.get('depends_on'),str) else task.get('depends_on') or []
        for dependency in run['tasks']:
            if dependency['id'] in ids:
                self.message(task['agent_id'],dependency['agent_id'],'receipt',
                    'Đã nhận và đọc kết quả đầu vào của nhiệm vụ '+dependency['id']+'.',
                    task['run_id'],task['id'],dedupe='receipt-'+task['id']+'-'+dependency['id'])

    def finished(self, task, output):
        from app.observatory import task_view
        full=self.owner.store.run(task['run_id'])
        raw=next(t for t in full['tasks'] if t['id']==task['id'])
        summary=task_view(raw)['activity']
        self.message(task['agent_id'],'user' if task['agent_id']=='ceo' else 'ceo','result',summary,task['run_id'],task['id'],dedupe='result-'+task['id']+'-'+output['status'])
        for target in full['tasks']:
            if task['id'] in (target['depends_on'] or []):
                self.message(task['agent_id'],target['agent_id'],'handoff',summary+' · Bàn giao bằng chứng '+task['id']+'.',task['run_id'],task['id'],dedupe='handoff-'+task['id']+'-'+target['id'])
        if task['agent_id']=='report':
            brief=output['result'].get('brief') or {}
            if brief:
                status='candidate' if brief.get('sample_candles',0)>=500 and any((r.get('test_trades') or 0)>=30 and (r.get('test_return_percent') or 0)>0 for r in brief.get('comparisons',[])) and not any(t['status']=='Error' for t in full['tasks']) else 'needs_validation'
                with self.owner.database.connect() as con:
                    con.execute('INSERT OR IGNORE INTO agent_improvements VALUES(?,?,?,?,?,?,?)',
                        (task['run_id'],now(),full['symbol'],full['interval'],status,brief['conclusion'],json.dumps(brief['comparisons'])))
                    con.execute('DELETE FROM agent_improvements WHERE rowid NOT IN (SELECT rowid FROM agent_improvements ORDER BY created_at DESC LIMIT 1000)')
                self.message('backtest','strategy','review','Đã lưu đánh giá chiến lược: '+brief['conclusion']+' Chưa tự thay đổi chiến lược đang chạy.',task['run_id'],task['id'],dedupe='review-'+task['run_id'])
        self.next_check=0

    def observe(self):
        owner=self.owner
        snapshot=owner.market.snapshot()
        symbols=self.symbols()
        interval=owner.research_interval
        reports=owner.research_status()['reports']
        portfolio=owner.trading.paper.portfolio()
        chunks=[]; technical=[]; data=[]; tests=[]; proposals=[]
        for symbol in symbols:
            item=next(r for r in snapshot['symbols'] if r['symbol']==symbol)
            fresh=bool(snapshot['connected'] and item.get('fresh'))
            chunks.append(f"{symbol}: {item.get('price') or 'chưa có giá'} USDT ({'LIVE' if fresh else 'chưa đủ mới'})")
            rows=owner.market.store.read(symbol,interval)
            data.append(f'{symbol}: {len(rows)} nến đóng / {interval}')
            if len(rows)>=60:
                metrics=series(rows)
                technical.append(f"{symbol}: RSI {metrics['rsi']:.2f}, EMA9 {metrics['ema9']:.2f}, MACD {metrics['macd']:.2f}")
            else: technical.append(f'{symbol}: chưa đủ 60 nến cho bộ chỉ báo')
            report=next((r for r in reports if r['symbol']==symbol and r['interval']==interval),None)
            tests.append(f"{symbol}: {len(report['comparisons'])} chiến lược đã kiểm thử" if report else f'{symbol}: chờ kiểm thử đầu tiên')
            proposal=owner.trading.proposal(symbol,interval)
            proposals.append(f"{symbol}: {proposal.get('signal','HOLD')}")
        descriptions={
            'market':' · '.join(chunks), 'technical':' · '.join(technical), 'data':' · '.join(data),
            'news':'Theo dõi kết quả RSS theo chu kỳ nghiên cứu; '+('chưa có nguồn được cấu hình.' if not owner.settings.news_feed_url else 'nguồn đã cấu hình, không suy đoán tin chưa đọc.'),
            'backtest':' · '.join(tests)+'. Chạy lại khi snapshot nến đổi; dùng cache khi dữ liệu không đổi.',
            'strategy':'So sánh điều kiện ba chiến lược; '+' · '.join(proposals),
            'signal':' · '.join(proposals),
            'risk':f"Đã đọc tài khoản: drawdown {portfolio['drawdown']*100:.2f}%, PnL ngày {portfolio['daily_pnl']:.2f} USDT; Kill Switch {'bật' if owner.database.halted() else 'tắt'}. Không mở lệnh.",
            'execution':'Đang giám sát khóa mở vị thế. Chỉ phân tích; không có quyền gửi lệnh thật.',
            'portfolio':f"Equity mô phỏng {portfolio['equity']:.2f} USDT; {len(portfolio['positions'])} vị thế đang mở.",
            'accounting':f"Đã kiểm tra {len(owner.trading.paper.ledger())} bút toán gần nhất trong sổ mô phỏng.",
            'performance':f"Đang theo dõi PnL mô phỏng {portfolio['daily_pnl']:.2f} USDT; chưa coi kết quả backtest là lợi nhuận thực.",
            'monitor':f"Database {'sẵn sàng' if owner.database.health() else 'lỗi'}; thị trường {'LIVE' if snapshot['connected'] else 'đang mất kết nối / stale'}.",
            'security':f"Cấu hình {owner.settings.mode}; observer={owner.settings.observer_mode}; PAPER tự động={'bật' if owner.trading.autopilot_enabled else 'tắt'}. Lệnh thật bị khóa; không phải kiểm toán bảo mật toàn diện.",
            'report':'Đã đọc '+str(len(reports))+' báo cáo nghiên cứu gần nhất. '+' · '.join(proposals),
            'ceo':'Đang điều phối theo chỉ thị hiện tại. '+('Theo dõi LIVE và chờ nến mới để nghiên cứu chuyên sâu.' if snapshot['connected'] else 'Đang yêu cầu bộ phận dữ liệu chờ kết nối; không tạo kết quả giả.'),
        }
        self.checked_at=now()
        self.observations={key:{'agent_id':key,'checked_at':self.checked_at,'summary':value,'source':'python'} for key,value in descriptions.items()}
        # These are measured watch reports, not simulated LLM conversations.
        stamp=int(time.time()//owner.settings.live_watch_seconds)
        for sender,recipient in [('market','technical'),('technical','strategy'),('risk','ceo'),('report','ceo')]:
            self.message(sender,recipient,'observation',descriptions[sender],dedupe=f'watch-{stamp}-{sender}')

    def save_model(self):
        with self.owner.database.connect() as con:
            con.execute('INSERT OR REPLACE INTO agent_live_config VALUES(1,?,?)',(int(self.owner.settings.ollama_enabled),self.owner.settings.ollama_model))

    async def discover_model(self):
        if not self.owner.settings.ollama_enabled:
            self.model_ready=False
            self.model_state='Chưa bật mô hình AI. Bấm Kết nối AI để kiểm tra Ollama trên máy.'
            return
        try:
            async with httpx.AsyncClient(base_url=self.owner.settings.ollama_url,trust_env=False,timeout=2,follow_redirects=False) as client:
                response=await client.get('/api/tags')
                response.raise_for_status()
                models=response.json().get('models',[])
            names=[m['name'] for m in models if isinstance(m.get('name'),str)]
            selected=self.owner.settings.ollama_model
            if selected not in names and selected+':latest' not in names:
                raise ValueError('Configured model missing')
            self.model_ready=True
            self.model_state='Đã tìm thấy '+selected+' trên Ollama; suy luận được ghi riêng là AI.'
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            self.model_ready=False
            self.model_state='Chưa kết nối được Ollama hoặc chưa có model '+self.owner.settings.ollama_model+'. Công cụ Python vẫn hoạt động.'

    async def reflect(self):
        roles=['market','technical','strategy','risk','report','ceo']
        role=roles[self.reflection_role%len(roles)];self.reflection_role+=1
        self.thinking=role
        model=self.owner.settings.ollama_model
        try:
            # Only allowlisted measurements and prior advisory text, never commands,
            # keys, news, user instructions or arbitrary tool outputs go to a model.
            previous=[m for m in self.snapshot()['messages'] if m['kind']=='ai'][:2]
            result=await self.owner.summary.discuss(role,self.observations.get(role,{}).get('summary','Chưa có dữ liệu'),
                [{'sender':m['sender'],'text':m['body']} for m in previous])
            if result['used']:
                self.message(role,'ceo' if role!='ceo' else 'user','ai',result['text'],model=model)
            else:
                self.model_ready=False;self.model_state=result['reason']
        finally:self.thinking=None

    async def tick(self):
        if self.model_job and self.model_job.done():
            try:self.model_job.result()
            except Exception:self.model_ready=False;self.model_state='Lượt suy luận lỗi; giữ kết quả công cụ.'
            self.model_job=None
        if not self.owner.research_enabled:return
        current=time.monotonic()
        if current>=self.next_check:
            self.observe();self.next_check=current+self.owner.settings.live_watch_seconds
        if current>=self.next_model_probe and self.model_job is None:
            await self.discover_model();self.next_model_probe=current+60
        if self.model_ready and current>=self.next_reflection and self.model_job is None:
            self.model_job=asyncio.create_task(self.reflect(),name='agent-discussion')
            self.next_reflection=current+30

    async def stop(self):
        if self.model_job:
            self.model_job.cancel()
            try:await self.model_job
            except asyncio.CancelledError:pass
            self.model_job=None
        self.thinking=None

    def snapshot(self):
        with self.owner.database.connect() as con:
            messages=[dict(r) for r in con.execute('SELECT id,created_at,sender,recipient,kind,body,run_id,task_id,model FROM agent_messages ORDER BY id DESC LIMIT 80')]
            improvements=[dict(r) for r in con.execute('SELECT * FROM agent_improvements ORDER BY created_at DESC LIMIT 12')]
        for item in improvements:item['comparisons']=json.loads(item['comparisons'])
        active=self.owner.running and self.owner.research_enabled
        return {'active':active,'watch_seconds':self.owner.settings.live_watch_seconds,
            'checked_at':self.checked_at,'observations':list(self.observations.values()),
            'autopilot':self.owner.trading.autopilot_status(),'improvements':improvements,
            'missions':self.missions(),'messages':messages,'thinking':self.thinking,
            'model_ready':self.model_ready,'model_message':self.model_state,
            'model_enabled':self.owner.settings.ollama_enabled,'model':self.owner.settings.ollama_model}
