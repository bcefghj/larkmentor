"""V1.5 IntentRouter 5 闸门完整覆盖测试."""

from __future__ import annotations

import pytest

from pilot.runtime.intent_router import (
    ChatMessage,
    CooldownStore,
    IntentRouter,
    IntentVerdict,
    LLMJudgement,
)


@pytest.mark.asyncio
async def test_g1_command_help() -> None:
    r = await IntentRouter().detect([ChatMessage("u1", "帮助", "c1")])
    assert r.verdict == IntentVerdict.COMMAND
    assert r.command_kind == "help"


@pytest.mark.asyncio
async def test_g1_command_status_slash() -> None:
    r = await IntentRouter().detect([ChatMessage("u1", "/status", "c1")])
    assert r.verdict == IntentVerdict.COMMAND
    assert r.command_kind == "status"


@pytest.mark.asyncio
async def test_g1_command_claim_chinese() -> None:
    r = await IntentRouter().detect([ChatMessage("u1", "我来执行", "c1")])
    assert r.verdict == IntentVerdict.COMMAND
    assert r.command_kind == "claim"


@pytest.mark.asyncio
async def test_g2_explicit_pilot_prefix() -> None:
    r = await IntentRouter().detect([ChatMessage("u1", "/pilot 写个文档", "c1")])
    assert r.verdict == IntentVerdict.READY
    assert "explicit_pilot" in r.rule_hits


@pytest.mark.asyncio
async def test_g3_strong_form_with_topic_short_circuit() -> None:
    """强 form 词 + 主题（OpenClaw）即使没动词也直接 READY."""
    r = await IntentRouter().detect([ChatMessage("u1", "OpenClaw 三件套", "c1")])
    assert r.verdict == IntentVerdict.READY


@pytest.mark.asyncio
async def test_g3_timely_word_sets_web_search_flag() -> None:
    r = await IntentRouter().detect([ChatMessage("u1", "今年最新 AI Agent 进展报告", "c1")])
    assert r.verdict == IntentVerdict.READY
    assert r.needs_web_search is True


@pytest.mark.asyncio
async def test_g3_form_word_alone_falls_through_to_clarify() -> None:
    """单出 form 词、无主题、无 LLM → NEEDS_CLARIFY 避免空启."""
    r = await IntentRouter().detect([ChatMessage("u1", "帮我做个 PPT", "c1")])
    assert r.verdict == IntentVerdict.NEEDS_CLARIFY


@pytest.mark.asyncio
async def test_g4_llm_ready_overrides() -> None:
    async def fake(text, history):
        return LLMJudgement(verdict="ready", is_task=True, summary="任务概要", confidence=0.9)

    r = await IntentRouter(llm_judge=fake).detect([ChatMessage("u1", "搞个东西", "c1")])
    assert r.verdict == IntentVerdict.READY
    assert r.llm_judgement is not None


@pytest.mark.asyncio
async def test_g4_llm_clarify_with_missing_fields() -> None:
    async def fake(text, history):
        return LLMJudgement(verdict="clarify", is_task=True, missing=["audience", "form"])

    r = await IntentRouter(llm_judge=fake).detect([ChatMessage("u1", "需要个东西", "c1")])
    assert r.verdict == IntentVerdict.NEEDS_CLARIFY
    assert any("给谁看" in q for q in r.clarify_questions)
    assert any("文档" in q for q in r.clarify_questions)


@pytest.mark.asyncio
async def test_g4_llm_chat_returns_friendly_reply() -> None:
    async def fake(text, history):
        return LLMJudgement(verdict="chat", friendly_reply="哈哈，我不会算命")

    r = await IntentRouter(llm_judge=fake).detect([ChatMessage("u1", "明天股市涨吗", "c1")])
    assert r.verdict == IntentVerdict.CHAT
    assert r.chat_reply == "哈哈，我不会算命"


@pytest.mark.asyncio
async def test_g4_llm_timeout_falls_to_g5() -> None:
    async def boom(text, history):
        raise TimeoutError("8s")

    r = await IntentRouter(llm_judge=boom).detect([ChatMessage("u1", "你好", "c1")])
    # greeting 命中 G5 闲聊兜底
    assert r.verdict == IntentVerdict.CHAT
    assert "你好" in r.chat_reply or "Agent-Pilot" in r.chat_reply


@pytest.mark.asyncio
async def test_g5_greeting_fallback() -> None:
    r = await IntentRouter().detect([ChatMessage("u1", "Hi", "c1")])
    assert r.verdict == IntentVerdict.CHAT


@pytest.mark.asyncio
async def test_g5_unknown_text_never_silent() -> None:
    """未识别也不沉默，给 CHAT 引导."""
    r = await IntentRouter().detect([ChatMessage("u1", "我啦啦啦", "c1")])
    assert r.verdict == IntentVerdict.CHAT
    assert r.chat_reply  # 必有回复


@pytest.mark.asyncio
async def test_cooldown_p2p_short() -> None:
    cd = CooldownStore(p2p_cooldown_sec=10, group_cooldown_sec=300)
    router = IntentRouter(cooldown=cd)
    history = [ChatMessage("u1", "OpenClaw 三件套", "c1")]
    r1 = await router.detect(history, is_p2p=True)
    assert r1.verdict == IntentVerdict.READY
    r2 = await router.detect(history, is_p2p=True)
    assert r2.verdict == IntentVerdict.COOLDOWN


@pytest.mark.asyncio
async def test_empty_message_returns_not_intent() -> None:
    r = await IntentRouter().detect([ChatMessage("u1", "  ", "c1")])
    assert r.verdict == IntentVerdict.NOT_INTENT
