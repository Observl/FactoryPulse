"""Optional account protection for a shared deployment; local demo remains explicit."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from contextvars import ContextVar
from datetime import datetime,timedelta,timezone

from fastapi import HTTPException,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field
from starlette.concurrency import run_in_threadpool

ONBOARDING_STEPS=5

_principal=ContextVar("factorypulse_principal",default=None)
COOKIE="factorypulse_session"
ROLES={"developer","admin","user","viewer"}
ROLE_NAMES={"developer":"开发者","admin":"管理员","user":"普通用户","viewer":"只读用户"}


def create_schema(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS auth_users (user_id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,role TEXT NOT NULL,staff_id TEXT,password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1)")
    connection.execute("CREATE TABLE IF NOT EXISTS auth_id_sequence (id INTEGER PRIMARY KEY CHECK(id=1),next_id INTEGER NOT NULL CHECK(next_id>=10001))")
    connection.execute("INSERT OR IGNORE INTO auth_id_sequence VALUES (1,10001)")
    connection.execute("CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires_at TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS auth_attempts (attempt_key TEXT PRIMARY KEY,attempts INTEGER NOT NULL,window_start TEXT NOT NULL)")

    connection.execute("CREATE TABLE IF NOT EXISTS auth_onboarding (user_id TEXT PRIMARY KEY REFERENCES auth_users(user_id) ON DELETE CASCADE,step INTEGER NOT NULL DEFAULT 0,completed_at TEXT)")


def principal(): return _principal.get()


def identity(fallback=""):
    user=principal()
    return user["display_name"] if user else fallback


def actor_metadata():
    user=principal()
    return {"actor_user_id":user["user_id"],"actor_role":user["role"]} if user else {"actor_mode":"local_single_operator"}


def require_roles(*roles):
    user=principal()
    if user and user["role"] not in roles: raise HTTPException(403,"当前账号没有执行此操作的权限")


def check_work_order_action(action,content):
    user=principal()
    if not user: return
    if user["role"] in {"developer","admin"}: return
    if user["role"]!="user" or action not in {"accept","start","pause","resume","finish"}: raise HTTPException(403,"此操作需要设备总管权限")
    if not user.get("staff_id") or str(user["staff_id"]) not in [str(value) for value in (content.get("staff_ids") or [content.get("staff_id")])]: raise HTTPException(403,"只能处理分配给自己的维修工单")


def password_hash(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password,encoded):
    try:
        if len(encoded)==64 and all(char in "0123456789abcdefABCDEF" for char in encoded):
            return hmac.compare_digest(password_hash(password),encoded.lower())
        method,rounds,salt,digest=encoded.split("$")
        if method!="pbkdf2_sha256": return False
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),int(rounds)).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError): return False


def validate_password(password):
    if len(password)<12 or len(password)>256 or not password.strip(): raise HTTPException(422,"密码需为12至256个字符，不能全部为空格")


def username(value):
    value=value.strip().casefold()
    if not 3<=len(value)<=60 or any(not (char.isalnum() or char in "-_.") for char in value): raise HTTPException(422,"账号名需为3至60个字母、数字、中文或 -_.")
    return value


class OnboardingProgress(BaseModel):
    step:int=Field(ge=0,le=ONBOARDING_STEPS,strict=True)


class LoginInput(BaseModel):
    username:str=Field(max_length=60)
    password:str=Field(max_length=256)


class BootstrapInput(LoginInput):
    display_name:str=Field(min_length=1,max_length=100)


class PasswordChange(BaseModel):
    current_password:str=Field(max_length=256)
    new_password:str=Field(max_length=256)


class ProfileUpdate(BaseModel):
    model_config={"extra":"forbid"}
    username:str=Field(min_length=1,max_length=60)
    display_name:str=Field(min_length=1,max_length=100)
    version:int=Field(ge=1)


class UserInput(BootstrapInput):
    username:str=Field(default="",max_length=60)
    role:str
    staff_id:str|int|None=None


class UserUpdate(BaseModel):
    display_name:str=Field(min_length=1,max_length=100)
    role:str
    staff_id:str|int|None=None
    active:bool
    version:int=Field(ge=1)


def install_auth(app,connect,lock):
    from .d1_identity import wrap_connection,configuration as identity_configuration
    from .cloud_mode import enabled as cloud_enabled,GUEST_ID
    connect=wrap_connection(connect)
    dummy=password_hash("timing-comparison-only-not-an-account")
    def required():
        with connect() as c:
            return bool(identity_configuration()) or cloud_enabled() or os.environ.get("FACTORYPULSE_TEST_ALLOW_ANONYMOUS")!="1" or os.environ.get("FACTORYPULSE_AUTH_REQUIRED")=="1" or bool(c.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone())

    def find_user(request):
        token=request.cookies.get(COOKIE)
        if not token: return None
        digest=hashlib.sha256(token.encode()).hexdigest()
        with connect() as c:
            row=c.execute("SELECT u.user_id,u.username,u.display_name,u.role,u.staff_id,u.version FROM auth_users u JOIN auth_sessions s ON s.user_id=u.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",(digest,datetime.now(timezone.utc).isoformat())).fetchone()
        return dict(row) if row else None

    def session(user,request):
        token=secrets.token_urlsafe(32);expires=datetime.now(timezone.utc)+timedelta(hours=8)
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current=c.execute("SELECT * FROM auth_users WHERE user_id=? AND active=1",(user["user_id"],)).fetchone()
            if not current: raise HTTPException(401,"账号状态已变化，请重新登录")
            if user.get("password_hash") and current["password_hash"]!=user["password_hash"]: raise HTTPException(401,"账号凭据已变化，请重新登录")
            user=dict(current)
            c.execute("DELETE FROM auth_sessions WHERE expires_at<=?",(datetime.now(timezone.utc).isoformat(),))
            c.execute("INSERT INTO auth_sessions VALUES (?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),user["user_id"],expires.isoformat()))
        response=JSONResponse({"success":True,"user":{key:user[key] for key in ("user_id","username","display_name","role","staff_id","version")}})
        response.set_cookie(COOKIE,token,httponly=True,samesite="strict",secure=request.url.scheme=="https",max_age=8*3600,path="/")
        return response

    def admin():
        if not principal() or principal()["role"]!="developer": raise HTTPException(403,"需要开发者账号")

    def validate_role(c,role,staff_id):
        if role not in ROLES:raise HTTPException(422,"请选择开发者、管理员、普通用户或只读用户")
        expected={"developer":0,"admin":-1}.get(role)
        if staff_id is None or str(staff_id).strip()=="":
            if expected is None:raise HTTPException(422,"普通用户和只读用户需填写正整数人员编号")
            return str(expected)
        try:
            text=str(staff_id).strip()
            number=int(text)
            if str(number)!=text:raise ValueError()
        except (ValueError,TypeError):raise HTTPException(422,"人员编号必须是整数") from None
        if expected is not None and number!=expected:raise HTTPException(422,"开发者人员编号为0，管理员人员编号为-1")
        if expected is None and number<=0:raise HTTPException(422,"公司人员编号必须为正整数")
        return str(number)

    def next_user_id(c):
        row=c.execute("SELECT next_id FROM auth_id_sequence WHERE id=1").fetchone()
        candidate=max(10001,int(row[0]))
        highest=c.execute("SELECT MAX(CAST(user_id AS INTEGER)) FROM auth_users WHERE user_id NOT GLOB '*[^0-9]*' AND user_id<>''").fetchone()[0]
        candidate=max(candidate,int(highest or 10000)+1)
        c.execute("UPDATE auth_id_sequence SET next_id=? WHERE id=1",(candidate+1,))
        return str(candidate)

    @app.middleware("http")
    async def protect(request:Request,call_next):
        if not request.url.path.startswith("/api/"): return await call_next(request)
        if request.method=="OPTIONS": return await call_next(request)
        origin=request.headers.get("origin")
        allowed=set(os.environ.get("FACTORYPULSE_ALLOWED_ORIGINS","http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000").split(","))
        if request.method not in {"GET","HEAD"} and origin and origin.rstrip("/") not in allowed: return JSONResponse({"detail":"此来源不能修改本地设备数据"},status_code=403)
        try:user=await run_in_threadpool(find_user,request)
        except HTTPException as exc:return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
        token=_principal.set(user)
        try:
            public=request.url.path in {"/api/health","/api/auth/status","/api/auth/login","/api/auth/bootstrap","/api/auth/logout","/api/auth/guest"}
            if not public and await run_in_threadpool(required):
                if not user: return JSONResponse({"detail":"请先登录后再操作"},status_code=401)
                path=request.url.path
                if path.startswith(("/api/developer/","/api/auth/users")) and user["role"]!="developer": return JSONResponse({"detail":"此功能需要开发者权限"},status_code=403)
                if request.method not in {"GET","HEAD"} and not path.startswith(("/api/auth/","/api/copilot/chat","/api/copilot/sessions")):
                    transition=path.startswith("/api/work-orders/") and path.endswith("/transition")
                    allowed_roles={"developer","admin","user"} if transition else {"developer","admin"}
                    if user["role"] not in allowed_roles: return JSONResponse({"detail":"当前账号仅可查看，不能修改或审批维护任务"},status_code=403)
            return await call_next(request)
        except HTTPException as exc:return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
        finally: _principal.reset(token)

    @app.get("/api/auth/status")
    def status():
        with connect() as c: exists=bool(c.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone())
        user=principal()
        onboarding=None
        if user:
            with connect() as c:
                row=c.execute("SELECT step,completed_at FROM auth_onboarding WHERE user_id=?",(user["user_id"],)).fetchone()
            onboarding={"step":row["step"] if row else 0,"completed_at":row["completed_at"] if row else None,"total_steps":ONBOARDING_STEPS}
        with connect() as c:guest_exists=c.execute("SELECT 1 FROM auth_users WHERE user_id=? AND role='viewer' AND active=1",(GUEST_ID,)).fetchone() if GUEST_ID else None
        return {"required":required(),"setup_needed":not exists,"mode":"accounts" if required() else "local_single_operator","guest_available":bool(GUEST_ID) and bool(guest_exists),"identity_provider":"cloudflare_d1" if identity_configuration() else "sqlite","user":user,"onboarding":onboarding}

    @app.post('/api/auth/guest')
    def guest_login(request:Request):
        if not identity_configuration() and not cloud_enabled():raise HTTPException(404,'未配置集中访客账号')
        with connect() as c:
            row=c.execute("SELECT * FROM auth_users WHERE user_id=? AND role='viewer' AND active=1",(GUEST_ID,)).fetchone()
        if not row:raise HTTPException(503,'访客账号尚未配置')
        if principal() and principal()['user_id']==GUEST_ID:return {"success":True}
        return session(dict(row),request)

    @app.post("/api/auth/onboarding")
    def onboarding_progress(payload:OnboardingProgress):
        user=principal()
        if not user: raise HTTPException(401,"请先登录后完成教程")
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=c.execute("SELECT step,completed_at FROM auth_onboarding WHERE user_id=?",(user["user_id"],)).fetchone()
            step=old["step"] if old else 0
            if payload.step>step+1: raise HTTPException(409,"请按顺序完成新手教程")
            target=max(step,payload.step)
            completed=old["completed_at"] if old else None
            if target==ONBOARDING_STEPS and not completed:
                completed=datetime.now(timezone.utc).isoformat()
                c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("onboarding_completed",user["user_id"],json.dumps(actor_metadata(),ensure_ascii=False),completed))
            c.execute("INSERT INTO auth_onboarding(user_id,step,completed_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET step=excluded.step,completed_at=excluded.completed_at",(user["user_id"],target,completed))
        return {"step":target,"completed_at":completed,"total_steps":ONBOARDING_STEPS}

    @app.post("/api/auth/bootstrap")
    def bootstrap(payload:BootstrapInput,request:Request):
        if cloud_enabled() or identity_configuration():raise HTTPException(403,'集中账号中心需由部署管理员初始化')
        if not request.client or request.client.host not in {"127.0.0.1","::1","localhost"}: raise HTTPException(403,"首次管理员必须在服务所在电脑上初始化")
        name=username(payload.username);validate_password(payload.password)
        if not payload.display_name.strip(): raise HTTPException(422,"请填写管理员姓名")
        encoded=password_hash(payload.password)
        user={"user_id":"","username":name,"display_name":payload.display_name.strip(),"role":"developer","staff_id":"0","version":1}
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone(): raise HTTPException(409,"管理员已初始化，请直接登录")
            user["user_id"]=next_user_id(c)
            c.execute("INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)",(user["user_id"],name,user["display_name"],"developer","0",encoded))
            c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("auth_initialized",user["user_id"],json.dumps({"username":name}),datetime.now(timezone.utc).isoformat()))
        return session(user,request)

    @app.post("/api/auth/login")
    def login(payload:LoginInput,request:Request):
        name=payload.username.strip().casefold();now=datetime.now(timezone.utc)
        attempt=hashlib.sha256((name+"/"+(request.client.host if request.client else "unknown")).encode()).hexdigest()
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            previous=c.execute("SELECT * FROM auth_attempts WHERE attempt_key=?",(attempt,)).fetchone()
            recent=previous and datetime.fromisoformat(previous["window_start"])>now-timedelta(minutes=10)
            if recent and previous["attempts"]>=5: raise HTTPException(429,"尝试次数过多，请10分钟后重试")
            c.execute("INSERT OR REPLACE INTO auth_attempts VALUES (?,?,?)",(attempt,previous["attempts"]+1 if recent else 1,previous["window_start"] if recent else now.isoformat()))
            row=c.execute("SELECT * FROM auth_users WHERE user_id=? OR username=? ORDER BY CASE WHEN user_id=? THEN 0 ELSE 1 END LIMIT 1",(name,name,name)).fetchone()
        valid=verify_password(payload.password,row["password_hash"] if row else dummy)
        if not row or not row["active"] or not valid: raise HTTPException(401,"账号或密码不正确")
        with lock,connect() as c: c.execute("DELETE FROM auth_attempts WHERE attempt_key=?",(attempt,))
        return session(dict(row),request)

    @app.post("/api/auth/logout")
    def logout(request:Request):
        token=request.cookies.get(COOKIE)
        if token:
            with lock,connect() as c: c.execute("DELETE FROM auth_sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),))
        response=JSONResponse({"success":True});response.delete_cookie(COOKIE,path="/");return response

    @app.post("/api/auth/password")
    def change_password(payload:PasswordChange):
        user=principal()
        if not user: raise HTTPException(401,"请先登录后修改密码")
        if user['user_id']==GUEST_ID and user['role']=='viewer':raise HTTPException(403,'共享访客不能修改密码')
        validate_password(payload.new_password)
        if payload.current_password==payload.new_password: raise HTTPException(422,"新密码不能与当前密码相同")
        now=datetime.now(timezone.utc)
        attempt="password-change/"+user["user_id"]
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            previous=c.execute("SELECT * FROM auth_attempts WHERE attempt_key=?",(attempt,)).fetchone()
            recent=previous and datetime.fromisoformat(previous["window_start"])>now-timedelta(minutes=10)
            if recent and previous["attempts"]>=5: raise HTTPException(429,"尝试次数过多，请10分钟后重试")
            c.execute("INSERT OR REPLACE INTO auth_attempts VALUES (?,?,?)",(attempt,previous["attempts"]+1 if recent else 1,previous["window_start"] if recent else now.isoformat()))
            old=c.execute("SELECT password_hash FROM auth_users WHERE user_id=? AND active=1",(user["user_id"],)).fetchone()
        if not old or not verify_password(payload.current_password,old["password_hash"]): raise HTTPException(422,"当前密码不正确")
        encoded=password_hash(payload.new_password)
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            updated=c.execute("UPDATE auth_users SET password_hash=?,version=version+1 WHERE user_id=? AND active=1 AND password_hash=?",(encoded,user["user_id"],old["password_hash"]))
            if updated.rowcount!=1: raise HTTPException(409,"账号信息已变化，请重新登录后操作")
            c.execute("DELETE FROM auth_sessions WHERE user_id=?",(user["user_id"],))
            c.execute("DELETE FROM auth_attempts WHERE attempt_key=?",(attempt,))
            c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("auth_password_changed",user["user_id"],json.dumps(actor_metadata(),ensure_ascii=False),now.isoformat()))
        response=JSONResponse({"success":True,"message":"密码已更新，所有旧会话已退出，请重新登录"})
        response.delete_cookie(COOKIE,path="/")
        return response

    @app.post("/api/auth/profile")
    def update_profile(payload:ProfileUpdate):
        user=principal()
        if not user: raise HTTPException(401,"请先登录")
        if user["role"] not in {"developer","admin"}: raise HTTPException(403,"当前角色不能修改账号名称")
        name=str(user["user_id"]) if identity_configuration() else username(payload.username);display=payload.display_name.strip()
        if not display: raise HTTPException(422,"名称不能全部为空格")
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=c.execute("SELECT * FROM auth_users WHERE user_id=? AND active=1",(user["user_id"],)).fetchone()
            if not old or old["version"]!=payload.version: raise HTTPException(409,"账号已更新，请刷新后重试")
            if old["role"] not in {"developer","admin"}: raise HTTPException(403,"当前角色不能修改账号名称")
            if c.execute("SELECT 1 FROM auth_users WHERE username=? AND user_id<>?",(name,user["user_id"])).fetchone(): raise HTTPException(409,"账号名已存在")
            c.execute("UPDATE auth_users SET username=?,display_name=?,version=version+1 WHERE user_id=?",(name,display,user["user_id"]))
            c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("auth_profile_updated",user["user_id"],json.dumps({"username":name,**actor_metadata()},ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        return {"success":True,"version":payload.version+1}

    @app.get("/api/auth/users")
    def users():
        admin()
        with connect() as c: records=[dict(row) for row in c.execute("SELECT user_id,username,display_name,role,staff_id,active,version FROM auth_users ORDER BY username")]
        return {"records":records}

    @app.post("/api/auth/users")
    def create_user(payload:UserInput):
        admin();name=username(payload.username) if payload.username.strip() else "";validate_password(payload.password)
        if not payload.display_name.strip(): raise HTTPException(422,"请填写人员姓名，不能全部为空格")
        encoded=password_hash(payload.password)
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE");staff_id=validate_role(c,payload.role,payload.staff_id)
            if c.execute("SELECT 1 FROM auth_users WHERE username=?",(name,)).fetchone(): raise HTTPException(409,"账号名已存在")
            identifier=next_user_id(c)
            name=identifier if identity_configuration() else name or identifier
            c.execute("INSERT INTO auth_users VALUES (?,?,?,?,?,?,1,1)",(identifier,name,payload.display_name.strip(),payload.role,staff_id,encoded))
            c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("auth_user_created",identifier,json.dumps({"username":name,"role":payload.role,**actor_metadata()},ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        return {"success":True,"user_id":identifier}

    @app.post("/api/auth/users/{identifier}")
    def update_user(identifier:str,payload:UserUpdate):
        admin()
        if not payload.display_name.strip(): raise HTTPException(422,"请填写人员姓名，不能全部为空格")
        with lock,connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old=c.execute("SELECT * FROM auth_users WHERE user_id=?",(identifier,)).fetchone()
            if not old: raise HTTPException(404,"账号不存在")
            if identifier==GUEST_ID and old["role"]=="viewer":raise HTTPException(403,"共享访客权限由部署配置管理，不能提升权限")
            if payload.version!=old["version"]: raise HTTPException(409,"账号信息已更新，请刷新")
            if payload.display_name.strip()!=old["display_name"] and principal()["user_id"]!=identifier: raise HTTPException(403,"名称只能由账号本人修改")
            if old["role"]=="developer" and old["active"] and (not payload.active or payload.role!="developer") and c.execute("SELECT COUNT(*) FROM auth_users WHERE role='developer' AND active=1").fetchone()[0]<=1: raise HTTPException(409,"不能停用或降级最后一个开发者")
            staff_id=validate_role(c,payload.role,payload.staff_id)
            c.execute("UPDATE auth_users SET display_name=?,role=?,staff_id=?,active=?,version=version+1 WHERE user_id=?",(payload.display_name.strip(),payload.role,staff_id,int(payload.active),identifier))
            if not payload.active: c.execute("DELETE FROM auth_sessions WHERE user_id=?",(identifier,))
            c.execute("INSERT INTO audit_events(event_type,entity_id,content,created_at) VALUES (?,?,?,?)",("auth_user_updated",identifier,json.dumps({"role":payload.role,"active":payload.active,**actor_metadata()},ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        return {"success":True,"version":payload.version+1}
