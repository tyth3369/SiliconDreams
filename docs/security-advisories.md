# 依赖安全公告与限时例外

最后复核：2026-09-13

适用版本：v1.0.0-rc.2

## 执行策略

CI 使用 `pip-audit` 检查生产依赖。任何未在本文件登记的漏洞都会阻断构建。例外只允许用于已经逐项复核、当前没有修复版本、且其攻击路径在 SiliconDreams 部署边界内不可达的问题。

## ChromaDB 1.5.9

截至复核日期，ChromaDB 1.5.9 受以下公告影响，且上游尚未发布修复版本：

| 审计 ID | 上游公告 | 涉及路径 | 当前处置 |
|---|---|---|---|
| PYSEC-2026-311 | [GHSA-f4j7-r4q5-qw2c](https://github.com/advisories/GHSA-f4j7-r4q5-qw2c) | HTTP Server API | 限时例外 |
| PYSEC-2026-3814 | [GHSA-36p7-vc44-83pf](https://github.com/advisories/GHSA-36p7-vc44-83pf) | HTTP Server RBAC/tenancy | 限时例外 |
| PYSEC-2026-3815 | [GHSA-xph7-9rjv-w5fr](https://github.com/advisories/GHSA-xph7-9rjv-w5fr) | HTTP Server API | 限时例外 |
| PYSEC-2026-3813 | [GHSA-2wm9-hf6c-p5cr](https://github.com/advisories/GHSA-2wm9-hf6c-p5cr) | HTTP Server RBAC/tenancy | 限时例外 |

### 为什么当前攻击路径不可达

- 应用只在 `src/vector_store.py` 中使用进程内 `chromadb.PersistentClient`，没有 `HttpClient`。
- Compose 没有 ChromaDB 服务，也没有启动 `chroma run`。
- 应用容器的 8000 端口只通过 Docker 内部 `expose` 提供给 Caddy，不映射到宿主机；公网仅开放 Caddy 的 80/443。
- Chroma 持久目录只由应用进程访问，外部请求不能直接调用其 Server API、RBAC 或 tenancy 接口。

这些控制只说明已知 HTTP Server 攻击面在当前单实例架构中不可达，不代表依赖本身已经安全。

### 例外的移除条件

满足任一条件时必须立即取消对应 `--ignore-vuln` 并重新锁定依赖：

1. ChromaDB 发布包含修复的兼容版本；
2. 项目改用 `chromadb.HttpClient`、启动 Chroma Server、增加独立 Chroma 服务或暴露其端口；
3. 新公告证明嵌入式 `PersistentClient` 同样受影响；
4. 下一次候选版发布审计到期。

架构回归由 `tests/test_dependency_policy.py` 阻止；依赖漏洞回归由 CI 的 `pip-audit` 阻止。每个发布候选都必须重新查阅上游公告，不得无限期沿用本例外。
