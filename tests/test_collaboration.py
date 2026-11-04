import asyncio
import json
import time

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_research import live_fixture, wait_reports
from tests.test_trading import FILTERS, proposal


def config(tmp_path, **kwargs):
    return Settings(database_path=tmp_path/'collab.db',market_enabled=False,_env_file=None,**kwargs)


def test_periodic_watch_keeps_measuring_without_duplicate_backtests(tmp_path):
    app=create_app(config(tmp_path))
    with TestClient(app) as client:
        live_fixture(app)
        owner=app.state.coordinator
        owner.research_tick()
        wait_reports(client)
        owner.live.observe()
        initial=client.get('/api/observatory').json()
        run_count=len(owner.store.runs())
        first=initial['live']['checked_at']
        market=app.state.market
        original=market.snapshot
        def changed():
            result=original()
            result['symbols'][0]['price']='102.50'
            return result
        market.snapshot=changed
        time.sleep(.01)
        owner.live.observe();owner.research_tick()
        after=client.get('/api/observatory').json()
        assert len(owner.store.runs())==run_count
        assert after['live']['checked_at']>first
        assert '102.50' in next(r for r in after['live']['observations'] if r['agent_id']=='market')['summary']
        assert any(a['status']=='Monitoring' for a in after['agents'])
        assert not any(m['kind']=='ai' for m in after['live']['messages'])
        assert after['live']['improvements'] and all(r['status']=='needs_validation' for r in after['live']['improvements'])


def test_missions_and_dependency_receipts_are_real_and_persistent(tmp_path):
    settings=config(tmp_path)
    app=create_app(settings)
    with TestClient(app) as client:
        live_fixture(app)
        response=client.post('/api/missions',json={'objective':'Theo dõi BTC, so sánh ba chiến lược','symbols':['BTCUSDT']})
        assert response.status_code==202
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            snapshot=client.get('/api/observatory').json()
            run=snapshot['cycle']
            if run and run['finished_at']:break
            time.sleep(.02)
        messages=snapshot['live']['messages']
        assert any(m['kind']=='handoff' and m['sender']=='technical' and m['recipient']=='backtest' for m in messages)
        assert any(m['kind']=='receipt' and m['sender']=='backtest' and m['recipient']=='technical' for m in messages)
        raw=client.get('/api/agent-cycles/'+run['id']).json()
        tasks={t['agent_id']:t for t in raw['tasks']}
        assert tasks['technical']['id'] in tasks['backtest']['result']['input_evidence_ids']
        assert tasks['backtest']['id']==tasks['strategy']['result']['backtest_evidence']
        assert client.post('/api/missions',json={'objective':' ' * 12,'symbols':['BTCUSDT']}).status_code==422
        assert client.post('/api/missions',json={'objective':'Hãy theo dõi X','symbols':['UNCONFIGUREDUSDT']}).status_code==422
        assert client.post('/api/orders').status_code==403
    with TestClient(create_app(settings)) as client:
        live=client.get('/api/observatory').json()['live']
        assert next(m for m in live['missions'] if m['active'])['symbols']==['BTCUSDT']
        assert any(m['kind']=='assignment' and m['sender']=='user' for m in live['messages'])


def test_paper_autopilot_is_explicit_risk_checked_idempotent_and_killable(tmp_path):
    settings=config(tmp_path)
    app=create_app(settings)
    with TestClient(app) as client:
        assert client.get('/api/autopilot').json()['enabled'] is False
        assert client.post('/api/autopilot',json={'enabled':True,'symbols':['BTCUSDT']}).status_code==409
        market=app.state.market
        market.snapshot=lambda:{'connected':True,'state':'streaming','symbols':[{'symbol':'BTCUSDT','price':'100','fresh':True,'event_age_seconds':{},'metadata':{'filters':FILTERS}}]}
        app.state.trading.proposal=lambda symbol,interval:proposal()
        assert app.state.trading.paper.enter(proposal())['sent'] is False
        response=client.post('/api/autopilot',json={'enabled':True,'symbols':['BTCUSDT']})
        assert response.status_code==200 and response.json()['mode']=='PAPER'
        assert response.json()['results'][0]['sent'] is True
        assert response.json()['exchange_execution_available'] is False
        assert len(client.get('/api/portfolio').json()['positions'])==1
        app.state.trading.autopilot_tick()
        assert len(client.get('/api/portfolio').json()['positions'])==1
        assert client.post('/api/orders').status_code==403
        assert client.post('/api/kill-switch').status_code==200
        assert not client.get('/api/autopilot').json()['enabled']
        assert app.state.trading.paper.enter(proposal(),autopilot=True)['sent'] is False
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/autopilot').json()['enabled'] is False
        assert client.get('/api/status').json()['halted'] is True


def test_model_discussion_is_separate_advisory_and_cannot_enable_execution(tmp_path,monkeypatch):
    original=httpx.AsyncClient
    payloads=[]
    def handler(request):
        if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'qwen2.5:3b'}]})
        body=json.loads(request.content);payloads.append(body)
        assert 'tools' not in body
        return httpx.Response(200,json={'message':{'content':'Nhận xét từ mô hình. Không đủ bằng chứng; không mở lệnh.'}})
    def factory(**kwargs):return original(**kwargs,transport=httpx.MockTransport(handler))
    monkeypatch.setattr('app.orchestration.llm.httpx.AsyncClient',factory)
    app=create_app(config(tmp_path))
    with TestClient(app) as client:
        result=client.post('/api/agents/model',json={'enabled':True,'model':'qwen2.5:3b'})
        assert result.status_code==200 and result.json()['ready']
        owner=app.state.coordinator
        owner.live.observations={'market':{'summary':'BTCUSDT: 100 USDT'},'technical':{'summary':'RSI 50'}}
        asyncio.run(owner.live.reflect())
        asyncio.run(owner.live.reflect())
        messages=owner.live.snapshot()['messages']
        assert any(m['kind']=='ai' and m['model']=='qwen2.5:3b' for m in messages)
        second=json.loads(payloads[-1]['messages'][1]['content'])
        assert second['previous_advisory'][0]['sender']=='market'
        assert not app.state.trading.autopilot_enabled
        assert client.post('/api/orders').status_code==403
        assert owner.live.thinking is None


def test_retried_message_is_not_duplicated(tmp_path):
    app=create_app(config(tmp_path))
    with TestClient(app):
        live=app.state.coordinator.live
        for i in range(3):live.message('market','technical','observation','Đã kiểm tra',dedupe='same-observation')
        with app.state.database.connect() as con:
            assert con.execute("SELECT COUNT(*) FROM agent_messages WHERE dedupe='same-observation'").fetchone()[0]==1
