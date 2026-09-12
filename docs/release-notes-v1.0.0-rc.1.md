# SiliconDreams v1.0.0-rc.1

这是 v1.0 的首个发布候选，面向个人或小团队共享账号部署。相比 v0.9.0，本候选版重点完成了可升级性、公网安全、真实引用质量门禁和隐私安全的运维可观测性。

## 主要变化

- SQLite schema v1→v6 有序事务迁移，带迁移校验和、备份、验证与原子恢复工具。
- 生产环境单账号认证、PBKDF2 密码哈希、签名会话、CSRF、分层限流、追加审计日志和 nonce CSP。
- 真实 DeepSeek 回答的人工 claim→source 引用基准：precision 100%、coverage 100%、编号有效率 100%。
- 每个 Agent 请求记录总耗时、首 token、模型/工具错误、实际 token、来源类型与可选 Decimal 成本估算；不复制研究正文或来源详情。
- HTMX 1.9.12、Marked 15.0.12、DOMPurify 3.4.15 和 IBM Plex 字体改为锁定版本、本地托管，页面运行不再依赖第三方 CDN。
- GitHub Actions 新增生产容器构建和 Compose 配置验证。

## 升级前必须执行

```bash
python scripts/manage_database.py backup backups/pre-v1.0-rc1.db
git pull --ff-only
uv sync --locked
python scripts/manage_database.py verify
```

Docker 部署请按 [deployment.md](deployment.md) 更新。数据库会在应用启动时升级到 schema v6；不要在没有已验证备份的情况下升级。

## 已知边界

- 当前是单共享账号，不是多租户系统。
- Uvicorn 必须保持一个 worker；POST→SSE hand-off 和限流状态仍在进程内。
- 本地 BGE-M3 和 cross-encoder 在 CPU 服务器首次加载较慢，需要持久化模型卷。
- 发布候选仍需在目标 ECS 上完成 DNS、HTTPS、真实 PDF、Tavily、备份恢复和 24 小时运维观察后，才晋升为 v1.0.0。

完整验收状态见 [release-checklist-v1.0.md](release-checklist-v1.0.md)。

