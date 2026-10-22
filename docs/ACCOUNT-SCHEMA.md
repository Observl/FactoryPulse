# 账号表规则

Cloudflare D1 的 `auth_users` 不再包含 `username`。网站使用 `user_id` 登录。

| 字段 | 规则 |
| --- | --- |
| user_id | 整数主键，自 10001 递增；网站创建账号后自动分配 |
| display_name | 显示名称 |
| role | 开发者、管理员、普通用户、只读用户 |
| staff_id | 开发者为 0，管理员为 -1，公司普通/只读用户使用正整数 |
| password_hash | 密码 UTF-8 字节的 SHA-256，64 位十六进制；兼容旧 PBKDF2-SHA256 |
| active | 1 启用，0 禁用 |
| version | 从 1 起的并发版本号，修改账号时递增 |

开发者拥有系统配置和账号管理权限，管理员负责维护业务审批管理，普通用户仅能处理分配给自己的工单，只读用户不能修改业务数据。数据库直接保存中文角色，服务内部映射为 developer/admin/user/viewer。

单次 SHA-256 是按所有者指定采用的格式，抗密码穷举能力弱于加盐慢哈希。登录输入原始密码，不能用哈希代替密码登录。修改密码时旧会话失效。不要将明文密码、哈希、D1 令牌发布到仓库。

只有显式配置 `FACTORYPULSE_GUEST_USER_ID` 指向一个已启用的只读账号时，才提供该账号的一键访客入口。普通编号账号不会被自动作为访客开放。

已有账号表的结构升级使用 `scripts/upgrade-d1-account-schema.py`；保留账号、原密码与教程记录，先在受保护的 `.secrets` 目录备份，并使旧会话失效。不自动创建默认账号。


在本机私密设置已有账号的密码（输入时隐藏，不需要手工计算哈希）：

```powershell
.venv\Scripts\python.exe scripts/set-d1-password.py --user-id 10001
```
