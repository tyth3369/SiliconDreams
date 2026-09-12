# SiliconDreams v1.0 发布候选验收清单

候选版本：`v1.0.0-rc.1`  
验收日期：2026-09-13  
最近稳定版：`v0.9.0`

## 自动化质量门禁

- [x] `uv lock --check`
- [x] `uv run ruff format --check .`
- [x] `uv run ruff check .`
- [x] 完整 pytest 与分支覆盖率门槛
- [x] Chromium E2E：主题、语言、图表、Watchlist、会话保持与认证路径
- [x] 引用 benchmark：precision 100%、claim coverage 100%、marker validity 100%
- [x] 官方年报检索 benchmark：Recall@5 100%、MRR 84.03%
- [x] 知识图谱审计：309 节点、1516 边、无别名冲突、无缺失端点/反向边
- [x] 工作台无外部 API 性能基线
- [x] `uv pip check`、JavaScript 语法与 Git diff whitespace
- [x] SQLite schema v6 integrity、foreign keys 与迁移历史
- [x] GitHub Actions 主质量工作流
- [ ] GitHub Actions 容器镜像构建与 Compose 配置

## 安全与隐私冻结

- [x] `.env`、`.github_token`、上传 PDF、SQLite、ChromaDB、备份与模型缓存未跟踪
- [x] 生产环境强制认证、Secure Cookie、CSRF、限流和可信代理边界
- [x] CSP nonce；脚本、样式、字体只允许本地 `'self'`
- [x] HTMX、Marked、DOMPurify 与 IBM Plex 锁定版本、本地托管并保留许可证
- [x] 网页/PDF/工具输出按不可信证据处理
- [x] 运维遥测不复制问题、回答、来源名称、URL 或证据片段
- [x] 数据库升级前备份、事务迁移和恢复拒绝覆盖已有文件

## 产品验收

- [x] 网页、PDF、术语和官方结构化事实多路径检索
- [x] 一次检索规划、并发执行、至多一次计算规划，无开放循环
- [x] 所有财务算术只经过 Decimal 计算器
- [x] 行内 `[N]` 引用与来源面板一一对应；网页/官方来源可打开
- [x] PDF 引用保留文件名、精确页码和原文片段
- [x] 中文/英文、自动/深色/浅色切换不清空会话
- [x] 会话新建、命名、切换、归档、恢复与 Markdown/PDF 导出
- [x] 财务图表、制程结构、Capex 强度、Watchlist 与官方事件时间线
- [x] PDF 摄入任务持久化、显示进度并可在重启后恢复

## 部署机上线前人工验收

- [ ] DNS `sillycon.xyz` / `www.sillycon.xyz` 指向目标 ECS
- [ ] 仅开放公网 80/443；8000 不直接暴露；SSH 仅可信来源
- [ ] 真实 `.env.production` 权限为 600，API Key 未出现在镜像、日志或 Git
- [ ] 下载 BGE-M3 与 reranker 后，模型卷可在容器重启后复用
- [ ] `docker compose up -d` 后 app 与 Caddy 均 healthy
- [ ] `https://sillycon.xyz/healthz` 返回 `v1.0.0-rc.1`，HTTP 自动跳转 HTTPS
- [ ] 登录失败、CSRF 拒绝和 AI 限流行为符合预期
- [ ] 用一份真实 PDF 验证上传→后台解析→索引→带页码引用回答
- [ ] 用一个“最新”问题验证 Tavily、来源日期、行内引用和外链
- [ ] 创建已验证数据库备份并演练一次恢复到临时路径
- [ ] 观察 24 小时 `/ops/metrics` 与审计日志，无异常错误峰值

## 发布决策

只有自动化门禁全部通过，且部署机人工验收没有 P0/P1 问题时，才把 `v1.0.0-rc.1` 晋升为 `v1.0.0`。候选期只接受阻断发布的修复，不再加入新功能。

