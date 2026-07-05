# 🤖 大模型 API 配置指南

让 "安小盾" 拥有真正的 AI 大脑！支持 **DeepSeek**、**智谱 AI**、**硅基流动** 三大国内平台。

---

## 💰 免费方案推荐

| 平台 | 免费额度 | 适用场景 | 获取链接 |
|------|---------|---------|---------|
| **智谱 GLM-4-Flash** | 🆓 完全免费 | 日常陪伴对话 | [open.bigmodel.cn](https://open.bigmodel.cn) |
| **硅基流动** | 🆓 新用户送 2000万 tokens | DeepSeek-V3 等 | [cloud.siliconflow.cn](https://cloud.siliconflow.cn) |
| **DeepSeek** | 💰 极便宜 (¥2/百万token) | 安全分析 | [platform.deepseek.com](https://platform.deepseek.com) |

> 💡 **建议**: 日常对话用智谱免费模型，安全分析用 DeepSeek。两者互补，基本不花钱。

---

## 📝 配置步骤

### 1. 智谱 AI (推荐首选，免费)

1. 打开 [https://open.bigmodel.cn](https://open.bigmodel.cn)
2. 手机号注册登录
3. 进入「API Keys」→ 创建新的 API Key
4. 复制 key，填入 `config.yaml`:

```yaml
llm:
  zhipu:
    enabled: true
    api_key: "你的key.a1b2c3d4..."  # 注意保留点号后面的部分
    model: "glm-4-flash"            # 免费模型
```

### 2. 硅基流动 (免费额度，可调用多个模型)

1. 打开 [https://cloud.siliconflow.cn](https://cloud.siliconflow.cn)
2. 注册登录 → API 密钥 → 新建
3. 复制 key，填入 `config.yaml`:

```yaml
llm:
  siliconflow:
    enabled: true
    api_key: "sk-xxxxx..."
    model: "deepseek-ai/DeepSeek-V3"   # 在硅基流动上跑 DeepSeek
```

### 3. DeepSeek (极低成本，专业分析)

1. 打开 [https://platform.deepseek.com](https://platform.deepseek.com)
2. 注册 → API Keys → 创建
3. 复制 key，填入 `config.yaml`:

```yaml
llm:
  deepseek:
    enabled: true
    api_key: "sk-xxxxx..."
    model: "deepseek-chat"
```

---

## 🔄 故障转移

配置多个平台后，系统自动故障转移：

```
主模型 (智谱免费) → 失败 → 自动切到硅基流动 → 失败 → 切到 DeepSeek
                                                              ↓
                                                     全部失败 → 本地台词库
```

角色始终在线，不会因为某个 API 挂了就沉默。

---

## 🎯 使用场景

| 功能 | 说明 | 使用的模型 |
|------|------|-----------|
| 💬 **动态陪伴对话** | 角色根据安全状态说不同的话 | 智谱免费 (glm-4-flash) |
| 🔍 **安全事件分析** | LLM 分析威胁并给出建议 | DeepSeek (deepseek-chat) |
| 🎓 **威胁通俗解释** | 用大白话解释检测到的攻击 | 任意可用模型 |
| 💬 **Web 聊天** | 在 Dashboard 中与角色自由对话 | 默认模型 |

---

## 🧪 验证配置

启动程序后查看日志：

```
🤖 LLM: 2 个模型可用
✅ 已注册: zhipu/glm-4-flash
✅ 已注册: siliconflow/deepseek-ai/DeepSeek-V3
```

或在 Web Dashboard 中访问 `http://127.0.0.1:5000/api/llm/status` 查看状态。

在 Dashboard 的聊天框输入 "你好"，角色用 LLM 回复就说明配置成功！

---

## 🛡️ 隐私提醒

- 安全事件数据会发送到 LLM API (云端)
- 不会发送你的个人文件或敏感信息
- 建议在 `config.yaml` 关闭不用的分析功能
- 仅用本地台词库则完全离线
