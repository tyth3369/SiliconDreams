# SiliconDreams v1.0.0-rc.4

`v1.0.0-rc.4` 是面向 `sillycon.xyz` 上线验收的候选版本。它保留 rc.3 的证据优先研究能力和可验证 GHCR 交付链，并补齐公网部署的自动检查入口。

## 本候选版变化

- 新增 `scripts/verify_deployment.py`，无需凭据即可验证 DNS、TLS、HTTP→HTTPS、`/healthz` 版本、认证边界、安全响应头及 CSRF Cookie 属性。
- 支持 `--expected-ip` 精确核对 ECS 公网地址，拒绝代理 Fake-IP、私网和其他非公网解析，防止 DNS 假阳性。
- 支持人类可读与 `--json` 两种输出；失败返回非零退出码，可接入运维自动化。
- 修复镜像发布工作流：预发布标签不再更新浮动 `latest`，稳定版才显式更新。

## 部署镜像

```bash
export SILICONDREAMS_IMAGE=ghcr.io/tyth3369/silicondreams:v1.0.0-rc.4
docker compose -f compose.yaml -f compose.registry.yaml pull app
docker compose -f compose.yaml -f compose.registry.yaml up -d --no-build
```

镜像 digest 和 attestation 链接将在标签发布工作流完成后写入 GitHub Release。

## 上线验收

```bash
uv run python scripts/verify_deployment.py \
  --base-url https://sillycon.xyz \
  --alias-url https://www.sillycon.xyz \
  --expected-version 1.0.0-rc.4 \
  --expected-ip ECS_PUBLIC_IPV4
```

正式 `v1.0.0` 仍需完成目标 ECS 上的真实 PDF、实时网页检索、备份恢复和 24 小时运维观察。候选版不构成稳定版晋升。
