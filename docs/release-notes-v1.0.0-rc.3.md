# SiliconDreams v1.0.0-rc.3

这是 v1.0 的第三个发布候选，重点把已验证源码转化为可审计、可直接部署的版本化容器制品。

## 相比 rc.2 的变化

- `v*` Git 标签自动构建并发布 `ghcr.io/tyth3369/silicondreams:<version>`。
- 发布工作流会拉取刚推送的 digest、启动真实容器并验证 `/healthz`，随后为同一 digest 生成 GitHub artifact attestation。
- 新增 `compose.registry.yaml`，阿里云 ECS 可拉取固定版本镜像并以 `--no-build` 启动；原有源码构建流程继续保留。
- CI 同时验证源码 Compose 和 registry override 的合并配置。
- 继承 rc.2 的生产依赖漏洞门禁与 ChromaDB 限时例外约束。

## 推荐部署镜像

```bash
export SILICONDREAMS_IMAGE=ghcr.io/tyth3369/silicondreams:v1.0.0-rc.3
docker compose -f compose.yaml -f compose.registry.yaml pull app
docker compose -f compose.yaml -f compose.registry.yaml up -d --no-build
```

首次发布后需在 GitHub Package 设置中将容器包设为 Public，或在 ECS 使用 `read:packages` 凭据登录 GHCR。完整部署步骤见 [deployment.md](deployment.md)。

目标 ECS 的 DNS、HTTPS、真实 PDF、Tavily、备份恢复和 24 小时观察仍是晋升 v1.0.0 前的必要人工门禁。

