# SiliconDreams — API Key 获取指南

## 1. DeepSeek API Key（必需）

### 注册步骤

1. 访问 [platform.deepseek.com](https://platform.deepseek.com)
2. 点击右上角「注册」→ 使用手机号或邮箱注册
3. 登录后，进入「API Keys」页面
4. 点击「创建 API Key」→ 复制生成的 key（格式：`sk-xxxxxxxxxxxxxxxx`）
5. **充值**：进入「账单」页面，充值 ¥10-20 即可（API 费用极低，¥10 可用很久）

### 配置

```bash
# 在项目根目录执行
cp .env.example .env
# 编辑 .env 文件，将 DEEPSEEK_API_KEY 替换为你的实际 key
```

### 验证

```bash
# 测试 API 连通性
curl https://api.deepseek.com/v1/models \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY"
```

### 费用参考

| 模型 | 输入价格 | 输出价格 | 100次对话预估 |
|------|---------|---------|-------------|
| deepseek-chat (V3) | ¥2/百万tokens | ¥3/百万tokens | ~¥0.05-0.10 |
| deepseek-reasoner (R1) | ¥1/百万tokens | ¥6/百万tokens | ~¥0.10-0.30 |

---

## 2. BGE-M3 Embedding（自动，无需 API Key）

BGE-M3 是开源模型，首次运行时自动从 Hugging Face 下载到本地缓存。

**注意事项**：
- 模型大小约 2GB，首次下载需 3-10 分钟（取决于网速）
- 下载后缓存在 `~/.cache/huggingface/`
- 无需任何 API Key，完全免费，完全离线

**手动预先下载（可选）**：
```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
```

---

## 3. 可选：其他 API（暂不接入）

| API | 用途 | 是否需要 |
|-----|------|---------|
| Kimi (月之暗面) | 超长文档备用 | 当前不需要（DeepSeek 128K 够用） |
| 通义千问 | 企业文档备用 | 当前不需要 |

如果未来需要扩展，在 `.env` 中添加对应的 API Key 即可。

---

## 4. 环境变量完整清单

```bash
# .env 文件内容
DEEPSEEK_API_KEY=sk-your-key-here       # 必填
DEEPSEEK_API_BASE=https://api.deepseek.com  # 默认即可
LLM_MODEL=deepseek-chat                 # deepseek-chat 或 deepseek-reasoner
EMBEDDING_MODEL=BAAI/bge-m3             # 固定值，无需修改
DEBUG=false                             # 开发时可设为 true
```
