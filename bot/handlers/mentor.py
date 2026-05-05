"""Mentor/coaching features – rookie mode, writing review, task clarify, onboarding, KB, growth."""

import logging
import time as _time

from bot.card_builder import (
    mentor_clarify_card,
    mentor_growth_card,
    mentor_review_card,
    mentor_weekly_card,
)
from bot.message_sender import send_card, send_text
from core.mentor import (
    growth_doc as v4_growth,
    knowledge_base as v4_kb,
    mentor_onboard,
    mentor_review as v4_weekly,
    mentor_router as v4_router,
    mentor_task as v4_task,
    mentor_write as v4_write,
    proactive_hook as v4_proactive,
)
from memory.user_state import add_org_doc

logger = logging.getLogger("flowguard.handler.mentor")

# All mentor-related command names
MENTOR_COMMANDS = frozenset(
    {
        "start_rookie",
        "stop_rookie",
        "rookie_review",
        "rookie_task",
        "rookie_weekly",
        "kb_import",
        "kb_import_wiki",
        "kb_search",
        "kb_list",
        "kb_delete_source",
        "mentor_route",
        "proactive_on",
        "proactive_off",
        "show_growth",
        "show_growth_week",
        "weekly_report",
        "monthly_wrapped",
        "show_memory",
        "delete_my_data",
        "onboard_reset",
        "onboard_show",
        "learn_doc",
    }
)


def handle_mentor_command(command: str, args: dict, open_id: str, user, text: str) -> bool:
    """Handle a mentor-related command. Returns True if handled."""
    if command not in MENTOR_COMMANDS:
        return False

    handler = _DISPATCH.get(command)
    if handler:
        handler(args, open_id, user, text)
        return True
    return False


def handle_onboarding_in_progress(open_id: str, text: str) -> bool:
    """If user is mid-onboarding, consume the message as an answer. Returns True if handled."""
    if not mentor_onboard.is_in_progress(open_id):
        return False

    if text.strip() in ("跳过入职", "skip onboarding"):
        mentor_onboard.reset(open_id)
        send_text(open_id, "已跳过 onboarding。可随时发 `开启新人模式` 重新触发。")
        return True

    sess, just_done = mentor_onboard.submit_answer(open_id, text)
    if just_done:
        send_text(
            open_id,
            "🎉 **MentorOnboard 完成**\n\n"
            + mentor_onboard.render_summary(sess)
            + "\n\n这些信息已自动入库，后续 Mentor 出手会优先参考。",
        )
    else:
        q = sess.next_question
        if q is not None:
            send_text(
                open_id,
                f"✓ 已记录\n\n🤝 **MentorOnboard（{sess.progress}）**\n[{q['dim']}] {q['label']}",
            )
    return True


# ── Individual command handlers ──


def _cmd_start_rookie(args, open_id, user, text):
    user.rookie_mode = True
    send_text(
        open_id,
        "✨ **LarkMentor 新人模式已开启**\n\n"
        "表达层带教 4 个 Skill：\n"
        "📝 `帮我看看：消息内容` · MentorWrite（消息起草：NVC + 3 版改写 + 风险）\n"
        "📋 `任务确认：任务描述` · MentorTask（任务澄清：模糊度打分 + 澄清问题）\n"
        "🤝 `重新入职` · MentorOnboard（新人入职：5 问知识沉淀）\n"
        "📊 `写周报：本周内容` · MentorReview（周报回顾：STAR 引用周报）\n\n"
        "🤖 `@Mentor xxx` · 自动路由（写作/任务/复盘/入职）\n"
        "📚 `导入文档：xxx` · 入库到组织 RAG（自动 PII 扫描）\n"
        "🔍 `查询知识：xxx` · 验证 RAG 召回\n"
        "🛎 `开启主动建议` / `关闭主动建议`\n"
        "📓 `我的成长档案` · 拿 Docx 链接 · `我的入职信息` 看 onboarding",
    )
    try:
        token = v4_growth.ensure_growth_doc(open_id)
        if token:
            send_text(open_id, "📓 已为你创建《我的新手成长记录》Docx，发送 `我的成长档案` 拿链接。")
    except Exception:
        pass
    try:
        if not mentor_onboard.is_in_progress(open_id):
            sess = mentor_onboard.start(open_id)
            if not sess.completed:
                q = sess.next_question
                if q is not None:
                    send_text(
                        open_id,
                        f"🤝 **MentorOnboard 团队融入流（{sess.progress}）**\n\n"
                        f"[{q['dim']}] {q['label']}\n\n"
                        f"（直接回复你的答案即可；不想做发 `跳过入职` 退出）",
                    )
    except Exception as e:
        logger.debug("onboard_start_skipped err=%s", e)


def _cmd_stop_rookie(args, open_id, user, text):
    user.rookie_mode = False
    send_text(open_id, "新人模式已关闭。Mentor 主动建议也已暂停。")


def _cmd_rookie_review(args, open_id, user, text):
    msg = args.get("message", "")
    if not msg:
        send_text(open_id, "请在 `帮我看看：` 后面输入你要审核的消息内容。")
        return
    review = v4_write.review(open_id, msg)
    send_card(open_id, mentor_review_card(review.to_dict()))
    try:
        v4_growth.append_entry(
            open_id,
            kind="writing",
            original=msg,
            improved=review.three_versions.get("neutral", msg),
            citations=review.citations,
        )
    except Exception as e:
        logger.debug("growth_append_skipped err=%s", e)


def _cmd_rookie_task(args, open_id, user, text):
    task = args.get("task", "")
    if not task:
        send_text(open_id, "请在 `任务确认：` 后面输入任务描述。")
        return
    clarif = v4_task.clarify(open_id, task)
    send_card(open_id, mentor_clarify_card(clarif.to_dict()))
    try:
        improved = (
            "; ".join(clarif.suggested_questions)
            if clarif.needs_clarification
            else f"{clarif.task_understanding} | {clarif.delivery_plan}"
        )
        v4_growth.append_entry(
            open_id,
            kind="task",
            original=task,
            improved=improved,
            citations=clarif.citations,
        )
    except Exception:
        pass


def _cmd_rookie_weekly(args, open_id, user, text):
    content = args.get("content", "")
    wk = v4_weekly.draft(open_id, user_meta=content[:120] if content else "")
    send_card(open_id, mentor_weekly_card(wk.to_dict()))


def _cmd_kb_import(args, open_id, user, text):
    content = args.get("content", "")
    if not content:
        send_text(open_id, "请在 `导入文档：` 后面贴入文档内容。")
        return
    res = v4_kb.import_text(open_id, source=f"manual_{int(_time.time())}.md", text=content)
    if res.ok:
        send_text(open_id, f"✅ 已导入 {res.chunks_added} 段。Mentor 后续回答会自动引用此文档。")
    else:
        if res.rejected_reason == "pii_detected":
            send_text(
                open_id,
                f"⚠️ 检测到敏感信息（{', '.join(res.pii_kinds)}），未入库。请手动去敏后再试。",
            )
        else:
            send_text(open_id, f"导入失败：{res.rejected_reason}")


def _cmd_kb_import_wiki(args, open_id, user, text):
    url = args.get("url", "")
    send_text(
        open_id,
        f"📚 正在尝试拉取 wiki：{url}\n\n"
        "⚠️ 飞书 Wiki API 权限需企业管理员审批，目前 v4 提供降级路径："
        "请用 `导入文档：内容` 手动粘贴文档内容。",
    )


def _cmd_kb_search(args, open_id, user, text):
    q = args.get("query", "")
    hits = v4_kb.search(open_id, q)
    if not hits:
        send_text(open_id, f"知识库无命中：{q}\n（可能尚未导入相关文档）")
        return
    lines = [f"**Top {len(hits)} 命中**（method={hits[0].method}）:\n"]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {h.citation_tag()} score={h.score:.3f}")
        lines.append(f"   {h.chunk.text[:120]}")
    send_text(open_id, "\n".join(lines))


def _cmd_kb_list(args, open_id, user, text):
    sources = v4_kb.list_sources(open_id)
    if not sources:
        send_text(open_id, "知识库为空。发送 `导入文档：xxx` 入库。")
        return
    lines = [f"📚 **你的知识库**（{len(sources)} 个文档）\n"]
    for s in sources:
        ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(s["last_ts"]))
        lines.append(f"- `{s['source']}` · {s['chunks']} 段 · {ts_str}")
    lines.append("\n删除单个文档：`删除知识：<source>`；全部清空：`删除我的数据`")
    send_text(open_id, "\n".join(lines))


def _cmd_kb_delete_source(args, open_id, user, text):
    src = args.get("source", "")
    if not src:
        send_text(open_id, "请在 `删除知识：` 后面跟文档名。先发 `知识库列表` 看可选项。")
        return
    n = v4_kb.delete_source(open_id, src)
    if n > 0:
        send_text(open_id, f"✅ 已删除 `{src}` 共 {n} 段。其它文档保留。")
    else:
        send_text(open_id, f"未找到 `{src}`。先发 `知识库列表` 确认源名。")


def _cmd_mentor_route(args, open_id, user, text):
    text_in = args.get("input", "")
    if not text_in:
        send_text(open_id, "请在 `@Mentor` 后面输入你的问题。")
        return
    decision = v4_router.route(text_in)
    if decision.role == "writing":
        review = v4_write.review(open_id, text_in)
        send_card(open_id, mentor_review_card(review.to_dict()))
    elif decision.role == "task":
        clarif = v4_task.clarify(open_id, text_in)
        send_card(open_id, mentor_clarify_card(clarif.to_dict()))
    elif decision.role == "weekly":
        wk = v4_weekly.draft(open_id)
        send_card(open_id, mentor_weekly_card(wk.to_dict()))
    else:
        send_text(
            open_id,
            f"Mentor 路由：{decision.role}（{decision.method}/{decision.confidence:.2f}）\n"
            f"理由：{decision.why}\n\n"
            "如需具体能力，请直接发：`帮我看看:` / `任务确认:` / `写周报:`",
        )


def _cmd_proactive_on(args, open_id, user, text):
    v4_proactive.set_enabled(user, True)
    send_text(open_id, "✅ 已开启 Mentor 主动建议。收到 P0/P1 时会私聊 3 版回复（5min 频控 / 24h 上限 3 次）。")


def _cmd_proactive_off(args, open_id, user, text):
    v4_proactive.set_enabled(user, False)
    send_text(open_id, "🔕 已关闭 Mentor 主动建议。你仍可主动用 `帮我看看：` 或 `@Mentor` 调用。")


def _cmd_show_growth(args, open_id, user, text):
    from core.mentor.growth_doc import load_entries

    week = load_entries(open_id, since_ts=int(_time.time()) - 7 * 86400)
    total = load_entries(open_id)
    doc_url = ""
    if user.growth_doc_token:
        doc_url = f"https://feishu.cn/docx/{user.growth_doc_token}"
    send_card(
        open_id,
        mentor_growth_card(
            week_count=len(week),
            total_count=len(total),
            doc_url=doc_url,
        ),
    )


def _cmd_show_growth_week(args, open_id, user, text):
    from core.mentor.growth_doc import load_entries

    week = load_entries(open_id, since_ts=int(_time.time()) - 7 * 86400)
    if not week:
        send_text(open_id, "本周暂无 Mentor 出手记录。")
        return
    lines = [f"📓 **本周 {len(week)} 条 Mentor 记录**\n"]
    for e in week[-10:]:
        ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(e.ts))
        lines.append(f"- [{ts_str}] [{e.kind}] {e.original[:40]} → {e.improved[:40]}")
    send_text(open_id, "\n".join(lines))


def _cmd_weekly_report(args, open_id, user, text):
    send_text(open_id, "正在基于你的工作记忆生成本周周报，请稍候...")
    try:
        from core.work_review.weekly_report import generate_weekly_report as gen_weekly

        report = gen_weekly(open_id, publish=True)
        header = (
            f"📋 **本周周报**（{report.stats.get('focus_count', 0)} 次专注 · "
            f"{report.stats.get('focus_minutes', 0)} 分钟）\n\n"
        )
        send_text(open_id, header + report.body_md)
    except Exception as e:
        logger.exception("weekly_report error: %s", e)
        send_text(open_id, f"周报生成失败：{e}")


def _cmd_monthly_wrapped(args, open_id, user, text):
    send_text(open_id, "正在生成月度 Wrapped 卡片...")
    try:
        from core.work_review.monthly_wrapped import generate_monthly_wrapped

        card_data = generate_monthly_wrapped(open_id, days=30)
        lines = [f"🎵 **{card_data.headline}**\n"]
        for b in card_data.bullets:
            lines.append(f"• {b}")
        lines.append("\n📊 统计：")
        for k, v in card_data.stats.items():
            lines.append(f"  - {k}: {v}")
        send_text(open_id, "\n".join(lines))
    except Exception as e:
        logger.exception("monthly_wrapped error: %s", e)
        send_text(open_id, f"月报生成失败：{e}")


def _cmd_show_memory(args, open_id, user, text):
    try:
        from core.flow_memory.archival import query_archival
        from core.flow_memory.working import WorkingMemory

        wm = WorkingMemory.load(open_id)
        recent_events = wm.recent(n=10)
        archived = query_archival(open_id, limit=5)

        lines = ["🧠 **我的记忆**\n"]
        lines.append(f"**工作记忆**（最近 {len(wm.events)}/{wm.capacity} 条事件）：")
        if recent_events:
            for ev in recent_events[-5:]:
                ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(ev.ts))
                payload_preview = str(ev.payload)[:60] if ev.payload else ""
                lines.append(f"  [{ts_str}] {ev.kind}: {payload_preview}")
        else:
            lines.append("  （暂无事件）")

        lines.append(f"\n**长期归档**（最近 {len(archived)} 条摘要）：")
        if archived:
            for a in archived:
                ts_str = _time.strftime("%m-%d %H:%M", _time.localtime(a.ts))
                lines.append(f"  [{ts_str}] ({a.kind}) {a.summary_md[:80]}")
        else:
            lines.append("  （暂无归档摘要）")

        send_text(open_id, "\n".join(lines))
    except Exception as e:
        logger.exception("show_memory error: %s", e)
        send_text(open_id, f"记忆查询失败：{e}")


def _cmd_delete_my_data(args, open_id, user, text):
    send_text(
        open_id,
        "⚠️ 确认删除你的所有数据？包括工作记忆、归档摘要、发送方画像。\n\n请在 30 秒内回复 `确认删除` 执行操作。",
    )


def _cmd_onboard_reset(args, open_id, user, text):
    mentor_onboard.reset(open_id)
    send_text(open_id, "已清空 onboarding。发送 `开启新人模式` 重新走 5 问入职流。")


def _cmd_onboard_show(args, open_id, user, text):
    sess = mentor_onboard.get_session(open_id)
    if sess is None or not sess.answers:
        send_text(open_id, "暂无 onboarding 记录。发送 `开启新人模式` 触发 5 问入职流。")
        return
    send_text(open_id, mentor_onboard.render_summary(sess))


def _cmd_learn_doc(args, open_id, user, text):
    content = args.get("content", "")
    if not content:
        send_text(open_id, "请在 `学习文档：` 后面输入文档内容或风格样本。")
        return
    add_org_doc(content)
    send_text(open_id, f"已学习文档内容（{len(content)}字）。新人模式的建议会参考此风格。")


# Command dispatch table
_DISPATCH = {
    "start_rookie": _cmd_start_rookie,
    "stop_rookie": _cmd_stop_rookie,
    "rookie_review": _cmd_rookie_review,
    "rookie_task": _cmd_rookie_task,
    "rookie_weekly": _cmd_rookie_weekly,
    "kb_import": _cmd_kb_import,
    "kb_import_wiki": _cmd_kb_import_wiki,
    "kb_search": _cmd_kb_search,
    "kb_list": _cmd_kb_list,
    "kb_delete_source": _cmd_kb_delete_source,
    "mentor_route": _cmd_mentor_route,
    "proactive_on": _cmd_proactive_on,
    "proactive_off": _cmd_proactive_off,
    "show_growth": _cmd_show_growth,
    "show_growth_week": _cmd_show_growth_week,
    "weekly_report": _cmd_weekly_report,
    "monthly_wrapped": _cmd_monthly_wrapped,
    "show_memory": _cmd_show_memory,
    "delete_my_data": _cmd_delete_my_data,
    "onboard_reset": _cmd_onboard_reset,
    "onboard_show": _cmd_onboard_show,
    "learn_doc": _cmd_learn_doc,
}
