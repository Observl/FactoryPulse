"""Share Cloudflare authentication with the local application, without local sessions."""
import os
import re
from urllib.parse import urlsplit

import httpx
from fastapi.responses import JSONResponse,Response


def install_auth_proxy(app,config):
    from .security import _principal
    service=config['auth_service_url'].rstrip('/')
    parsed=urlsplit(service)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise RuntimeError('认证服务必须为可信 HTTPS 根地址')

    @app.middleware('http')
    async def cloudflare_auth(request,call_next):
        path=request.url.path
        if not path.startswith('/api/') or request.method=='OPTIONS' or path=='/api/health':
            return await call_next(request)
        origin=request.headers.get('origin')
        allowed={x.rstrip('/') for x in os.environ.get('FACTORYPULSE_ALLOWED_ORIGINS','http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000').split(',')}
        if request.method not in {'GET','HEAD'} and origin and origin.rstrip('/') not in allowed:
            return JSONResponse({'detail':'此来源不能修改设备数据'},status_code=403)
        headers={'Cookie':request.headers.get('cookie',''),'Origin':origin or str(request.base_url).rstrip('/')}
        try:
            async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
                native_work=bool(re.match(r'^/api/(?:copilot/dify(?:/|$)|work-orders(?:/|$)|alerts/[^/]+/action$|maintenance-requests$|schedule/generate$|maintenance/(?:timeline|time-readiness)$|resources(?:/|$)|equipment/[^/]+/operations$|operations/resource-occupancy$)',path))
                if path.startswith('/api/auth/') or (native_work and request.method!='GET'):
                    headers['Content-Type']=request.headers.get('content-type','application/json')
                    upstream=await client.request(request.method,service+path+('?' + str(request.url.query) if request.url.query else ''),headers=headers,content=await request.body(),timeout=135 if path=="/api/copilot/dify/chat" else 20)
                    response=Response(upstream.content,status_code=upstream.status_code,headers={'Content-Type':upstream.headers.get('content-type','application/json'),'Cache-Control':'no-store'})
                    for cookie in upstream.headers.get_list('set-cookie'):
                        if request.url.scheme=='http' and request.url.hostname in {'localhost','127.0.0.1','::1'}:
                            cookie='; '.join('SameSite=Strict' if part.strip().lower()=='samesite=none' else part.strip() for part in cookie.split(';') if part.strip().lower() not in {'secure','partitioned'})
                        response.headers.append('set-cookie',cookie)
                    return response
                upstream=await client.get(service+'/api/auth/status',headers=headers)
                if upstream.status_code!=200:
                    return JSONResponse({'detail':'Cloudflare 账号服务暂不可用，请稍后重试'},status_code=503)
                user=upstream.json().get('user')
        except (httpx.HTTPError,ValueError):
            return JSONResponse({'detail':'无法连接 Cloudflare 账号服务，未使用离线登录'},status_code=503)
        if not user:return JSONResponse({'detail':'请先登录后再操作'},status_code=401)
        if path.startswith('/api/developer/') and user['role']!='developer':
            return JSONResponse({'detail':'此功能需要开发者权限'},status_code=403)
        if request.method not in {'GET','HEAD'} and not path.startswith(('/api/copilot/chat','/api/copilot/sessions')):
            transition=path.startswith('/api/work-orders/') and path.endswith('/transition')
            roles={'developer','admin','user'} if transition else {'developer','admin'}
            if user['role'] not in roles:return JSONResponse({'detail':'当前账号仅可查看，不能修改或审批维护任务'},status_code=403)
        token=_principal.set(user)
        try:
            from .data_sync import cached_business_response
            async def read_response():
                if native_work and request.method=='GET':
                    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
                        upstream=await client.get(service+path+('?' + str(request.url.query) if request.url.query else ''),headers=headers)
                    return Response(upstream.content,status_code=upstream.status_code,headers={'Content-Type':upstream.headers.get('content-type','application/json'),'Cache-Control':'no-store'})
                return await call_next(request)
            return await cached_business_response(request,read_response)
        finally:_principal.reset(token)
