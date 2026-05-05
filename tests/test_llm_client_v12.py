"""Tests for the refactored llm/llm_client.py (v12)."""

import json
from unittest.mock import MagicMock, patch

import pytest

import llm.llm_client as lc
from core.exceptions import LLMError


# ---------------------------------------------------------------------------
# chat() with mock OpenAI client
# ---------------------------------------------------------------------------

def test_chat_returns_content(mock_openai_client):
    """chat() should return the content from the mocked completion."""
    with patch.object(lc, "_get_client", return_value=mock_openai_client):
        result = lc.chat("你好")
    assert result == "Mock LLM response"
    mock_openai_client.chat.completions.create.assert_called_once()


def test_chat_returns_empty_on_failure():
    """chat() catches exceptions and returns empty string."""
    broken = MagicMock()
    broken.chat.completions.create.side_effect = RuntimeError("boom")
    with patch.object(lc, "_get_client", return_value=broken), \
         patch.object(lc, "_LLM_MAX_RETRY", 0):
        result = lc.chat("hello")
    assert result == ""


# ---------------------------------------------------------------------------
# chat_stream() yields chunks
# ---------------------------------------------------------------------------

def test_chat_stream_yields_chunks():
    """chat_stream() should yield content deltas from the streaming response."""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "Hello"

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta.content = " world"

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])

    with patch.object(lc, "_get_client", return_value=mock_client):
        chunks = list(lc.chat_stream("测试"))
    assert chunks == ["Hello", " world"]


def test_chat_stream_yields_fallback_on_error():
    """On exception, chat_stream yields LLM_FALLBACK_MSG."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("timeout")

    with patch.object(lc, "_get_client", return_value=mock_client):
        chunks = list(lc.chat_stream("测试"))
    assert chunks == [lc.LLM_FALLBACK_MSG]


# ---------------------------------------------------------------------------
# chat_json() parsing
# ---------------------------------------------------------------------------

def test_chat_json_parses_json(mock_openai_client):
    """chat_json() should parse a plain JSON response."""
    mock_openai_client.chat.completions.create.return_value.choices[
        0
    ].message.content = '{"key": "value"}'
    with patch.object(lc, "_get_client", return_value=mock_openai_client):
        result = lc.chat_json("返回JSON")
    assert result == {"key": "value"}


def test_chat_json_handles_markdown_fences(mock_openai_client):
    """chat_json() should strip ```json ... ``` fences before parsing."""
    mock_openai_client.chat.completions.create.return_value.choices[
        0
    ].message.content = '```json\n{"a": 1}\n```'
    with patch.object(lc, "_get_client", return_value=mock_openai_client):
        result = lc.chat_json("返回JSON")
    assert result == {"a": 1}


def test_chat_json_returns_empty_dict_on_invalid_json(mock_openai_client):
    """chat_json() returns {} when the LLM response is not valid JSON."""
    mock_openai_client.chat.completions.create.return_value.choices[
        0
    ].message.content = "这不是JSON"
    with patch.object(lc, "_get_client", return_value=mock_openai_client):
        result = lc.chat_json("返回JSON")
    assert result == {}


# ---------------------------------------------------------------------------
# _cap_prompt()
# ---------------------------------------------------------------------------

def test_cap_prompt_truncates_long_text():
    """_cap_prompt() should truncate prompts exceeding the char cap."""
    long_text = "A" * 50_000
    result = lc._cap_prompt(long_text)
    assert len(result) < len(long_text)
    assert "已裁剪" in result


def test_cap_prompt_leaves_short_text_unchanged():
    """_cap_prompt() should not modify short prompts."""
    short = "短文本"
    assert lc._cap_prompt(short) == short


# ---------------------------------------------------------------------------
# _wrap_user_input()
# ---------------------------------------------------------------------------

def test_wrap_user_input():
    """_wrap_user_input() wraps text in <user_input> tags."""
    result = lc._wrap_user_input("hello")
    assert result.startswith("<user_input>")
    assert result.endswith("</user_input>")
    assert "hello" in result


# ---------------------------------------------------------------------------
# _build_system_prompt()
# ---------------------------------------------------------------------------

def test_build_system_prompt_includes_tier1():
    """_build_system_prompt() result must contain the tier1 role definition."""
    prompt = lc._build_system_prompt()
    assert "Agent-Pilot" in prompt


# ---------------------------------------------------------------------------
# invalidate_prompt_cache()
# ---------------------------------------------------------------------------

def test_invalidate_prompt_cache_clears_tier2():
    """invalidate_prompt_cache() should remove all tier2 entries."""
    lc._prompt_cache["tier2:default:default:ou_a:None"] = "cached"
    lc._prompt_cache["tier2:default:default:ou_b:None"] = "cached2"
    lc._prompt_cache["tier1"] = "stable"

    lc.invalidate_prompt_cache()

    assert "tier1" in lc._prompt_cache
    assert not any(k.startswith("tier2:") for k in lc._prompt_cache)


# ---------------------------------------------------------------------------
# _select_provider() – MiMo first
# ---------------------------------------------------------------------------

def test_select_provider_returns_mimo_first():
    """_select_provider() should prefer MiMo when its key is configured."""
    with patch("config.Config.MIMO_API_KEY", "test_mimo_key", create=True), \
         patch("config.Config.MIMO_BASE_URL", "http://localhost:8888/v1", create=True):
        api_key, base_url = lc._select_provider()
    assert api_key == "test_mimo_key"
    assert "localhost" in base_url


# ---------------------------------------------------------------------------
# get_active_model()
# ---------------------------------------------------------------------------

def test_get_active_model_returns_mimo_model():
    """get_active_model() should return the MiMo model when MiMo is active."""
    with patch("config.Config.MIMO_API_KEY", "test_mimo_key", create=True), \
         patch("config.Config.MIMO_MODEL", "test-model", create=True):
        model = lc.get_active_model()
    assert model == "test-model"


def test_get_active_model_fallback():
    """Without any provider keys, get_active_model() returns default doubao model."""
    with patch.multiple(
        "config.Config",
        MIMO_API_KEY="",
        ARK_API_KEY="",
        MINIMAX_API_KEY="",
    ):
        model = lc.get_active_model()
    assert model == "doubao-seed-2.0-pro"


# ---------------------------------------------------------------------------
# _sync_retry raises LLMError after exhaustion
# ---------------------------------------------------------------------------

def test_sync_retry_raises_llm_error_on_exhaustion():
    """_sync_retry should raise LLMError after all retries are exhausted."""
    call_count = 0

    def _failing():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("always fails")

    with patch.object(lc, "_LLM_MAX_RETRY", 1), \
         patch("time.sleep"):
        with pytest.raises(LLMError) as exc_info:
            lc._sync_retry(_failing, "test")

    assert call_count == 2  # initial + 1 retry
    assert exc_info.value.is_retryable is False


def test_sync_retry_returns_on_success():
    """_sync_retry returns immediately when the function succeeds."""
    result = lc._sync_retry(lambda: "ok", "test")
    assert result == "ok"


# ---------------------------------------------------------------------------
# LLM_FALLBACK_MSG
# ---------------------------------------------------------------------------

def test_fallback_msg_is_nonempty_string():
    """LLM_FALLBACK_MSG must be a non-empty string."""
    assert isinstance(lc.LLM_FALLBACK_MSG, str)
    assert len(lc.LLM_FALLBACK_MSG) > 0
