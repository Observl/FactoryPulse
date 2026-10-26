# Cloudflare 网站与账号服务

Cloudflare 主站、GitHub Pages 与本机使用同一个完整 React 应用及账号协议。部署地址决定 API 请求发往哪里，不使用精简页面、前端模拟认证或不同的功能分支。

| 入口 | 账号连接 |
| --- | --- |
| 本机 | `/api/auth/*` → Python 账号接口 → 现有 Cloudflare D1 |
| Cloudflare 主站 | `https://factorypulse.griffonage2077.workers.dev`，页面与 `/api/auth/*` 同源，Worker 绑定现有 D1 |
| GitHub Pages 镜像 | 同一完整页面，账号请求发往 Cloudflare 主站 |

账号编号为大于等于 10000 的整数，自动分配时递增且不复用已删除编号。`staff_id` 必须为大于等于 -1 的整数：开发者固定为 0，管理员和只读用户固定为 -1，普通用户为正整数。数据库 CHECK、Worker、Python 接口及账号表单使用相同规则。

网站仍使用用户编号和用户自己配置的密码登录。D1 中的账号、密码哈希、启用状态、四类角色、教程进度和会话是同一份数据。修改密码会使其他入口的旧会话失效。不会创建默认管理员或改写现有账号密码。

账号服务源码位于 `cloudflare/identity/worker.mjs`，绑定 `factorypulse_users` 为 `DB`。数据库令牌不放进 Worker 源码或浏览器。外部只能调用经过权限检查的账号接口，没有公开 SQL 查询接口。

跨站登录使用 `HttpOnly; Secure; SameSite=None; Partitioned` 会话 Cookie，浏览器请求使用 `credentials: include`。只允许明确列出的页面来源，不使用通配 CORS。需要支持分区 Cookie 的浏览器；若浏览器禁止此类会话，登录不会以离线身份绕过验证。

本机继续使用同源 Cookie；两种连接共用 D1 的会话哈希。D1 修改使用同一套版本保护，冲突返回 409，数据库故障返回 503，不回退到默认账号。

## 修改与验证

```sh
npm ci --prefix cloudflare/identity --ignore-scripts
npm test --prefix cloudflare/identity
```

测试使用隔离 D1，不接触真实账号。Worker 发布使用 `cloudflare/identity/wrangler.jsonc`，必须在所有者授权的 Cloudflare 会话中执行。GitHub 的页面构建通过 `VITE_API_BASE_URL` 设置公开 API 地址；这不是数据库凭据。

## 业务服务器

账号服务支持真实登录、退出、教程、个人资料、改密与开发者账号管理。设备数据、模型训练、维修排程等 Python 功能仍需要业务服务器。未配置时这些接口明确返回 503，不生成虚假成功结果或演示数据。

提供服务器后，把完整 Python 服务接入同一个 D1，并在 Worker 中设置 `BUSINESS_API_ORIGIN` 为其 HTTPS 根地址；后端可信来源需包含 `https://observl.github.io`。Worker 会在验证真实会话后转发业务请求，网站代码无需切换版本。

## 完整网页托管

`cloudflare/wrangler.jsonc` 将完整 `dist/` 作为静态资源与真实账号 Worker 一起部署，数据库绑定为 `DB`。前端使用 `/api`，不再依赖 GitHub 提供登录接口。只上传构建目录及账号服务代码，禁止上传项目根目录、业务数据库或 `.secrets`。

```sh
npm run build
npx wrangler deploy --config cloudflare/wrangler.jsonc
```

部署后检查首页、资源文件、`/api/auth/status` 与构建清单。主站账号登录是同源请求，页面源文件始终为完整工作台。
