# 完整云端部署与集中账号

所有环境运行同一套 React 页面、Python API、训练解释、SQL/Excel 导入、联合排程、审批、库存、时间轴、助手、备份恢复和审计。登录入口完全一致，账号统一使用 Cloudflare D1，访客一键进入，管理员输入账号密码。没有独立精简版或模拟业务成功。

## 部署包

- `Dockerfile`：构建完整前端与 Python 服务，使用非 root 用户、单个业务进程。
- `compose.cloud.yaml`：Caddy HTTPS 入口、后端、持久业务卷、TLS 证书卷。
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

只有以下身份表上传 D1：账号与密码哈希、会话哈希、登录限流、教程进度和身份操作审计。设备、工单、模型数据继续在业务服务持久卷中。D1 不开放匿名 SQL 接口；网站账号的权限与 Cloudflare 控制台权限是两套独立权限。

```powershell
.venv\Scripts\python.exe scripts/prepare-cloud.py
.venv\Scripts\python.exe scripts/migrate-d1-identity.py --source .env.runtime/data/factorypulse.sqlite3 --config .secrets/identity.json --admin-password-file .secrets/cloud-admin-password
```

迁移只向空账号库写入；保留原有 PBKDF2 密码哈希及教程进度，增加 `test` 管理员和只读访客，不复制旧会话。已有本地账号不删除。迁移后用户重新登录，所有密码、权限和会话由集中库校验；修改密码使所有部署的旧会话一起失效。

管理员的登录名为“线上测试员”，固定 ID 为 `test`。所有部署均按用户名登录；已有用户名 `test` 的只读账号完整保留，不会因为同名 ID 被升级或覆盖。

本地启动前设置：

```powershell
$env:FACTORYPULSE_IDENTITY_CONFIG=(Resolve-Path .secrets/identity.json).Path
```

集中账号提交使用 D1 原子批处理及版本冲突校验，跨部署冲突返回 409；网络失败返回 503，不以本地副本替代认证。此实现为小规模参赛/验证账号设计，每次事务读取身份快照；大规模部署需进一步压测与专用身份服务设计。

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
# 编辑 FACTORYPULSE_DOMAIN 为实际域名，并设置 BUILD_COMMIT。
docker compose --env-file deploy/cloud.env -f compose.cloud.yaml up -d --build
docker compose --env-file deploy/cloud.env -f compose.cloud.yaml ps
```

集中账号配置在 Compose 中作为机密挂载；缺少 D1 配置时拒绝启动，禁止使用独立 SQLite 账号库替代。共享访客只能读取，不能提升角色或修改共享密码。

## 更新、备份与回退

更新前停止写入并制作一致性业务备份，再更新镜像；保留 `factorypulse_data` 卷。`docker compose down` 不删除数据，**不要使用 `down -v`**。回退前确认数据库结构兼容，不能直接降级打开更高结构版本。

D1 身份数据使用 Cloudflare 的备份/恢复机制管理；本地业务备份不包含集中账号恢复。加密主密钥必须单独备份，丢失后不能解密已保存 AI 密钥。禁止把主密钥备份到公开仓库。

服务器尚未提供时，只能完成部署包、隔离环境测试及容器 CI；不能宣称完整业务已经上线。GitHub Pages 发布相同的完整前端，但其自身不能执行 API；完整业务必须从已部署 Python 服务的地址访问。
