# SiliconDreams 安全指南

## 适用边界

当前身份模型面向个人或小团队共享的单账号部署。它保护 API 额度、上传文件、研究会话和管理型写操作，但不提供用户注册、角色权限、组织隔离、审计导出签名或合规留存。公网入口必须是 Caddy HTTPS；应用端口不得直接暴露。

## 安全控制

- 登录密码使用带随机盐的 PBKDF2-SHA256（600,000 次迭代）保存，仓库和数据库均不保存明文密码。
- 浏览器会话由 `APP_SESSION_SECRET` 进行 HMAC 签名，默认 12 小时失效；会话 Cookie 为 HttpOnly、SameSite=Lax，生产环境必须 Secure。
- 每个登录态具有绑定的 CSRF token。受保护的非 GET 请求必须同时携带 Cookie 与 `X-CSRF-Token`，登录表单使用预认证 CSRF token。
- 登录、AI 请求和普通请求采用独立滑动窗口限流。当前部署限定单进程，因此限流状态位于内存；多实例前必须迁移到共享存储。
- 所有变更请求写入 SQLite `audit_events`；数据库触发器拒绝 UPDATE 和 DELETE。日志只保存经 HMAC 截断的客户端标识，不保存原始 IP、密码、API Key 或请求正文。
- AI 运维遥测只保存随机请求 ID、会话外键、模型/工具计数、耗时、token、错误码和来源类型计数；不复制用户问题、模型回答、来源标题、URL 或证据片段。
- 每个 HTML 响应生成独立 CSP nonce。脚本不允许 `unsafe-inline`；HTMX、Marked、DOMPurify 与 IBM Plex 字体均以锁定版本随应用本地提供，CSP 的脚本、样式和字体只允许 `'self'`。页面同时启用 frame deny、nosniff、严格 referrer policy、权限限制和跨源 opener 隔离。
- 网页、PDF 与工具结果均视为不可信证据，不能作为系统指令执行。
- CI 使用 `pip-audit` 阻断未复核的生产依赖漏洞。当前 ChromaDB 无修复版本的 Server API 公告采用严格限时例外；攻击面、补偿控制和移除条件见 [security-advisories.md](security-advisories.md)。

## 生产配置

先运行：

```bash
docker compose run --rm app python scripts/generate_auth_config.py
```

把结果写入 `.env.production`，并确保至少包含：

```dotenv
APP_ENV=production
AUTH_ENABLED=true
APP_USERNAME=researcher
APP_PASSWORD_HASH='pbkdf2_sha256$...'
APP_SESSION_SECRET=...
COOKIE_SECURE=true
TRUST_PROXY_HEADERS=true
RATE_LIMIT_ENABLED=true
```

只有当应用仅能通过受信任 Caddy 访问时才启用 `TRUST_PROXY_HEADERS=true`。若直接暴露应用端口，攻击者可伪造转发头绕过基于客户端地址的登录限流。

## 日常检查

```bash
docker compose exec app python scripts/manage_database.py verify
docker compose exec app python scripts/manage_database.py audit --limit 100
docker compose exec app python scripts/manage_database.py metrics --hours 24
docker compose logs --since=24h app
```

重点检查重复登录失败、429 限流、连续 403 CSRF 拒绝和异常 5xx。审计表是防误改的追加日志，但与数据库位于同一信任边界；高保证部署应把日志同步到独立只写存储。

## 密钥轮换与撤销

- 更换 `APP_SESSION_SECRET` 并重启服务会立即使所有已有登录会话和 CSRF token 失效。
- 更换登录密码：重新运行生成器，只替换 `APP_PASSWORD_HASH`，然后重启服务。
- DeepSeek 或 Tavily Key 泄露时，应先在服务商后台撤销，再更新 `.env.production` 并重启；不要只删除本地文件。
- 当前无单会话撤销列表；需要立刻踢出所有会话时轮换 `APP_SESSION_SECRET`。

## 事故响应

1. 在安全组临时关闭公网 80/443，保留受限 SSH。
2. 保存应用日志并执行数据库在线备份，不要直接复制运行中的 WAL 数据库。
3. 撤销可能泄露的 API Key，轮换会话密钥与登录密码。
4. 运行数据库 `verify`，查看审计事件并核对上传目录、Git 历史和最近部署 commit。
5. 从已验证备份恢复时先停止应用，恢复后再次执行 `verify`。

## 已知限制

- 单共享账号，无法区分同一用户名下的不同人员。
- 限流为单进程内存状态，重启后清零。
- 登出不会单独吊销无状态 token；浏览器会删除 Cookie，服务端强制全局吊销依赖会话密钥轮换。
- 前端运行时已本地化，但这些 vendored 文件不会由 Python 锁文件自动升级；升级时必须核对上游版本、许可证和 SHA-256，并重新跑浏览器测试。
- ChromaDB 依赖当前包含上游尚未修复的 HTTP Server 安全公告；本项目只能继续使用嵌入式 `PersistentClient`，不得启动或暴露 Chroma Server。详见 [security-advisories.md](security-advisories.md)。
