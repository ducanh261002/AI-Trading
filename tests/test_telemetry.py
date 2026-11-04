import time
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from tests.test_research import live_fixture
from tests.test_trading import FILTERS,proposal


def config(tmp_path):
    return Settings(database_path=tmp_path/'telemetry.db',market_enabled=False,_env_file=None)


def test_diagnostics_explain_hold_and_disabled_without_forcing_orders(tmp_path):
    app=create_app(config(tmp_path))
    with TestClient(app) as client:
        live_fixture(app)
        result=client.get('/api/trading/telemetry').json()
        assert result['account']['mode']=='PAPER'
        assert not result['account']['exchange_account_connected']
        for row in result['diagnostics']['checks']:
            assert row['signal']=='HOLD' and len(row['strategies'])==3
            assert 'No actionable signal' in row['blockers']
            assert 'PAPER autopilot not started' in row['blockers']
            assert 'Missing exchange filters' in row['blockers']
            assert not row['ready_for_next_check']
        assert result['account']['positions']==[]


def test_pnl_uses_actual_ledger_fees_and_marks_then_survives_restart(tmp_path):
    settings=config(tmp_path);app=create_app(settings)
    with TestClient(app) as client:
        price={'value':100}
        app.state.market.snapshot=lambda:{'connected':True,'state':'streaming','symbols':[{'symbol':s,'price':str(price['value']),'fresh':True,'event_age_seconds':{},'metadata':{'filters':FILTERS}} for s in app.state.market.symbols]}
        app.state.trading.proposal=lambda symbol,interval:proposal()
        assert client.post('/api/autopilot',json={'enabled':True,'symbols':['BTCUSDT']}).status_code==200
        telemetry=app.state.trading.telemetry
        first=telemetry.account()
        assert first['fees']>0 and first['net_cash_pnl']==-first['fees']
        assert first['realized_gross']==0
        telemetry.sample(force=True)
        price['value']=102
        second=telemetry.account()
        p=second['positions'][0]
        assert abs(second['unrealized']-(102-p['entry'])*p['quantity'])<1e-8
        assert second['net_total_pnl']==second['net_cash_pnl']+second['unrealized']
        telemetry.sample(force=True)
        assert len(telemetry.history())>=2
        assert telemetry.history()[-1]['net_total_pnl']==second['net_total_pnl']
        client.post('/api/autopilot',json={'enabled':False})
    with TestClient(create_app(settings)) as client:
        result=client.get('/api/trading/telemetry').json()
        assert len(result['history'])>=2 and result['account']['fees']>0
        assert result['account']['fresh'] is False


def test_specialists_persist_and_have_only_readonly_measured_focus(tmp_path):
    settings=config(tmp_path);app=create_app(settings)
    with TestClient(app) as client:
        live_fixture(app)
        created=[]
        for i in range(4):
            response=client.post('/api/agents/specialists',json={'name':f'BTC chuyên gia {i}','focus':'technical','purpose':'Theo dõi chỉ báo kỹ thuật BTC và ETH'})
            assert response.status_code==201
            created.append(response.json()['id'])
            assert response.json()['capabilities']==['read_measurements','advisory_only']
        assert client.post('/api/agents/specialists',json={'name':'Agent số 5','focus':'risk','purpose':'Giám sát rủi ro'}).status_code==409
        assert client.post('/api/agents/specialists',json={'name':'Trader','focus':'execute_orders','purpose':'Mở lệnh tiền thật'}).status_code==422
        app.state.coordinator.live.observe()
        snapshot=client.get('/api/observatory').json()
        assert len(snapshot['agents'])==20
        for agent in snapshot['agents']:
            if agent['id'] in created:
                assert agent['status']=='Monitoring' and 'RSI' in agent['watch']['summary']
                assert agent['task'] is None
        assert client.post('/api/orders').status_code==403
    with TestClient(create_app(settings)) as client:
        assert len(client.get('/api/observatory').json()['agents'])==20
