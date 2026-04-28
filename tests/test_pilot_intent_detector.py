"""P3 · IntentDetector 三闸门测试 (PRD §5 + Q5).

20+ 用例覆盖：
- 规则层 keyword / semantic / time / resource / multi-speaker
- LLM judge JSON 解析容错
- 冷却 + 忽略
- 三闸门完整流转：READY / NEEDS_CLARIFY / NOT_INTENT / COOLDOWN / IGNORED
"""
from __future__ import annotations

import json

import pytest

from core.agent_pilot.application import (
    ChatMessage,
    CooldownManager,
    IntentDetector,
    IntentDetectorConfig,
    IntentVerdict,
)
from core.agent_pilot.application.intent_detector import (
    LLMJudgement,
    detect_rules,
    rule_passes,
    _parse_llm_response,
)


# ── 闸门 1: 规则层 ─────────────────────────────────────────────────────────


def _msg(sender: str, text: str, chat: str = "g1") -> ChatMessage:
    return ChatMessage(sender_open_id=sender, text=text, chat_id=chat, ts=0)


def test_rule_hit_pure_keyword():
    msgs = [_msg("u1", "下周需要做个 PPT 给老板看")]
    hit = detect_rules(msgs)
    assert hit.score >= 0.4
    assert any("下周" in s for s in [w for w in hit.keyword_hits if "下周" in w]) or hit.has_time_signal


def test_rule_hit_no_keyword():
    msgs = [_msg("u1", "今天天气不错")]
    hit = detect_rules(msgs)
    assert hit.score < 0.4


def test_rule_hit_multi_speaker():
    msgs = [
        _msg("u1", "下周要做活动复盘汇报"),
        _msg("u2", "对，给老板看的"),
        _msg("u3", "我有数据"),
    ]
    hit = detect_rules(msgs)
    assert hit.multi_speaker
    assert hit.score >= 0.5


def test_rule_hit_resource_signal():
    msgs = [_msg("u1", "把这个 https://feishu.cn/doc/abc 整理一下")]
    hit = detect_rules(msgs)
    assert hit.has_resource_signal
    assert hit.score >= 0.4


def test_rule_hit_time_signal():
    msgs = [_msg("u1", "下周要做汇报")]
    hit = detect_rules(msgs)
    assert hit.has_time_signal


def test_rule_passes_threshold():
    high = detect_rules([_msg("u1", "下周做个 PPT 汇报给老板，资料在 https://x.com/y.docx")])
    low = detect_rules([_msg("u1", "嗯")])
    assert rule_passes(high)
    assert not rule_passes(low)


def test_rule_handles_empty_messages():
    hit = detect_rules([])
    assert hit.score == 0


def test_rule_keyword_english():
    msgs = [_msg("u1", "We need a deck for next monday")]
    hit = detect_rules(msgs)
    assert hit.score >= 0.2  # 部分英文关键词命中


# ── 闸门 2: LLM JSON 解析 ──────────────────────────────────────────────────


def test_parse_llm_clean_json():
    raw = json.dumps({
        "is_task": True,
        "task_type": "ppt",
        "goal": "活动复盘汇报",
        "resources": ["历史复盘", "预算表"],
        "next_step": "确认 owner",
        "confidence": 0.85,
    })
    j = _parse_llm_response(raw)
    assert j.is_task
    assert j.task_type == "ppt"
    assert j.goal == "活动复盘汇报"
    assert "历史复盘" in j.resources
    assert j.confidence == 0.85


def test_parse_llm_with_markdown_fence():
    raw = "```json\n{\"is_task\": true, \"goal\": \"x\", \"confidence\": 0.7}\n```"
    j = _parse_llm_response(raw)
    assert j.is_task
    assert j.goal == "x"


def test_parse_llm_with_leading_garbage():
    raw = "Here is the result:\n{\"is_task\": false, \"goal\": \"\", \"confidence\": 0.1}"
    j = _parse_llm_response(raw)
    assert not j.is_task
    assert j.confidence == 0.1


def test_parse_llm_empty_returns_default():
    j = _parse_llm_response("")
    assert not j.is_task
    assert j.confidence == 0.0


def test_parse_llm_garbled():
    j = _parse_llm_response("not a json at all")
    assert not j.is_task


# ── 冷却 + 忽略 ────────────────────────────────────────────────────────────


def test_cooldown_basic():
    cd = CooldownManager(default_cooldown_sec=3600)
    cd.mark_fired("g1", "活动复盘汇报")
    assert cd.is_cooling("g1", "活动复盘汇报")
    assert cd.is_cooling("g1", "活动复盘 汇报")  # normalize 后相同
    assert not cd.is_cooling("g1", "其他主题")


def test_cooldown_cross_chat_independent():
    cd = CooldownManager()
    cd.mark_fired("g1", "复盘汇报")
    assert not cd.is_cooling("g2", "复盘汇报")


def test_ignore_list():
    cd = CooldownManager()
    cd.mark_ignored("g1", "活动复盘汇报")
    assert cd.is_ignored("g1", "活动复盘汇报")


def test_cooldown_reset():
    cd = CooldownManager()
    cd.mark_fired("g1", "x")
    cd.mark_ignored("g1", "y")
    cd.reset()
    assert not cd.is_cooling("g1", "x")
    assert not cd.is_ignored("g1", "y")


# ── IntentDetector 主入口（mock LLM） ───────────────────────────────────────


def _mock_llm_yes(text: str) -> str:
    return json.dumps({
        "is_task": True, "task_type": "ppt",
        "goal": "活动复盘汇报", "resources": ["数据"],
        "next_step": "确认", "confidence": 0.88,
    })


def _mock_llm_no(text: str) -> str:
    return json.dumps({
        "is_task": False, "task_type": "other",
        "goal": "", "resources": [], "next_step": "", "confidence": 0.10,
    })


def _mock_llm_lowconf(text: str) -> str:
    return json.dumps({
        "is_task": True, "task_type": "report",
        "goal": "校园活动", "resources": [],
        "next_step": "需更多信息", "confidence": 0.30,
    })


def _mock_llm_empty(text: str) -> str:
    return ""


def test_detect_full_ready():
    det = IntentDetector(llm_caller=_mock_llm_yes)
    msgs = [
        _msg("u1", "下周做活动复盘汇报"),
        _msg("u2", "对，给老板"),
        _msg("u3", "我有数据"),
    ]
    res = det.detect(msgs)
    assert res.verdict == IntentVerdict.READY
    assert res.suggested_title
    assert res.suggested_owner == "u3"  # 最后一条发言者


def test_detect_not_intent_when_llm_says_no():
    det = IntentDetector(llm_caller=_mock_llm_no)
    msgs = [_msg("u1", "下周做活动复盘汇报")]
    res = det.detect(msgs)
    assert res.verdict == IntentVerdict.NOT_INTENT


def test_detect_not_intent_no_keywords():
    det = IntentDetector(llm_caller=_mock_llm_yes)
    msgs = [_msg("u1", "今天天气不错")]
    res = det.detect(msgs)
    assert res.verdict == IntentVerdict.NOT_INTENT  # 闸门 1 没过


def test_detect_clarify_when_lowconf():
    det = IntentDetector(llm_caller=_mock_llm_lowconf)
    msgs = [_msg("u1", "下周做汇报")]
    res = det.detect(msgs)
    assert res.verdict == IntentVerdict.NEEDS_CLARIFY
    assert len(res.clarify_questions) >= 1


def test_detect_cooldown_blocks_repeat():
    det = IntentDetector(llm_caller=_mock_llm_yes)
    msgs = [_msg("u1", "下周做活动复盘汇报", chat="g1")]
    r1 = det.detect(msgs)
    assert r1.verdict == IntentVerdict.READY
    # 模拟弹卡后 mark_fired
    det.cooldown.mark_fired(r1.chat_id, r1.theme_key)
    r2 = det.detect(msgs)
    assert r2.verdict == IntentVerdict.COOLDOWN


def test_detect_ignore_blocks_repeat():
    det = IntentDetector(llm_caller=_mock_llm_yes)
    msgs = [_msg("u1", "下周做活动复盘汇报", chat="g1")]
    r1 = det.detect(msgs)
    det.cooldown.mark_ignored(r1.chat_id, r1.theme_key)
    r2 = det.detect(msgs)
    assert r2.verdict == IntentVerdict.IGNORED


def test_detect_degrade_when_llm_empty():
    """LLM 返回空时 → fall back: 当前实现下 LLM judge.is_task=False 视为 NOT_INTENT.

    若想要规则强命中即触发，可设 enable_llm=False."""
    det = IntentDetector(llm_caller=_mock_llm_empty)
    msgs = [_msg("u1", "下周做活动复盘汇报")]
    res = det.detect(msgs)
    assert res.verdict == IntentVerdict.NOT_INTENT


def test_detect_disable_llm_means_rule_only():
    cfg = IntentDetectorConfig(enable_llm=False)
    det = IntentDetector(config=cfg, llm_caller=_mock_llm_empty)
    msgs = [
        _msg("u1", "下周做个 PPT 汇报给老板"),
        _msg("u2", "对"),
    ]
    res = det.detect(msgs)
    # rule_only mode: passes rule + llm.is_task=True forced + confidence=0.6 (>0.55) -> READY
    assert res.verdict == IntentVerdict.READY


def test_detect_empty_messages():
    det = IntentDetector(llm_caller=_mock_llm_yes)
    res = det.detect([])
    assert res.verdict == IntentVerdict.NOT_INTENT
