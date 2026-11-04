"""Paper-account telemetry and transparent entry diagnostics; no fabricated fills."""
import time
from datetime import datetime,timedelta,timezone
from app.db import now


class TradingTelemetry:
    def __init__(self, service):
        self.service=service
        self.last_sample=0

    def initialize(self):
        with self.service.database.connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS paper_equity_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,
                equity REAL NOT NULL,cash REAL NOT NULL,unrealized REAL NOT NULL,
                realized_gross REAL NOT NULL,fees REAL NOT NULL,funding REAL NOT NULL,
                net_cash_pnl REAL NOT NULL,net_total_pnl REAL NOT NULL,fresh INTEGER NOT NULL)''')

    def totals(self):
        with self.service.database.connect() as con:
            rows={r['kind']:r['amount'] for r in con.execute('SELECT kind,SUM(amount) AS amount FROM paper_ledger GROUP BY kind')}
        gross=float(rows.get('REALIZED_PNL',0))
        fees=-float(rows.get('ENTRY_FEE',0))-float(rows.get('EXIT_FEE',0))
        funding=float(rows.get('FUNDING',0))
        return {'realized_gross':gross,'fees':max(0.0,fees),'funding':funding,'net_cash_pnl':sum(float(v) for v in rows.values())}

    def account(self):
        portfolio=self.service.paper.portfolio()
        market=self.service.market.snapshot()
        totals=self.totals()
        prices={r['symbol']:r for r in market['symbols']}
        fresh=bool(market['connected'] and all(prices.get(p['symbol'],{}).get('fresh') for p in portfolio['positions']))
        return {'as_of':now(),'mode':'PAPER','source':'paper_ledger_and_positions',
            'equity':portfolio['equity'],'cash':portfolio['balance'],'unrealized':portfolio['unrealized_pnl'],
            'daily_pnl':portfolio['daily_pnl'],'drawdown_percent':portfolio['drawdown']*100,
            'net_total_pnl':totals['net_cash_pnl']+portfolio['unrealized_pnl'],**totals,
            'positions':portfolio['positions'],'fresh':fresh,'market_connected':market['connected'],
            'exchange_account_connected':False}

    def sample(self,force=False):
        if not force and time.monotonic()-self.last_sample<5:return
        row=self.account()
        with self.service.database.connect() as con:
            con.execute('''INSERT INTO paper_equity_history(created_at,equity,cash,unrealized,realized_gross,fees,funding,net_cash_pnl,net_total_pnl,fresh)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',tuple(row[k] for k in ('as_of','equity','cash','unrealized','realized_gross','fees','funding','net_cash_pnl','net_total_pnl','fresh')))
            con.execute('DELETE FROM paper_equity_history WHERE created_at < ?',((datetime.now(timezone.utc)-timedelta(hours=24)).isoformat(),))
            con.execute('DELETE FROM paper_equity_history WHERE id < (SELECT COALESCE(MAX(id),0)-17280 FROM paper_equity_history)')
        self.last_sample=time.monotonic()

    def history(self):
        with self.service.database.connect() as con:
            rows=[dict(r) for r in con.execute('SELECT * FROM paper_equity_history ORDER BY id DESC LIMIT 17280')]
        rows.reverse()
        stride=max(1,(len(rows)+479)//480)
        points=rows[::stride]
        if rows and (not points or points[-1]['id']!=rows[-1]['id']):points.append(rows[-1])
        return points

    def diagnostics(self):
        service=self.service
        snapshot=service.market.snapshot()
        choices=service.autopilot_symbols
        checks=[]
        for symbol in choices:
            row=next((r for r in snapshot['symbols'] if r['symbol']==symbol),{})
            rows=service.market.store.read(symbol,service.autopilot_interval)
            proposal=service.proposal(symbol,service.autopilot_interval)
            risk=service.paper.review(proposal) if row else {'approved':False,'reasons':['Market data stale or incomplete']}
            mark=float(row['price']) if row.get('price') is not None else None
            entry=proposal.get('entry')
            deviation=abs(mark/float(entry)-1)*100 if mark is not None and entry else None
            reasons=list(risk.get('reasons',[]))
            if len(rows)<60:reasons.append('Need at least 60 closed candles')
            if not (row.get('metadata') or {}).get('filters'):reasons.append('Missing exchange filters')
            if not service.autopilot_enabled:reasons.insert(0,'PAPER autopilot not started')
            if deviation is not None and deviation>service.settings.max_entry_deviation*100:
                reasons.append('Price moved away from signal entry')
            previous=next((r for r in service.autopilot_results if r['symbol']==symbol),None)
            strategies=[{'strategy':p['strategy'],'signal':p['signal'],'reason':p.get('reason')} for p in proposal.get('proposals',[proposal]) if 'strategy' in p]
            checks.append({'symbol':symbol,'interval':service.autopilot_interval,'closed_candles':len(rows),
                'fresh':bool(snapshot['connected'] and row.get('fresh')),
                'exchange_filter_count':len((row.get('metadata') or {}).get('filters',[])),
                'signal':proposal.get('signal','HOLD'),'strategies':strategies,
                'mark_price':mark,'signal_entry':entry,'deviation_percent':deviation,
                'max_deviation_percent':service.settings.max_entry_deviation*100,
                'risk_approved':bool(risk.get('approved')),'blockers':list(dict.fromkeys(reasons)),
                'last_attempt':previous,'ready_for_next_check':not reasons})
        return {'as_of':now(),'mode':'PAPER','checks':checks,'exchange_execution_available':False}
