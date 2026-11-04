import asyncio
import time
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from tests.test_research import live_fixture, wait_reports


def config(tmp_path, **kwargs):
    return Settings(database_path=tmp_path/'observer.db', market_enabled=False, _env_file=None, **kwargs)


def test_observer_default_3d_and_execution_guards(tmp_path):
    app=create_app(config(tmp_path, paper_auto=True))
    with TestClient(app) as client:
        html=client.get('/').text
        assert 'data-start-3d="true"' in html and 'arm-paper' not in html
        for path in ('/observer.js','/observer.css','/operator','/scene.js'):
            assert client.get(path).status_code==200
        state=client.get('/api/observatory').json()
        assert len(state['agents'])==16 and state['research']['enabled']
        assert state['new_positions_allowed'] is False
        assert client.get('/api/status').json()['paper_auto'] is False
        for endpoint,body in [('/api/paper/arm',{'confirmation':'ENABLE PAPER ONLY'}),('/api/paper/run',{})]:
            assert client.post(endpoint,json=body).status_code==409
        assert app.state.trading.paper.enter({})['sent'] is False
        result=asyncio.run(app.state.coordinator.tools.execution({'analysis_only':False}))
        assert result['result']['sent'] is False


def test_observer_upgrade_once_and_pause_persists(tmp_path):
    settings=config(tmp_path,observer_mode=False)
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/research').json()['enabled'] is False
    settings.observer_mode=True
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/research').json()['enabled'] is True
        assert client.post('/api/research',json={'enabled':False}).status_code==200
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/research').json()['enabled'] is False


def test_observer_autonomous_reports_without_manual_command(tmp_path):
    app=create_app(config(tmp_path))
    original=app.router.lifespan_context
    @asynccontextmanager
    async def seeded(application):
        async with original(application):
            live_fixture(application)
            yield
    app.router.lifespan_context=seeded
    with TestClient(app) as client:
        reports=wait_reports(client)['reports']
        assert len(reports)==2 and all(len(r['comparisons'])==3 for r in reports)
        state=client.get('/api/observatory').json()
        assert all(a['task'] for a in state['agents'])
        assert state['finished_today']>=32
        assert client.get('/api/portfolio').json()['positions']==[]
        assert 'input_json' not in str(state)


def test_observer_forces_readonly_even_explicit_operator_cycle(tmp_path):
    app=create_app(config(tmp_path))
    with TestClient(app) as client:
        response=client.post('/api/agent-cycles',json={'analysis_only':False})
        assert response.status_code==202
        run=client.get('/api/agent-cycles/'+response.json()['run_id']).json()
        assert run['analysis_only']
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            state=client.get('/api/observatory').json()
            if all(a['task'] and a['task']['finished_at'] for a in state['agents']):break
            time.sleep(.03)
        assert not any(a['status'] in ('Working','Thinking') for a in state['agents'])
        assert next(a for a in state['agents'] if a['id']=='news')['status']=='Waiting'
