"""Build Feishu interactive message cards for all FlowGuard scenarios."""

from utils.time_utils import fmt_duration


def _header(title: str, color: str = "blue") -> dict:
    return {
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        }
    }


def _md(text: str) -> dict:
    return {"tag": "div", "text": {"tag": "lark_md", "content": text}}


def _divider() -> dict:
    return {"tag": "hr"}


def _buttons(*buttons) -> dict:
    return {"tag": "action", "actions": list(buttons)}


def _btn(label: str, value: dict, style: str = "default") -> dict:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": style,
        "value": value,
    }


def focus_started_card(duration_min: int = 0) -> dict:
    dur_text = f"（时长：{duration_min}分钟）" if duration_min else "（无限时长）"
    card = _header("保护模式已开启", "blue")
    card["elements"] = [
        _md(f"FlowGuard 已进入深度专注保护{dur_text}\n\n"
            "**消息处理策略：**\n"
            "- P0 紧急消息 - 立即推送\n"
            "- P1 重要消息 - 攒批提醒\n"
            "- P2 一般消息 - 智能代回复\n"
            "- P3 闲聊广播 - 静默归档"),
        _divider(),
        _buttons(
            _btn("结束专注", {"action": "end_focus"}, "danger"),
            _btn("查看状态", {"action": "show_status"}),
        ),
    ]
    return card


def urgent_alert_card(sender: str, content: str, chat_name: str) -> dict:
    card = _header("紧急消息", "red")
    card["elements"] = [
        _md(f"**来自：** {sender}\n**频道：** {chat_name}\n\n"
            f"**内容：**\n{content[:200]}"),
        _divider(),
        _md("此消息被判定为 P0 紧急级别，已突破保护模式推送。"),
    ]
    return card


def batch_reminder_card(messages: list) -> dict:
    card = _header("待查看消息汇总", "wathet")
    lines = []
    for i, m in enumerate(messages[:10], 1):
        lines.append(f"{i}. **[{m['sender']}]** {m['content'][:50]}")
    card["elements"] = [
        _md("\n".join(lines) if lines else "暂无待查看消息"),
        _divider(),
        _md(f"共 {len(messages)} 条消息在专注期间被暂存"),
    ]
    return card


def recovery_card(stats: dict, recovery_text: str) -> dict:
    dur = fmt_duration(stats.get("duration_sec", 0))
    total = stats.get("total_messages", 0)
    p0 = stats.get("p0_count", 0)
    p1 = stats.get("p1_count", 0)
    p2 = stats.get("p2_count", 0)
    p3 = stats.get("p3_count", 0)

    card = _header("工作恢复提示", "green")
    card["elements"] = [
        _md(f"**专注时长：** {dur}\n"
            f"**期间消息：** 共 {total} 条\n"
            f"- 紧急已推送：{p0} 条\n"
            f"- 待查看：{p1} 条\n"
            f"- 已代回复：{p2} 条\n"
            f"- 已归档：{p3} 条"),
        _divider(),
        _md(f"**恢复建议：**\n{recovery_text}"),
        _divider(),
        _buttons(
            _btn("继续专注", {"action": "start_focus"}, "primary"),
            _btn("查看今日报告", {"action": "daily_report"}),
        ),
    ]
    return card


def daily_report_card(
    total_interrupts: int,
    p0: int, p1: int, p2: int, p3: int,
    focus_seconds: int,
    shielded: int,
    advice: str = "",
) -> dict:
    focus_dur = fmt_duration(focus_seconds)
    saved_min = shielded * 2

    card = _header("FlowGuard 今日报告", "purple")
    card["elements"] = [
        _md(f"**今日消息统计：**\n"
            f"- 总消息数：{total_interrupts}\n"
            f"- P0 紧急：{p0}\n"
            f"- P1 重要：{p1}\n"
            f"- P2 代回复：{p2}\n"
            f"- P3 归档：{p3}"),
        _divider(),
        _md(f"**深度工作时长：** {focus_dur}\n"
            f"**FlowGuard 帮你拦截：** {shielded} 条消息\n"
            f"**预估节省：** 约 {saved_min} 分钟注意力恢复时间"),
        _divider(),
        _md(f"**建议：** {advice}" if advice else
            "**建议：** 尝试在下午 2-4 点设置专注时段，减少深度工作被切碎。"),
    ]
    return card


def help_card() -> dict:
    card = _header("FlowGuard v3 使用指南", "indigo")
    card["elements"] = [
        _md("**专注保护：**\n"
            "- `开始专注` / `专注 90 分钟` — 进入保护模式\n"
            "- `结束专注` — 退出保护模式\n"
            "- `今天的状态` / `状态` — 查看当前状态\n"
            "- `今日报告` — 查看打断分析"),
        _divider(),
        _md("**v3 新功能：**\n"
            "- `本周周报` / `周报` — 基于工作记忆自动生成周报\n"
            "- `月报` / `wrapped` — 月度 Wrapped 卡片\n"
            "- `我的记忆` — 查看工作记忆与归档摘要\n"
            "- `撤回最近决策` — 一键撤回上一条 AI 决策\n"
            "- `删除我的数据` — 清除所有个人数据"),
        _divider(),
        _md("**白名单管理：**\n"
            "- `白名单 张三` — 添加白名单\n"
            "- `移除白名单 张三` — 移除\n"
            "- `白名单列表` — 查看"),
        _divider(),
        _md("**工作台 & 决策：**\n"
            "- `演示工作台` — 自动创建飞书多维表格 + 文档\n"
            "- `我的工作台` — 查看已有工作台\n"
            "- `最近决策` — 查看 AI 决策记录\n"
            "- `为什么 决策ID` — 查看 6 维评分详情\n"
            "- `回滚 决策ID P0` — 手动纠正分级"),
        _divider(),
        _md("**多任务 & 新人模式：**\n"
            "- `添加任务：任务名` / `切换任务：任务名` / `任务列表`\n"
            "- `开启新人模式` — 启用表达优化\n"
            "- `帮我看看：消息` / `写周报：内容`"),
    ]
    return card


def rookie_review_card(
    original: str, risk_level: str, risk_desc: str, improved: str, explanation: str,
) -> dict:
    color_map = {"low": "green", "medium": "orange", "high": "red"}
    level_text = {"low": "低风险", "medium": "中风险", "high": "高风险"}

    card = _header("消息审核结果", color_map.get(risk_level, "blue"))
    card["elements"] = [
        _md(f"**风险等级：** {level_text.get(risk_level, risk_level)}"),
    ]
    if risk_desc:
        card["elements"].append(_md(f"**问题：** {risk_desc}"))
    card["elements"].extend([
        _divider(),
        _md(f"**原文：**\n{original}"),
        _divider(),
        _md(f"**优化版本：**\n{improved}"),
        _divider(),
        _md(explanation),
    ])
    return card


def achievement_card(achievement_name: str, achievement_desc: str) -> dict:
    card = _header("解锁新成就!", "yellow")
    card["elements"] = [
        _md(f"**{achievement_name}**\n{achievement_desc}"),
        _divider(),
        _md("继续保持！深度工作是最稀缺的能力。"),
    ]
    return card


def achievements_list_card(unlocked: list, all_defs: list) -> dict:
    card = _header("我的成就", "indigo")
    lines = []
    for a in all_defs:
        if a["id"] in unlocked:
            lines.append(f"[已解锁] **{a['name']}** — {a['desc']}")
        else:
            lines.append(f"[未解锁] {a['name']} — {a['desc']}")
    card["elements"] = [
        _md("\n".join(lines)),
    ]
    return card


def workspace_welcome_card(bitable_url: str, onboarding_url: str, recovery_url: str, complete: bool = True) -> dict:
    """The judge-friendly welcome card showing the auto-provisioned workspace."""
    card = _header("欢迎使用 FlowGuard - 你的专属飞书工作台已就绪", "turquoise")
    if complete:
        body = (
            "我已经为你在飞书里**自动开通了 3 个资源**：\n\n"
            f"📊 [我的打断分析看板（多维表格）]({bitable_url})\n"
            "  已预置 10 条演示数据，点开即可看到完整看板\n\n"
            f"📘 [FlowGuard 使用指南（飞书文档）]({onboarding_url})\n"
            "  5 分钟读完，了解所有用法\n\n"
            f"📝 [上下文恢复卡片（动态文档）]({recovery_url})\n"
            "  每次结束专注，我会在这里追加一张恢复卡片\n\n"
            "—— 点开任意一个，开始体验。"
        )
    else:
        body = (
            "已为你创建欢迎流程。部分高级资源（多维表格 / 文档）创建未完全成功，\n"
            "可能是应用权限尚未审批。你可以：\n\n"
            "1. 直接发送 `开始专注` 体验核心能力\n"
            "2. 给应用补全 `bitable:app` / `docx:document` 权限后\n"
            "   发送 `演示工作台` 重新生成"
        )
    card["elements"] = [
        _md(body),
        _divider(),
        _buttons(
            _btn("开始专注", {"action": "start_focus"}, "primary"),
            _btn("帮助", {"action": "help"}),
        ),
    ]
    return card


def first_time_welcome_card() -> dict:
    """Lightweight first-touch welcome before workspace provisioning."""
    card = _header("FlowGuard - 智能工作状态守护", "blue")
    card["elements"] = [
        _md(
            "你好！我是 FlowGuard，飞书生态中第一个**保护工作状态**的智能 Agent。\n\n"
            "**核心能力**\n"
            "- Smart Shield - 6 维消息智能分级\n"
            "- Flow Detector - 自动识别专注状态\n"
            "- Context Recall - 被打断后帮你找回上下文\n"
            "- Rookie Buddy - 新人沟通辅导\n\n"
            "**第一次使用？** 发送 `演示工作台`，我会自动给你创建多维表格 + 使用指南。\n"
            "**老用户？** 发送 `开始专注` 直接进入保护模式。\n"
            "**完整指令？** 发送 `帮助`。"
        ),
        _divider(),
        _buttons(
            _btn("演示工作台", {"action": "demo_workspace"}, "primary"),
            _btn("开始专注", {"action": "start_focus"}),
            _btn("帮助", {"action": "help"}),
        ),
    ]
    return card


# ── v4 Mentor cards ──────────────────────────────────────────────────────────


_RISK_TEMPLATE = {"low": "green", "medium": "yellow", "high": "red"}
_RISK_LABEL = {"low": "🟢 低风险", "medium": "🟡 中风险", "high": "🔴 高风险"}


def _risk_bar(risk_level: str) -> str:
    risk_level = (risk_level or "low").lower()
    return _RISK_LABEL.get(risk_level, "🟢 低风险")


def mentor_review_card(review_dict: dict, draft_id: str = "") -> dict:
    """Card for the writing mentor output (3 versions + NVC + risk)."""
    risk = (review_dict.get("risk_level") or "low").lower()
    color = _RISK_TEMPLATE.get(risk, "blue")
    card = _header("Mentor · 写作建议", color)

    versions = review_dict.get("three_versions") or {}
    nvc = review_dict.get("nvc_diagnosis") or {}
    citations = review_dict.get("citations") or []

    risk_block = (
        f"**风险**：{_risk_bar(risk)}\n"
        + (f"**问题**：{review_dict.get('risk_description','')}\n"
           if review_dict.get("risk_description") else "")
    )

    nvc_block = ""
    if any(nvc.values()):
        nvc_block = (
            "\n**NVC 诊断**\n"
            f"- 事实：{nvc.get('observation','')[:80]}\n"
            f"- 感受：{nvc.get('feeling','')[:80]}\n"
            f"- 需求：{nvc.get('need','')[:80]}\n"
            f"- 请求：{nvc.get('request','')[:80]}\n"
        )

    versions_block = (
        "\n**3 版改写**\n"
        f"🔵 **保守版**\n{versions.get('conservative','')}\n\n"
        f"🟢 **中性版**\n{versions.get('neutral','')}\n\n"
        f"🟠 **直接版**\n{versions.get('direct','')}\n"
    )

    why = review_dict.get("explanation", "")
    cite_block = ""
    if citations:
        cite_block = "\n**引用**：" + " ".join(citations[:3])

    card["elements"] = [
        _md(risk_block + nvc_block + versions_block + (f"\n💡 {why}" if why else "") + cite_block),
        _divider(),
        _buttons(
            _btn("用保守版", {"action": "mentor_pick", "ver": "conservative", "id": draft_id}),
            _btn("用中性版", {"action": "mentor_pick", "ver": "neutral", "id": draft_id}, "primary"),
            _btn("用直接版", {"action": "mentor_pick", "ver": "direct", "id": draft_id}),
        ),
    ]
    return card


def mentor_clarify_card(task_dict: dict, draft_id: str = "") -> dict:
    """Card for the task mentor output (clarification questions or plan)."""
    needs = bool(task_dict.get("needs_clarification"))
    color = "yellow" if needs else "turquoise"
    title = "Mentor · 建议先澄清" if needs else "Mentor · 任务理解就绪"
    card = _header(title, color)

    ambiguity = float(task_dict.get("ambiguity", 0.0))
    bar_filled = int(min(10, max(0, ambiguity * 10)))
    bar = "🟧" * bar_filled + "⬜" * (10 - bar_filled)
    missing = task_dict.get("missing_dims") or []
    missing_text = "、".join(missing) if missing else "无"

    head = (
        f"**模糊度**：{bar} {ambiguity:.2f}\n"
        f"**缺失维度**：{missing_text}\n"
    )

    if needs:
        questions = task_dict.get("suggested_questions") or []
        body = "\n**建议先问对方**\n" + "\n".join(
            f"{i+1}. {q}" for i, q in enumerate(questions[:2])
        )
        actions = _buttons(
            _btn("我已确认", {"action": "mentor_clarified", "id": draft_id}, "primary"),
            _btn("不需要澄清", {"action": "mentor_skip_clarify", "id": draft_id}),
        )
    else:
        understanding = task_dict.get("task_understanding", "")
        plan = task_dict.get("delivery_plan", "")
        risks = task_dict.get("risks") or []
        body = (
            f"\n**我的理解**\n{understanding}\n\n"
            f"**交付计划**\n{plan}\n"
        )
        if risks:
            body += "\n**风险点**\n" + "\n".join(f"- {r}" for r in risks[:3])
        actions = _buttons(
            _btn("立即开工", {"action": "mentor_start_task", "id": draft_id}, "primary"),
            _btn("再问一下", {"action": "mentor_back_to_clarify", "id": draft_id}),
        )

    citations = task_dict.get("citations") or []
    cite_block = ""
    if citations:
        cite_block = "\n\n**引用**：" + " ".join(citations[:3])

    card["elements"] = [
        _md(head + body + cite_block),
        _divider(),
        actions,
    ]
    return card


def mentor_weekly_card(weekly_dict: dict) -> dict:
    """Card for the weekly STAR draft."""
    card = _header("Mentor · 本周周报草稿（STAR）", "indigo")
    body = weekly_dict.get("body_md") or "（暂无）"
    citations = weekly_dict.get("citations") or []
    used_star = bool(weekly_dict.get("used_star", False))

    head = "**STAR 校验**：" + ("✅ 通过" if used_star else "⚠️ 部分缺失") + "\n"
    if citations:
        head += f"**引用**：{len(citations)} 条 archival 摘要\n"
    head += "\n"

    card["elements"] = [
        _md(head + body),
        _divider(),
        _buttons(
            _btn("追加到成长档案", {"action": "mentor_append_growth", "kind": "weekly"}, "primary"),
            _btn("重新生成", {"action": "mentor_regen_weekly"}),
        ),
    ]
    return card


def mentor_growth_card(week_count: int, total_count: int, doc_url: str = "") -> dict:
    """Card linking to the user's growth journal Docx."""
    card = _header("Mentor · 我的成长档案", "violet")
    if doc_url:
        body = (
            f"📓 [打开《我的新手成长记录》]({doc_url})\n\n"
            f"**本周条目**：{week_count}\n"
            f"**累计条目**：{total_count}\n\n"
            "本档案由 FlowGuard 自动维护——每次 Mentor 出手都会追加一条；"
            "每周日 21:00 会自动写一段成长摘要。"
        )
    else:
        body = (
            "成长档案尚未创建（飞书 docx 权限可能未审批）。\n\n"
            "你可以发送 `开启新人模式` 让我尝试再创建一次；"
            "或者使用 `查看本周成长` 查看本地条目。"
        )
    card["elements"] = [
        _md(body),
        _divider(),
        _buttons(
            _btn("查看本周成长", {"action": "mentor_show_growth_week"}, "primary"),
            _btn("关闭主动建议", {"action": "mentor_proactive_off"}),
            _btn("开启主动建议", {"action": "mentor_proactive_on"}),
        ),
    ]
    return card


def mentor_proactive_card(suggestion: dict, draft_id: str = "") -> dict:
    """Card pushed when LarkMentor proactively suggests reply versions."""
    sender = suggestion.get("sender_name", "")
    chat_name = suggestion.get("chat_name", "")
    level = suggestion.get("level", "P1")
    original = (suggestion.get("original") or "")[:120]
    versions = suggestion.get("three_versions") or {}
    citations = suggestion.get("citations") or []
    explain = suggestion.get("explain", "")  # LarkMentor v1: explainable line

    color = "red" if level == "P0" else "orange"
    card = _header(f"Mentor · 建议回复（{level}）", color)

    head = (
        f"**来自**：{sender} · {chat_name}\n"
        f"**原文**：{original}\n\n"
        "🤖 **Mentor 起草了 3 版回复**（你点确认才会发出，LarkMentor 不会替你发）：\n\n"
        f"🔵 **保守版**\n{versions.get('conservative','')}\n\n"
        f"🟢 **中性版**\n{versions.get('neutral','')}\n\n"
        f"🟠 **直接版**\n{versions.get('direct','')}\n"
    )

    if explain:
        head += f"\n**为什么主动出手**：{explain}"

    if citations:
        head += "\n**引用**：" + " ".join(citations[:3])

    card["elements"] = [
        _md(head),
        _divider(),
        _buttons(
            _btn("用保守版", {"action": "mentor_pick_proactive", "ver": "conservative", "id": draft_id}),
            _btn("用中性版", {"action": "mentor_pick_proactive", "ver": "neutral", "id": draft_id}, "primary"),
            _btn("用直接版", {"action": "mentor_pick_proactive", "ver": "direct", "id": draft_id}),
            _btn("不需要", {"action": "mentor_dismiss_proactive", "id": draft_id}),
        ),
    ]
    return card
