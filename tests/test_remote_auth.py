import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.remote_auth import install_auth_proxy
from backend.security import principal


def test_shared_cloudflare_sessions_and_permissions(monkeypatch):
    calls=[]
    def upstream(request):
        calls.append(request)
        if request.url.path.endswith('/login'):
            return httpx.Response(200,json={'success':True},headers={'set-cookie':'factorypulse_session=test; Path=/; HttpOnly; Secure; SameSite=None; Partitioned'})
        return httpx.Response(200,json={'user':{'user_id':'10001','role':'viewer','display_name':'Test'}})
    original=httpx.AsyncClient
    monkeypatch.setattr('backend.remote_auth.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(upstream),**kw))
    app=FastAPI();install_auth_proxy(app,{'auth_service_url':'https://trusted.example'})
    @app.get('/api/items')
    def items():return {'user':principal()}
    @app.post('/api/items')
    def update():return {'success':True}
    with TestClient(app,base_url='http://127.0.0.1:8000') as client:
        r=client.post('/api/auth/login',json={'username':'synthetic','password':'synthetic'},headers={'Origin':'http://127.0.0.1:8000'})
        assert r.status_code==200
        cookie=r.headers['set-cookie'];assert 'HttpOnly' in cookie and 'SameSite=Strict' in cookie and 'Secure' not in cookie and 'Partitioned' not in cookie
        assert client.get('/api/items').json()['user']['role']=='viewer'
        assert client.post('/api/items').status_code==403
        assert client.post('/api/auth/login',headers={'Origin':'https://evil.example'}).status_code==403
        assert all(r.url.host=='trusted.example' for r in calls)


def test_proxy_fails_closed_and_rejects_insecure_configuration(monkeypatch):
    with pytest.raises(RuntimeError):install_auth_proxy(FastAPI(),{'auth_service_url':'http://untrusted.example'})
    def failure(request):raise httpx.ConnectError('unavailable')
    original=httpx.AsyncClient
    monkeypatch.setattr('backend.remote_auth.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(failure),**kw))
    app=FastAPI();install_auth_proxy(app,{'auth_service_url':'https://trusted.example'})
    with TestClient(app) as client:
        assert client.get('/api/items').status_code==503
        assert principal() is None


def test_local_work_orders_use_same_worker_and_preserve_query_and_conflicts(monkeypatch):
    calls=[]
    def upstream(request):
        calls.append(request)
        if request.url.path=='/api/auth/status':
            return httpx.Response(200,json={'user':{'user_id':'10001','role':'admin','version':1}})
        return httpx.Response(409,json={'detail':'工单已变化'}) if request.method=='POST' else httpx.Response(200,json={'records':[]})
    original=httpx.AsyncClient
    monkeypatch.setattr('backend.remote_auth.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(upstream),**kw))
    app=FastAPI();install_auth_proxy(app,{'auth_service_url':'https://trusted.example'})
    with TestClient(app,base_url='http://127.0.0.1:8000') as client:
        assert client.get('/api/work-orders?include_deleted=true&dataset_version=fixture').json()=={'records':[]}
        assert calls[-1].url.query==b'include_deleted=true&dataset_version=fixture'
        assert client.post('/api/work-orders/test/approval',json={'decision':'approve'}).status_code==409
        assert calls[-1].url.path=='/api/work-orders/test/approval'
