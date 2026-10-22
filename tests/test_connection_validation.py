import asyncio,threading
import httpx,pytest
from fastapi import HTTPException
from backend import main
from backend.connection_validation import AddressValidationPool
from tests.test_api import client

QUESTION='请查询CNC-001的运行历史并解释维修风险'
def configure(monkeypatch,pool):
    with main.connect() as connection:
        main.settings_set_many(connection,{'ai_base_url':'https://factorypulse-test.invalid/v1','ai_model':'test'})
    monkeypatch.setattr(main,'_api_key','synthetic-not-real')
    monkeypatch.setattr(main,'address_validation',pool)

def test_slow_address_lookup_does_not_block_health_requests(monkeypatch):
    pool=AddressValidationPool(workers=1,timeout=1);started=threading.Event();release=threading.Event()
    configure(monkeypatch,pool)
    def lookup(_):started.set();release.wait(2)
    async def agent(*args,**kwargs):return {'answer':'已读取测试证据','trace':[],'proposals':[]}
    monkeypatch.setattr(main,'require_public_https',lookup);monkeypatch.setattr(main,'run_agent',agent)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as app:
            task=asyncio.create_task(app.post('/api/copilot/chat',json={'question':QUESTION}))
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.005)
            assert started.is_set()
            health=await asyncio.wait_for(app.get('/api/health'),timeout=.3)
            assert health.status_code==200 and not task.done()
            release.set();assert (await task).status_code==200
    try:asyncio.run(exercise())
    finally:release.set();pool.close()

def test_timed_out_lookup_retains_slot_until_worker_really_finishes():
    pool=AddressValidationPool(workers=1,timeout=.02);release=threading.Event()
    try:
        with pytest.raises(HTTPException) as first:asyncio.run(pool.check('test',lambda _:release.wait(2)))
        assert first.value.status_code==504
        with pytest.raises(HTTPException) as second:asyncio.run(pool.check('test',lambda _:None))
        assert second.value.status_code==503
        release.set();pool.executor.submit(lambda:None).result(timeout=1)
        assert asyncio.run(pool.check('test',lambda _:'ready'))=='ready'
    finally:release.set();pool.close()

def test_late_address_result_cannot_start_an_agent_after_timeout(monkeypatch):
    pool=AddressValidationPool(workers=1,timeout=.02);release=threading.Event();calls=[]
    configure(monkeypatch,pool)
    monkeypatch.setattr(main,'require_public_https',lambda _:release.wait(2))
    async def agent(*args,**kwargs):calls.append(True);return {}
    monkeypatch.setattr(main,'run_agent',agent)
    try:
        response=client.post('/api/copilot/chat',json={'question':QUESTION})
        assert response.status_code==200 and response.json()['mode']=='unavailable'
        assert response.json()['proposals']==[]
    finally:release.set();pool.close()
    assert calls==[]

def test_private_saved_url_remains_blocked_after_async_validation(monkeypatch):
    pool=AddressValidationPool();configure(monkeypatch,pool)
    with main.connect() as connection:main.settings_set_many(connection,{'ai_base_url':'http://127.0.0.1:9'})
    try:
        result=client.post('/api/copilot/chat',json={'question':QUESTION})
        assert result.status_code==200 and result.json()['mode']=='unavailable'
        assert '公开 HTTPS' in result.json()['answer'] and result.json()['trace']==[]
    finally:pool.close()
