# SiliconDreams v1.0.0-rc.5

`v1.0.0-rc.5` 是面向 CPU-only ECS 部署的候选版本。它保留 rc.4 的公网验收能力，并修正 Linux 容器错误安装 CUDA 运行时所造成的镜像膨胀。

## 本候选版变化

- Linux 从 PyTorch 官方 CPU wheel 索引安装 `torch+cpu`，macOS 继续使用支持 MPS 的 PyPI wheel。
- 从通用依赖锁中移除 CUDA、NVIDIA 与 Triton 运行时，避免 CPU-only 生产主机下载无用 GPU 依赖。
- `requirements.txt` 改为完整、带 hash 的生产依赖快照；CI 安全审计不再二次解析依赖。
- CI 与发布工作流均在真实 Linux 容器内断言 `torch.version.cuda is None`，并输出镜像字节大小。

## 部署镜像

```bash
export SILICONDREAMS_IMAGE=ghcr.io/tyth3369/silicondreams:v1.0.0-rc.5
docker compose -f compose.yaml -f compose.registry.yaml pull app
docker compose -f compose.yaml -f compose.registry.yaml up -d --no-build
```

镜像 digest：`sha256:52615f147d2db0d0a9ec68951751e163139387be7ff0f35761f99dcb30c19585`。发布工作流按 digest 回拉镜像后确认 `torch 2.14.0+cpu`、镜像大小 `1,713,377,249` 字节，并从真实容器的 `/healthz` 得到 `1.0.0-rc.5`。构建来源已生成 [provenance attestation](https://github.com/tyth3369/SiliconDreams/attestations/47270759)，签名写入 Rekor 与 GHCR。

## 上线验收

```bash
uv run python scripts/verify_deployment.py \
  --base-url https://sillycon.xyz \
  --alias-url https://www.sillycon.xyz \
  --expected-version 1.0.0-rc.5 \
  --expected-ip ECS_PUBLIC_IPV4
```

正式 `v1.0.0` 仍需完成目标 ECS 上的真实 PDF、实时网页检索、备份恢复和 24 小时运维观察。
