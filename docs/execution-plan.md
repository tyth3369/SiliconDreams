# SiliconDreams — v0.7 至 v1.0 执行计划

## v0.7 工程与证据基础

- [x] Git 可恢复基线与 secrets 审计
- [x] Python 3.12 + uv + `pyproject.toml` + lockfile
- [x] 删除 Streamlit、LangChain ReAct、LlamaIndex 活跃依赖和重复计算器
- [x] Ruff、pytest、coverage 配置与 GitHub Actions
- [x] SQLite source/document/chunk/fact/conversation/message 模型
- [x] 官方台积电/中芯国际 FY2025 来源元数据
- [x] PDF 精确页码、内容寻址、幂等索引
- [x] BGE-M3 + BM25 + RRF + cross-encoder
- [x] Provider 抽象与 DeepSeek V4
- [x] 有界确定性 Agent 与并发检索
- [x] 引用安全、Markdown 消毒、会话隔离
- [x] 检索 Recall@K/MRR 评估框架
- [x] 服务端事件循环 offload、输入限制和安全响应头
- [x] 文档与真实实现同步
- [x] GitHub 首发准备、Docker Compose、Caddy HTTPS 与部署文档

## v0.8 数据质量与研究工作台

- [x] 用真实年报构建人工核验的中英双语 retrieval golden set（12 题；Recall@5 100%，MRR 84.03%）
- [x] 将台积电 2024 Q1–2026 Q2 官方季度财务事实纳入 SQLite，不再依赖网页摘要
- [x] 补齐中芯国际季度官方财务事实并统一两家公司披露口径
- [x] 来源可信度/发布日期/冲突检测进入回答策略
- [x] PDF 摄入改为持久后台 job，显示阶段与进度
- [x] 对话管理：新建、命名、切换、归档
- [x] 下载研究结果为 Markdown/PDF

## v0.9 分析产品化

- [x] 可复用公司对比模板与指标口径字典
- [ ] 财务时间序列图、制程收入结构图和 Capex 强度图
- [ ] Watchlist 与事件时间线
- [ ] Web 搜索缓存、官方域名优先和抓取快照
- [ ] 端到端浏览器测试与性能基准
- [ ] 术语关系规范化：实体、别名、关系类型、闭合边审计

## v1.0 可交付版本

- [ ] 完整数据迁移和 schema versioning
- [ ] 公网部署前身份认证、CSRF、限流、审计日志和 CSP nonce
- [ ] 真实 benchmark 达到约定 Recall@5 / citation precision 门槛
- [ ] 成本、延迟、错误率和来源覆盖度可观测
- [ ] 安装、备份、恢复、升级和安全文档
- [ ] 发布候选冻结与验收清单

## 发布门槛

每个里程碑必须同时满足：Ruff 通过、全部 pytest 通过、依赖检查通过、secrets 未跟踪、真实浏览器关键路径通过、devlog 已更新。GitHub push 只能在用户明确授权后进行。
