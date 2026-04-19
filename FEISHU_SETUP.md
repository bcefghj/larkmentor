# 飞书开发者平台配置指南

> 完整跑通 LarkMentor 需要先在飞书开放平台创建一个自建应用，拿到 `App ID` 和 `App Secret`。  
> 整个过程约 **10 分钟**。

---

## 第一步：创建自建应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，用你的飞书账号登录
2. 点击右上角 **「创建应用」**
3. 选择 **「自建应用」**
4. 填写名称（如 `LarkMentor`）和描述，上传图标，点击确认
5. 进入应用后，在左侧 **「凭证与基础信息」** 页面找到：
   - `App ID`（形如 `cli_xxxxxxxxx`）
   - `App Secret`（点击「查看」复制）

把这两个值填进你的 `.env`：

```
FEISHU_APP_ID=cli_xxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx
```

---

## 第二步：开启机器人能力

1. 左侧菜单 **「应用功能」→「机器人」**
2. 点击 **「开启机器人」**
3. 消息卡片请求网址：**留空**（我们使用 WebSocket 长连接，不需要填 HTTP 回调地址）

---

## 第三步：申请 API 权限

左侧菜单 **「权限管理」→「API 权限」→「申请权限」**

### 必须申请（缺一不可）

| 权限标识 | 用途 |
|----------|------|
| `im:message` | 接收和发送消息 |
| `im:message:send_as_bot` | Bot 主动发送卡片消息 |
| `im:chat:readonly` | 读取群信息（识别发送人） |
| `contact:user.base:readonly` | 解析发送者姓名 |
| `docx:document` | 自动创建《新手成长记录》飞书文档 |
| `bitable:app` | 读写多维表格（任务结构化） |

### 可选申请（有代码兜底，不开也能跑）

| 权限标识 | 用途 |
|----------|------|
| `calendar:calendar` | 日历忙闲查询（专注时自动标记） |
| `task:task` | 飞书任务 v2 管理 |
| `wiki:wiki:readonly` | Wiki 知识检索（`导入wiki:` 指令） |

---

## 第四步：配置事件订阅

左侧菜单 **「开发配置」→「事件与回调」→「事件配置」**

**关键选择**：选 **「使用长连接接收事件」**，不要选 HTTP 回调（这样本地和服务器都不需要公网 IP 即可开发测试）。

需要订阅以下两个事件：

| 事件 | 用途 |
|------|------|
| `im.message.receive_v1` | 接收用户私聊和群消息 |
| `card.action.trigger` | 接收卡片按钮点击（Recovery Card 的采纳按钮依赖这个！） |

> ⚠️ **如果不订阅 `card.action.trigger`，点击 Recovery Card 上的「采纳」按钮会没有反应。**

---

## 第五步：发布应用版本

每次修改权限或事件配置后，都需要发布新版本才能生效：

1. 左侧菜单 **「应用发布」→「版本管理与发布」**
2. 点击 **「创建版本」**，填写版本号（如 `1.0.0`）
3. 点击 **「提交审核」**

> - 测试企业（个人开发者账号）：**立即自动通过**
> - 正式企业：需要管理员审批

---

## 第六步：启动 Bot 验证

```bash
# 1. 填好 .env
cp .env.example .env
# 编辑 .env，填入 FEISHU_APP_ID 和 FEISHU_APP_SECRET

# 2. 启动
python main.py
```

启动后你会看到：
```
╔═══════════════════════════════════════════╗
║  FlowGuard v4.0 – AI 工作伙伴 (守护+教练)   ║
╚═══════════════════════════════════════════╝
正在连接飞书长连接服务...
```

在飞书中搜索你创建的 Bot 名称 → 私聊发 `开启新人模式` → 应该收到欢迎卡片。

---

## 常见问题

| 症状 | 原因 | 解决 |
|------|------|------|
| Bot 无响应 | 事件没订阅或版本未发布 | 检查「事件订阅」→「发布版本」 |
| 点卡片按钮没反应 | 缺少 `card.action.trigger` 事件 | 补充订阅，重新发布 |
| 报错 `99991403 permission denied` | 权限未申请或版本未发布 | 去「API 权限」申请 → 发布新版本 |
| Bot 不响应群消息 | 群消息需要 @Bot 才能触发 | 在群里 @LarkMentor + 内容 |
| `FEISHU_APP_ID` 报错 | `.env` 没填 | 检查 `.env` 文件 |

---

## 获取火山方舟 API Key（LLM）

LarkMentor 使用[火山方舟](https://console.volcengine.com/ark) Doubao 模型作为 LLM：

1. 注册 [火山引擎](https://console.volcengine.com/) 账号
2. 进入 [方舟控制台](https://console.volcengine.com/ark)
3. 左侧 **「API Key 管理」→「创建 API Key」**
4. 复制 API Key（形如 `ark-xxxxxxxxxxxx`）
5. 填入 `.env`：

```
ARK_API_KEY=ark-xxxxxxxxxxxx
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
ARK_MODEL=doubao-seed-2.0-pro
```

> **Coding Plan 用户免费**：如果你是「方舟编程计划」用户，使用上述 `coding/v3` 端点不消耗额度。

---

## 完整 `.env` 示例

```bash
# 飞书（必填）
FEISHU_APP_ID=cli_xxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx

# 火山方舟（必填）
ARK_API_KEY=ark-xxxxxxxxxxxx
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
ARK_MODEL=doubao-seed-2.0-pro

# 飞书多维表格（可选，用于数据存储）
BITABLE_APP_TOKEN=
BITABLE_TABLE_ID=

# Dashboard 端口（默认 8080）
DASHBOARD_PORT=8080
```

其他配置项见 [`.env.example`](.env.example)。
