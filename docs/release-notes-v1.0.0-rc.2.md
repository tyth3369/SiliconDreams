# SiliconDreams v1.0.0-rc.2

这是 v1.0 的第二个发布候选，修复首个候选在依赖安全审计上的治理缺口，不增加产品功能。

## 相比 rc.1 的变化

- CI 新增 `pip-audit` 生产依赖漏洞门禁；未复核的新漏洞会直接阻断构建。
- 逐项记录 ChromaDB 1.5.9 尚无修复版本的 HTTP Server/RBAC 公告、当前不可达原因、补偿控制与例外移除条件。
- 新增架构回归测试，保证应用继续使用嵌入式 `PersistentClient`，不会引入 Chroma HTTP Client、Server 服务或端口暴露。
- 产品、数据模型、界面和数据库 schema 与 rc.1 保持兼容。

## 升级前必须执行

```bash
python scripts/manage_database.py backup backups/pre-v1.0-rc2.db
git pull --ff-only
uv sync --locked
python scripts/manage_database.py verify
```

Docker 部署请按 [deployment.md](deployment.md) 操作。目标 ECS 的 DNS、HTTPS、真实 PDF、Tavily、备份恢复和 24 小时观察仍是晋升 v1.0.0 前的必要人工门禁。

依赖例外详情见 [security-advisories.md](security-advisories.md)，完整验收状态见 [release-checklist-v1.0.md](release-checklist-v1.0.md)。

