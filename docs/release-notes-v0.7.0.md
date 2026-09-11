# SiliconDreams v0.7.0

首个可发布版本，将早期原型重构为证据优先、可恢复、可测试的半导体投研助理。

## 主要能力

- DeepSeek Provider、确定性检索规划与流式回答。
- Tavily 网页检索、上传 PDF 混合 RAG、术语库与官方公司事实多路径取证。
- BGE-M3 + BM25 + weighted RRF + 多语言 Cross-Encoder 重排。
- Python Decimal 财务计算器，所有算术与模型生成解耦。
- SQLite 会话/来源/文档/事实持久化与 ChromaDB 向量索引。
- 消息内 `[N]` 引用、精确 PDF 页码、网页链接和安全 Markdown 渲染。
- Bloomberg Terminal 风格中英文 UI，支持自动/深色/浅色主题。

## 工程与部署

- Python 3.12、uv 锁文件、Ruff、pytest 和 GitHub Actions。
- Docker Compose + Caddy 单机部署，自动 HTTPS、Basic Auth、持久化数据与模型卷。
- 阿里云 ECS 与 `sillycon.xyz` 的完整部署、备份及回滚指南。

## 当前边界

- 当前生产配置面向个人或小范围使用，默认启用 Basic Auth。
- 必须保持单 Uvicorn worker；多实例前需将 SSE hand-off 迁移至共享队列。
- 季度官方结构化事实、正式身份系统、限流和审计计划在后续版本完成。
- 本项目用于研究辅助，不构成投资建议。

## 验证

- Ruff format/check 通过。
- 89 项 pytest 回归测试通过。
- uv 锁文件和已安装依赖一致性检查通过。
