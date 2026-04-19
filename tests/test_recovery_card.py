"""Tests for core/recovery_card.py (LarkMentor v2 双线 UI 唯一交点)"""

from __future__ import annotations

import time

import pytest


def _make_user_with_blocked(open_id="u_test_recovery"):
    """Helper: seed working_memory with 4 blocked messages of mixed levels."""
    from core.flow_memory.working import WorkingMemory, WorkingEvent
    wm = WorkingMemory.load(open_id)
    wm.events = []
    base_ts = int(time.time()) - 1000

    seeds = [
        ("张三", "u1", "紧急：方案需要立刻确认", "P0", 0.95, "私聊", base_ts + 50),
        ("李四", "u2", "今天能给我反馈吗", "P1", 0.78, "私聊", base_ts + 200),
        ("工程群", "g1", "周五的会议改到三点", "P2", 0.52, "工程群", base_ts + 350),
        ("noisy", "u3", "FYI 行业新闻分享", "P3", 0.10, "群通知", base_ts + 600),
    ]
    for name, sid, content, lvl, score, chat, ts in seeds:
        wm.append(WorkingEvent(
            ts=ts,
            kind="message",
            payload={
                "sender_name": name,
                "sender_id": sid,
                "content": content,
                "level": lvl,
                "score": score,
                "chat_name": chat,
                "message_id": f"m_{sid}_{ts}",
            },
        ))
    wm.save()
    return open_id, base_ts


def test_collect_blocked_messages_sorts_by_priority_and_excludes_p3():
    from core.recovery_card import collect_blocked_messages

    open_id, base_ts = _make_user_with_blocked()
    blocked = collect_blocked_messages(open_id, base_ts)

    assert len(blocked) == 3
    assert blocked[0].level == "P0"
    assert blocked[1].level == "P1"
    assert blocked[2].level == "P2"
    assert all(m.level != "P3" for m in blocked)


def test_collect_blocked_messages_respects_max_n():
    from core.recovery_card import collect_blocked_messages

    open_id, base_ts = _make_user_with_blocked()
    blocked = collect_blocked_messages(open_id, base_ts, max_n=2)
    assert len(blocked) == 2


def test_pick_top_message_returns_p0():
    from core.recovery_card import collect_blocked_messages, pick_top_message

    open_id, base_ts = _make_user_with_blocked()
    blocked = collect_blocked_messages(open_id, base_ts)
    top = pick_top_message(blocked)
    assert top is not None
    assert top.level == "P0"
    assert top.sender_name == "张三"


def test_pick_top_message_empty_returns_none():
    from core.recovery_card import pick_top_message
    assert pick_top_message([]) is None


def test_blocked_message_relative_time():
    from core.recovery_card import BlockedMessage
    now = int(time.time())
    m = BlockedMessage(
        sender_name="x", sender_id="y", content="hi",
        level="P1", score=0.5, ts=now - 30,
    )
    s = m.relative_time(now)
    assert "秒前" in s


def test_blocked_message_short_content():
    from core.recovery_card import BlockedMessage
    long = "一二三四五" * 30
    m = BlockedMessage(
        sender_name="x", sender_id="y", content=long,
        level="P1", score=0.5, ts=0,
    )
    assert len(m.short_content(10)) <= 13


def test_draft_three_versions_falls_back_when_llm_unavailable():
    from core.recovery_card import draft_three_versions, BlockedMessage

    msg = BlockedMessage(
        sender_name="王经理", sender_id="u9",
        content="麻烦看下方案", level="P0", score=0.9, ts=0,
    )
    drafts = draft_three_versions("u_test", msg)
    assert len(drafts) == 3
    tones = [d.tone for d in drafts]
    assert tones == ["conservative", "neutral", "direct"]
    for d in drafts:
        assert d.text.strip()
        assert d.label in ("保守", "中性", "直接")


def test_build_recovery_context_full_pipeline():
    from core.recovery_card import build_recovery_context

    open_id, base_ts = _make_user_with_blocked()
    ctx = build_recovery_context(
        open_id,
        focus_start_ts=base_ts,
        focus_end_ts=base_ts + 2700,
    )
    assert ctx.user_open_id == open_id
    assert ctx.focus_duration_sec == 2700
    assert len(ctx.blocked) == 3
    assert ctx.top_message is not None
    assert ctx.top_message.level == "P0"
    assert len(ctx.drafts_for_top) == 3
    assert "P0" in ctx.explanation


def test_build_recovery_context_skip_drafts():
    from core.recovery_card import build_recovery_context

    open_id, base_ts = _make_user_with_blocked()
    ctx = build_recovery_context(
        open_id,
        focus_start_ts=base_ts,
        include_drafts=False,
    )
    assert ctx.drafts_for_top == []


def test_render_recovery_card_has_double_line_layout():
    from core.recovery_card import build_recovery_context, render_recovery_card

    open_id, base_ts = _make_user_with_blocked()
    ctx = build_recovery_context(open_id, focus_start_ts=base_ts)
    card = render_recovery_card(ctx)

    assert "config" in card
    assert "header" in card
    assert "elements" in card

    txt = str(card)
    assert "我替你挡了什么" in txt
    assert "我替你起草了回复" in txt
    assert "永不自动发送" in txt

    has_action = any(el.get("tag") == "action" for el in card["elements"])
    assert has_action

    actions = [el for el in card["elements"] if el.get("tag") == "action"][0]["actions"]
    btn_texts = [b["text"]["content"] for b in actions]
    assert any("采纳" in t for t in btn_texts)
    assert any("忽略" in t for t in btn_texts)


def test_render_recovery_card_empty_blocked_still_renders():
    from core.recovery_card import RecoveryContext, render_recovery_card

    ctx = RecoveryContext(
        user_open_id="u_empty",
        focus_duration_sec=600,
    )
    card = render_recovery_card(ctx)
    txt = str(card)
    assert "没有需要你看的消息" in txt
    assert "暂无需要回复的紧急消息" in txt


def test_send_recovery_card_uses_injected_sender():
    from core.recovery_card import send_recovery_card

    open_id, base_ts = _make_user_with_blocked()
    captured = {}

    def fake_sender(receive_id, card):
        captured["receive_id"] = receive_id
        captured["card"] = card
        return True

    ok, ctx = send_recovery_card(
        open_id,
        focus_start_ts=base_ts,
        sender=fake_sender,
    )

    assert ok is True
    assert captured["receive_id"] == open_id
    assert "elements" in captured["card"]
    assert ctx.top_message is not None
