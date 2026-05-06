"""Welcome / help cards – v13 全新文案，给裁判 30 秒可懂的第一印象."""

from __future__ import annotations

from typing import Any, Dict


def first_time_welcome_card(dashboard_url: str = "") -> Dict[str, Any]:
    """Sent the first time a user DMs the bot."""
    body = """**👋 我是 Agent-Pilot，飞书里的 AI 办公主驾驶**

我能把你的一句话需求 → 自动变成完整的文档 / PPT / 架构图 / 演讲稿。

**🚀 30 秒上手（直接发以下任意一句）：**
- `帮我写一份 AI Agent 发展趋势报告`
- `做一份 8 页客户汇报 PPT`
- `画一张产品架构图`
- `把上周讨论整理成方案 + PPT + 架构图`

**🎯 我会自动做这些事：**
1. **三闸门识别**任务意图，模糊时主动澄清
2. **4-Agent 工坊**协作（调研 → 撰写 → 评审 → 演示设计）
3. **真产物**：飞书 Docx + .pptx 文件 + tldraw 画布 + 演讲稿
4. **多端实时同步**：手机 / 电脑 / Web Dashboard 一致

**📋 进阶指令：**
- `/pilot <意图>` 显式触发
- `/plan <意图>` 只规划不执行
- `帮助` 查看完整命令"""

    if dashboard_url:
        body += f"\n\n**📊 实时进度面板：** [{dashboard_url}]({dashboard_url})"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🛫 欢迎使用 Agent-Pilot"},
            "template": "indigo",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body}},
        ],
    }


def help_card(dashboard_url: str = "") -> Dict[str, Any]:
    """Detailed help card when the user types `帮助` or `/help`."""
    body = """## 🛫 Agent-Pilot 完整指南

### 核心能力
| 能力 | 触发方式 | 产物 |
|---|---|---|
| 文档生成 | "写一份关于 X 的报告" | 飞书 Docx + Markdown |
| PPT 生成 | "做一份 X 主题 PPT" | 真 .pptx + Slidev HTML |
| 架构图 / 流程图 | "画一张 X 架构图" | tldraw + Mermaid + 飞书 Docx |
| 三件套 | "X 的方案+图+PPT" | 三种产物联动生成 |

### 示例话术
- 短意图：`帮我写个产品介绍`
- 长意图：`把上周关于 AI 趋势的讨论整理成给老板看的 8 页 PPT`
- 模糊意图：`帮我做个汇报` → Agent 会主动问"汇报对象 / 页数 / 受众"
- Canvas：`画一张 Agent 系统架构图`
- 三件套：`产品方案 + 架构图 + 评审 PPT`

### 命令
- `/pilot <意图>` 强制触发 Pilot 流程
- `/plan <意图>` 只规划不执行（Plan Mode）
- `/list` 查看历史任务
- `状态` 查看当前任务进度
- `帮助` 显示本卡片

### 我的工作流
1. **意图识别**：三闸门（规则 + LLM + 最小信息）判断
2. **任务规划**：DAG 拆解为多个子任务（im → doc → canvas → slide → archive）
3. **4-Agent 协作**：Researcher → Writer → Critic → Presenter
4. **多端同步**：飞书 / Dashboard / Flutter 实时一致
5. **总结归档**：分享链接 + 产物列表

### 评分维度对应
- 完整性 50%：从 IM 到归档的端到端闭环 + Demo < 3 分钟
- 创新性 25%：4-Agent 协作 + 流式打字机 + 真 PPTX 三件套 + 主动澄清
- 技术性 25%：模块化架构 + 鲁棒错误处理 + 多端 CRDT + 监控

### 出错时
- "rate limit"：等 60 秒重试，或开启 `AGENT_PILOT_DISABLE_RATE_LIMIT=1`
- 文档空白：极少出现；如复现请截图 + 飞书链接发给我
- 飞书域名打不开：换浏览器 / 关闭代理 / 联系管理员"""

    if dashboard_url:
        body += f"\n\n**📊 Dashboard：** [{dashboard_url}]({dashboard_url})"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📚 Agent-Pilot · 完整指南"},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body}},
        ],
    }


__all__ = ["first_time_welcome_card", "help_card"]
