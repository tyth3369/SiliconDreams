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

## 4. 配置 secrets 与访问保护

```bash
cp .env.production.example .env.production
cp .env.caddy.example .env.caddy
chmod 600 .env.production .env.caddy
```

在 `.env.production` 填入真实 DeepSeek 与 Tavily API Key。

生成网站密码哈希：

```bash
docker run --rm -it caddy:2-alpine caddy hash-password
```

按提示输入强密码，将输出完整复制到 `.env.caddy` 的 `SITE_PASSWORD_HASH`，并按需修改 `SITE_USERNAME`。浏览器访问网站时会要求这组用户名和密码。不要填写明文密码，也不要提交这两个生产环境文件。

## 5. 构建并下载本地模型

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

最后访问 `https://sillycon.xyz`。Caddy 会在 DNS 已正确指向且 80/443 可达时自动申请、续期 TLS 证书，并将 HTTP 重定向到 HTTPS。

应用必须保持单个 Uvicorn worker；当前 POST 请求到 SSE 流之间的短暂交接状态仍位于进程内。横向扩容前要先把这部分迁移到 Redis 或统一的持久队列。

## 7. 更新、备份和回滚

更新：

```bash
git pull --ff-only
docker compose build app
docker compose up -d
```

备份至少应包含 `data/`；Caddy 证书卷可以自动重建，本地模型卷可以重新下载。升级前建议：

```bash
tar -czf "silicondreams-data-$(date +%F).tar.gz" data
```

查看状态与回滚：

```bash
git log --oneline -10
git checkout v0.7.0
docker compose build app
docker compose up -d
```

## 上线边界

- 该配置面向个人/小范围首发，Basic Auth 是必要保护，不是完整多用户账号系统。
- 不要直接暴露 `8000` 端口；公网只开放 Caddy 的 80/443。
- 不要使用多个 Uvicorn worker。
- `data/` 含上传文档、会话和向量索引，应视为敏感数据并定期备份。
- v1.0 前仍需补充正式身份认证、CSRF、应用层限流、审计日志和 CSP nonce。
