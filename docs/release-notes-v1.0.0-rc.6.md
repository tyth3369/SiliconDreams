# SiliconDreams v1.0.0-rc.6

`v1.0.0-rc.6` 是面向公网部署的模型供应链与运行就绪加固版本。它保留 rc.5 的 CPU-only Linux 镜像，并消除模型残片被误判为完整缓存的风险。

## 本候选版变化

- BGE-M3 与多语言 reranker 固定到完整 Hugging Face commit，不再从可变的 `main` 下载。
- 每个模型文件均有预期大小和 SHA-256；下载先进入 `.part`，校验成功后原子落盘，全部文件通过后才写入版本化完成标记。
- BGE-M3 禁用 remote code，运行期只接受与固定清单匹配的离线缓存。
- 新增 `/readyz`，同时验证 SQLite、DeepSeek、Tavily、BGE-M3 与 reranker；生产 Compose 以该端点决定 app 是否 healthy。
- 公网部署验证器新增 readiness 检查，要求精确版本及所有依赖均处于 ready 状态。
- Docker 构建使用 BuildKit uv cache mount，避免将下载缓存写入运行镜像层。

## 部署镜像

```bash
export SILICONDREAMS_IMAGE=ghcr.io/tyth3369/silicondreams:v1.0.0-rc.6
docker compose -f compose.yaml -f compose.registry.yaml pull app
docker compose -f compose.yaml -f compose.registry.yaml run --rm app python src/tools/download_bge_m3.py
docker compose -f compose.yaml -f compose.registry.yaml run --rm app python src/tools/download_reranker.py
docker compose -f compose.yaml -f compose.registry.yaml up -d --no-build
```

镜像 digest：`sha256:0a67925daadfb3121a001270640f5e7346f75729cf958f7dbddd699f0cae91ae`。发布工作流按 digest 回拉镜像后确认 `torch 2.14.0+cpu`、镜像大小 `1,710,072,050` 字节，并从真实容器的 `/healthz` 得到 `1.0.0-rc.6`。构建来源已生成 [provenance attestation](https://github.com/tyth3369/SiliconDreams/attestations/47302299)，签名写入 Rekor 与 GHCR。该预发布只推送 `v1.0.0-rc.6`，没有更新 `latest`。

## 上线验收

```bash
uv run python scripts/verify_deployment.py \
  --base-url https://sillycon.xyz \
  --alias-url https://www.sillycon.xyz \
  --expected-version 1.0.0-rc.6 \
  --expected-ip ECS_PUBLIC_IPV4
```

正式 `v1.0.0` 仍需完成目标 ECS 上的 DNS/TLS、真实 PDF、实时网页检索、备份恢复和 24 小时运维观察。
