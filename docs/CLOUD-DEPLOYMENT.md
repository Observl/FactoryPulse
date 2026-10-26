# 完整云端部署与集中账号

本地与目标服务器使用同一套 React 页面和 Python 业务代码，账号及业务数据统一读写 Cloudflare D1。当前 Workers 已部署完整前端和部分业务读取接口；完整排程、方案比较及其余修改接口仍需部署 Python 计算服务。不能将准备完成的部署配置描述为完整业务已经上线。

## 部署包

- `Dockerfile`：构建完整前端与 Python 服务，使用非 root 用户、单个业务进程。
- `compose.cloud.yaml`：Caddy HTTPS 入口、后端、上传文件及加密配置卷、TLS 证书卷；不使用本地业务数据库。
- `backend/cloud_server.py`：完整云端启动入口，校验构建文件、账号配置和加密主密钥。
- `backend/requirements-cloud.lock.txt`：Linux/Python 3.12 依赖锁，容器构建和启动需通过 CI 验证。
- `.secrets/`：运行凭据，不进入 Git 或容器构建上下文。D1 令牌只由服务器读取。

## 账号中心

目标 D1：`factorypulse_users` / `af5776ef-c7f8-48c7-8f21-1bb36f98061c`。

身份配置文件示例（保存为 `.secrets/identity.json`）：

```json
{
  "account_id": "af8b5dc2fceddfd9316d60164cb2e7e2",
  "database_id": "af5776ef-c7f8-48c7-8f21-1bb36f98061c",
  "token_file": "cloudflare-d1-token"
}
```

令牌写入配置文件同目录的 `cloudflare-d1-token`，不可写入前端、GitHub 公共仓库或日志。Cloudflare 当前账号令牌 UI 的 D1 权限为账号范围；不能将它描述成已限制为单个数据库。必须由所有者授权该范围后才能创建。不要授予其他产品权限。

身份表存入账号 D1；设备、工单、库存、模型证据及业务审计存入业务 D1 `abc7cb74-5be4-49a2-827a-3bd8b639f257`。业务配置保存为 `.secrets/business.json`，格式同上，使用业务库 ID。生产运行禁止本地 SQLite，上传 SQLite/SQL 文件的旧路径已关闭，可使用 CSV/XLSX 导入。D1 不开放匿名 SQL 接口；网站权限与 Cloudflare 控制台权限相互独立。

既有账号表升级运行：

```powershell
.venv\Scripts\python.exe scripts/upgrade-d1-account-schema.py
```

该操作保留有效的数字编号账号及密码，移除 username，修复内部事务表，并在私有目录备份。账号使用从 10001 开始的数字编号登录，不再自动创建默认管理员或访客。用户自行配置账号，密码使用 64 位 SHA-256；角色和人员编号约束见 [账号表规则](ACCOUNT-SCHEMA.md)。

本地启动前设置：

```powershell
$env:FACTORYPULSE_IDENTITY_CONFIG=(Resolve-Path .secrets/identity.json).Path
```

账号及业务提交使用 D1 原子批处理与版本冲突校验，跨部署冲突返回 409；网络失败返回 503，不回退到本地数据库。查询及事务工作表也在 D1。部署准备读取既有账号配置，不再索取或生成默认管理员密码。

## 服务器启动

服务器需有 Docker Compose，域名 A/AAAA 记录指向服务器，并开放 80/443。将源码和受保护的 `.secrets` 文件分别传到服务器，不上传已有本地业务数据库或浏览器配置。

Linux 上 Compose 的文件型 secrets 可能保留源文件权限。容器业务用户为 UID/GID 10001；上传后由服务器所有者设置 `.secrets` 目录仅自己可进入，机密文件组为 10001、权限 0640，使容器可读取但其他普通用户不可读取。使用 root 所有者部署时可执行：

```sh
sudo chown -R root:10001 .secrets
sudo chmod 0700 .secrets
sudo chmod 0640 .secrets/*
```

此后用 `sudo docker compose` 执行以下启动命令。不要为解决权限问题把机密文件设置为全员可读。

```sh
cp deploy/cloud.env.example deploy/cloud.env
# 编辑 FACTORYPULSE_DOMAIN 为计算服务域名，并设置 BUILD_COMMIT。
# FACTORYPULSE_FRONTEND_ORIGIN 保留实际 Cloudflare 页面来源。
docker compose --env-file deploy/cloud.env -f compose.cloud.yaml up -d --build
docker compose --env-file deploy/cloud.env -f compose.cloud.yaml ps
```

集中账号配置在 Compose 中作为机密挂载；缺少 D1 配置时拒绝启动，禁止使用独立 SQLite 账号库替代。共享访客只能读取，不能提升角色或修改共享密码。

## 更新、备份与回退

更新前停止写入并制作一致性业务备份，再更新镜像；保留 `factorypulse_data` 卷。`docker compose down` 不删除数据，**不要使用 `down -v`**。回退前确认数据库结构兼容，不能直接降级打开更高结构版本。

D1 账号及业务数据均由 Cloudflare 导出及 Time Travel 管理；本地数据库备份关闭。加密主密钥必须单独备份，丢失后不能解密已保存 AI 密钥。禁止把主密钥备份到公开仓库。

## 本地修改后发布

1. 在本地修改同一套 Python/React 源码，数据始终访问 D1。
2. 优先执行与改动相关的短时检查；完整训练、大数据导入、容器构建及全量验收另行安排。
3. 上传源码到 GitHub。上传源码本身不会为 Workers 增加 Python 求解能力。
4. 提供计算服务域名及服务器后，部署上述容器；将其 HTTPS 根地址设置为 Worker 的 `BUSINESS_API_ORIGIN`。
5. Python 的允许来源必须包含 `FACTORYPULSE_FRONTEND_ORIGIN`。Worker 保留请求方法、参数、正文和 D1 会话 Cookie，Python 再验证账号权限并读写同一 D1。
6. 先做一次小范围的读写与排程检查，再扩大验收范围。

服务器尚未提供时，可以准备部署包及运行隔离短测，不能宣称完整业务已经上线。当前线上部分接口仍返回 501；接入真实 Python 服务后由该服务处理。
