"""Tests for the 3-tier prompt cache in llm/llm_client.py."""

from unittest.mock import patch

import pytest

import llm.llm_client as lc


# ---------------------------------------------------------------------------
# Tier 1: _get_tier1()
# ---------------------------------------------------------------------------

def test_tier1_returns_nonempty_string():
    result = lc._get_tier1()
    assert isinstance(result, str)
    assert len(result) > 0


def test_tier1_contains_agent_pilot():
    """Tier 1 role definition must mention Agent-Pilot."""
    result = lc._get_tier1()
    assert "Agent-Pilot" in result


def test_tier1_is_cached():
    """Calling _get_tier1() twice should store exactly one 'tier1' key."""
    lc._get_tier1()
    lc._get_tier1()
    assert "tier1" in lc._prompt_cache


# ---------------------------------------------------------------------------
# Tier 2: _get_tier2() caching
# ---------------------------------------------------------------------------

def test_tier2_caches_results():
    """Calling _get_tier2() twice with same params returns the same object."""
    with patch("llm.llm_client._AUTO_INJECT", False):
        first = lc._get_tier2(user_open_id="ou_test", enterprise_id="e1")
        second = lc._get_tier2(user_open_id="ou_test", enterprise_id="e1")
    assert first is second


def test_tier2_different_users_get_different_cache_keys():
    """Different user_open_id values should produce different cache keys."""
    with patch("llm.llm_client._AUTO_INJECT", False):
        lc._get_tier2(user_open_id="ou_aaa")
        lc._get_tier2(user_open_id="ou_bbb")
    tier2_keys = [k for k in lc._prompt_cache if k.startswith("tier2:")]
    assert len(tier2_keys) >= 2


# ---------------------------------------------------------------------------
# Tier 3: _get_tier3()
# ---------------------------------------------------------------------------

def test_tier3_includes_injection_guard():
    """Tier 3 must contain the injection guard text."""
    result = lc._get_tier3()
    assert "安全边界" in result


def test_tier3_includes_caller_system():
    """When caller_system is provided, it should appear in tier 3 output."""
    result = lc._get_tier3(caller_system="你是一个文档助手")
    assert "文档助手" in result
    assert "安全边界" in result


def test_tier3_without_caller_system():
    """Without caller_system, tier 3 should still have the guard."""
    result = lc._get_tier3(caller_system="")
    assert "安全边界" in result
    assert result.strip().startswith("[安全边界]") or "安全边界" in result


# ---------------------------------------------------------------------------
# invalidate_prompt_cache()
# ---------------------------------------------------------------------------

def test_invalidate_removes_all_tier2():
    """invalidate_prompt_cache() with no args removes all tier2 entries."""
    lc._prompt_cache["tier1"] = "stable"
    lc._prompt_cache["tier2:e1:w1:ou_a:None"] = "session_a"
    lc._prompt_cache["tier2:e1:w1:ou_b:None"] = "session_b"

    lc.invalidate_prompt_cache()

    assert "tier1" in lc._prompt_cache
    assert not any(k.startswith("tier2:") for k in lc._prompt_cache)


def test_invalidate_by_user_only_removes_matching():
    """invalidate_prompt_cache(user_open_id='ou_123') only removes matching keys."""
    lc._prompt_cache["tier2:e1:w1:ou_123:None"] = "yes"
    lc._prompt_cache["tier2:e1:w1:ou_456:None"] = "no"

    lc.invalidate_prompt_cache(user_open_id="ou_123")

    assert "tier2:e1:w1:ou_123:None" not in lc._prompt_cache
    assert "tier2:e1:w1:ou_456:None" in lc._prompt_cache


# ---------------------------------------------------------------------------
# _build_system_prompt() combines all tiers
# ---------------------------------------------------------------------------

def test_build_system_prompt_combines_tiers():
    """_build_system_prompt() should include tier1 role and tier3 guard."""
    with patch("llm.llm_client._AUTO_INJECT", False):
        prompt = lc._build_system_prompt(system="自定义系统文本")
    assert "Agent-Pilot" in prompt
    assert "安全边界" in prompt
    assert "自定义系统文本" in prompt


def test_build_system_prompt_without_system_text():
    """Even without a caller system, build should return tier1 + tier3."""
    with patch("llm.llm_client._AUTO_INJECT", False):
        prompt = lc._build_system_prompt()
    assert "Agent-Pilot" in prompt
    assert "安全边界" in prompt


# ---------------------------------------------------------------------------
# Cache population after first call
# ---------------------------------------------------------------------------

def test_cache_populated_after_first_call():
    """After _build_system_prompt(), the cache should have tier1 + tier2 entries."""
    assert len(lc._prompt_cache) == 0

    with patch("llm.llm_client._AUTO_INJECT", False):
        lc._build_system_prompt(user_open_id="ou_pop_test")

    assert "tier1" in lc._prompt_cache
    tier2_keys = [k for k in lc._prompt_cache if k.startswith("tier2:")]
    assert len(tier2_keys) >= 1


def test_tier1_cached_across_calls():
    """Tier1 value should be populated once and reused."""
    with patch("llm.llm_client._AUTO_INJECT", False):
        lc._build_system_prompt()

    tier1_val = lc._prompt_cache.get("tier1")
    assert tier1_val is not None

    with patch("llm.llm_client._AUTO_INJECT", False):
        lc._build_system_prompt()

    assert lc._prompt_cache["tier1"] is tier1_val
