# SiliconDreams 部署指南：阿里云 ECS + sillycon.xyz

当前版本包含本地 BGE-M3、Cross-Encoder、SQLite、ChromaDB 和长连接 SSE，不适合部署到纯静态托管或无持久磁盘的 Serverless 平台。首版推荐使用阿里云香港 ECS、Docker Compose 与 Caddy。

## 1. 购买和准备 ECS

推荐首发规格：

- 地域：香港。香港节点不要求中国大陆 ICP 备案；若使用中国大陆 ECS，域名上线前必须完成 ICP 备案。
- 系统：Ubuntu 24.04 LTS x86_64。
- 配置：至少 4 vCPU、16GB RAM、50GB SSD；本地模型使用 CPU，首次检索会有预热时间。
- 安全组：开放 TCP 80/443；SSH 22 仅允许自己的固定公网 IP。

阿里云官方参考：[在 ECS 上安装 Docker](https://help.aliyun.com/en/ecs/user-guide/install-and-use-docker)、[ICP备案说明](https://help.aliyun.com/en/icp-filing/basic-icp-service/support/for-the-record-process-faq)。

## 2. 配置域名解析

在阿里云云解析 DNS 中添加：

| 主机记录 | 类型 | 记录值 |
|---|---|---|
| `@` | A | ECS 公网 IPv4 |
| `www` | A | ECS 公网 IPv4 |

等待解析生效后可用 `dig +short sillycon.xyz` 检查。官方参考：[添加网站解析](https://help.aliyun.com/zh/dns/pubz-add-website-parsing)。

## 3. 安装 Docker 与拉取代码

登录 ECS 后执行：

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker

git clone https://github.com/tyth3369/SiliconDreams.git
cd SiliconDreams
```

生产环境更建议按阿里云官方 Docker 文档配置软件源，而不是长期依赖 convenience script。

## 4. 配置 secrets 与应用登录

```bash
cp .env.production.example .env.production
cp .env.caddy.example .env.caddy
chmod 600 .env.production .env.caddy
```

在 `.env.production` 填入真实 DeepSeek 与 Tavily API Key。

若需要显示 API 成本估算，再按供应商当前合同价格填写
`LLM_INPUT_CACHE_HIT_USD_PER_MILLION`、`LLM_INPUT_CACHE_MISS_USD_PER_MILLION` 和
`LLM_OUTPUT_USD_PER_MILLION`。三个值必须同时填写；留空时仍记录实际 token，但成本显示为 `null`，避免用过期价格产生伪精确结果。

生成应用用户名、PBKDF2 密码哈希和随机会话密钥：

```bash
docker compose run --rm app python scripts/generate_auth_config.py
```

将输出的 `APP_*`、`AUTH_ENABLED`、`COOKIE_SECURE`、`TRUST_PROXY_HEADERS` 和 `RATE_LIMIT_ENABLED` 行完整复制到 `.env.production`，替换示例值。密码哈希必须保留生成器输出的单引号，避免 `$` 被 Compose 插值；明文密码不会写入文件。`APP_ENV=production` 会在认证或安全 Cookie 未正确配置时让服务拒绝启动。

Caddy 只负责 TLS 与反向代理，登录、CSRF、限流和审计均由应用处理。不要提交 `.env.production` 或 `.env.caddy`。

## 5. 获取应用镜像并下载本地模型

### 方式 A：拉取版本化 GHCR 镜像（推荐）

每个 `v*` 标签都会由 GitHub Actions 构建镜像、运行 `/healthz` 冒烟测试并生成 provenance attestation。部署时只使用明确版本，不使用浮动 `latest`：

```bash
export SILICONDREAMS_IMAGE=ghcr.io/tyth3369/silicondreams:v1.0.0-rc.5
docker compose -f compose.yaml -f compose.registry.yaml pull app
docker compose -f compose.yaml -f compose.registry.yaml run --rm app \
  python scripts/generate_auth_config.py
# 将生成的认证配置写入 .env.production 后继续
docker compose -f compose.yaml -f compose.registry.yaml run --rm app \
  python src/tools/download_bge_m3.py
docker compose -f compose.yaml -f compose.registry.yaml run --rm app \
  python src/tools/download_reranker.py
docker compose -f compose.yaml -f compose.registry.yaml up -d --no-build
```

`ghcr.io/tyth3369/silicondreams` 已验证为 Public，可匿名拉取。若未来改为私有，先用具有 `read:packages` 的细粒度凭据执行 `docker login ghcr.io`。不要把凭据写入仓库或 shell history。GitHub 说明：[Container registry 权限](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages)。

候选版必须使用完整版本标签。发布系统关闭 metadata-action 的自动 `latest` 行为；只有不含预发布后缀的稳定标签才显式更新 `latest`。

### 方式 B：在 ECS 从源码构建（回退）

```bash
docker compose build
docker compose run --rm app python src/tools/download_bge_m3.py
docker compose run --rm app python src/tools/download_reranker.py
```

模型约占 3GB，保存在 Docker 命名卷 `model_cache` 中。下载器支持断点续传。

## 6. 启动与验证

```bash
docker compose up -d
docker compose ps
docker compose logs -f --tail=100
curl -fsS http://127.0.0.1:8000/healthz
```

如果采用 GHCR 镜像，以上所有 `docker compose` 命令都要追加 `-f compose.yaml -f compose.registry.yaml`，并保持 `SILICONDREAMS_IMAGE` 指向同一版本标签。

最后访问 `https://sillycon.xyz`。Caddy 会在 DNS 已正确指向且 80/443 可达时自动申请、续期 TLS 证书，并将 HTTP 重定向到 HTTPS。

从仓库目录运行无凭据公网验收器，自动检查 DNS、TLS、HTTP 跳转、运行版本、未登录访问边界、安全响应头和 CSRF Cookie 属性：

```bash
uv run python scripts/verify_deployment.py \
  --base-url https://sillycon.xyz \
  --alias-url https://www.sillycon.xyz \
  --expected-version 1.0.0-rc.5 \
  --expected-ip ECS_PUBLIC_IPV4
```

也可追加 `--json` 输出供 CI 或运维平台读取。别名检查会验证 `www` 的 DNS、TLS 和到主域名的规范跳转。命令不会发送登录凭据、API Key 或研究内容；任何检查失败都会返回非零退出码。若本地代理启用了 Fake-IP，类似 `198.18.0.0/15` 的非公网结果会被明确拒绝。建议同时在 ECS 本机执行一次，以排除本地代理 DNS 的影响。

不熟悉终端时，可以打开 GitHub 仓库的 **Actions → Verify public deployment → Run workflow**，只填写 ECS 公网 IPv4；其余三项已有 `sillycon.xyz`、`www.sillycon.xyz` 和当前候选版本的默认值。该工作流从 GitHub 的公网 Runner 运行同一验证器，只申请仓库只读权限，不读取任何 GitHub Secret、应用密码或 API Key。检查失败时展开 `Verify DNS, TLS, application and security boundary` 即可看到具体失败项。

应用必须保持单个 Uvicorn worker；当前 POST 请求到 SSE 流之间的短暂交接状态仍位于进程内。横向扩容前要先把这部分迁移到 Redis 或统一的持久队列。

## 7. 更新、备份和回滚

升级前先创建并校验 SQLite 在线备份（能够包含 WAL 中已提交的数据）：

```bash
mkdir -p backups
docker compose exec app python scripts/manage_database.py status
docker compose exec app python scripts/manage_database.py backup \
  "/app/backups/silicondreams-$(date +%F-%H%M%S).db"
```

Compose 已把宿主机 `backups/` 挂载到容器 `/app/backups/`。不要只在服务运行时复制 `.db` 文件，因为 WAL 中可能还有已提交的数据。

更新：

```bash
git pull --ff-only
docker compose build app
docker compose up -d
docker compose exec app python scripts/manage_database.py verify
docker compose exec app python scripts/manage_database.py audit --limit 50
docker compose exec app python scripts/manage_database.py metrics --hours 24
```

GHCR 部署的升级方式是先备份，再更新版本化镜像变量并拉取：

```bash
export SILICONDREAMS_IMAGE=ghcr.io/tyth3369/silicondreams:NEW_VERSION
docker compose -f compose.yaml -f compose.registry.yaml pull app
docker compose -f compose.yaml -f compose.registry.yaml up -d --no-build app
docker compose -f compose.yaml -f compose.registry.yaml exec app \
  python scripts/manage_database.py verify
```

完整灾备还应包含 `data/pdfs/` 与 `data/chroma_db/`；Caddy 证书卷可以自动重建，本地模型卷可以重新下载。停机后的完整目录归档可使用：

```bash
tar -czf "silicondreams-data-$(date +%F).tar.gz" data
```

数据库恢复会拒绝覆盖现有文件，必须明确传入 `--force`。恢复前停止应用并保留当前数据目录：

```bash
docker compose stop app
docker compose run --rm app python scripts/manage_database.py \
  --database /app/data/silicondreams.db restore /app/backups/KNOWN-GOOD.db --force
docker compose up -d app
docker compose exec app python scripts/manage_database.py verify
```

查看状态与回滚：

```bash
git log --oneline -10
git checkout v0.8.0
docker compose build app
docker compose up -d
```

## 上线边界

- 该配置面向个人/小范围首发，应用提供单账号认证，不是多租户权限系统。
- 不要直接暴露 `8000` 端口；公网只开放 Caddy 的 80/443。
- 不要使用多个 Uvicorn worker。
- `data/` 含上传文档、会话和向量索引，应视为敏感数据并定期备份。
- 上线前阅读 `docs/security.md`，确认密钥轮换、代理边界和事故响应步骤。
