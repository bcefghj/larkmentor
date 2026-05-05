"""Tests for the unified exception hierarchy in core/exceptions.py."""

import pytest

from core.exceptions import (
    AgentPilotError,
    ConfigError,
    FeishuAPIError,
    LLMError,
    PlanningError,
    ToolExecutionError,
)


# ---------------------------------------------------------------------------
# AgentPilotError.to_user_message()
# ---------------------------------------------------------------------------

def test_base_error_user_message_is_chinese():
    """to_user_message() should return Chinese-language user-facing text."""
    err = AgentPilotError("internal boom")
    msg = err.to_user_message()
    assert "系统" in msg or "管理员" in msg or "错误" in msg
    assert "AGENT_PILOT_ERROR" in msg


# ---------------------------------------------------------------------------
# AgentPilotError.to_log_dict()
# ---------------------------------------------------------------------------

def test_base_error_log_dict_has_required_keys():
    """to_log_dict() must contain the keys needed by structlog."""
    err = AgentPilotError("something broke", details={"extra": 1})
    d = err.to_log_dict()
    for key in ("error_type", "error_code", "message", "details", "timestamp"):
        assert key in d, f"missing key: {key}"
    assert d["error_type"] == "AgentPilotError"
    assert d["error_code"] == "AGENT_PILOT_ERROR"
    assert d["message"] == "something broke"


def test_base_error_stores_timestamp():
    """AgentPilotError should record an ISO-format timestamp."""
    err = AgentPilotError("ts test")
    assert hasattr(err, "timestamp")
    assert "T" in err.timestamp  # ISO format


# ---------------------------------------------------------------------------
# LLMError stores provider and model info
# ---------------------------------------------------------------------------

def test_llm_error_stores_provider_and_model():
    err = LLMError(
        "timeout",
        provider="volcano_ark",
        model="doubao-seed-2.0-pro",
        retries_attempted=3,
        is_retryable=True,
    )
    assert err.provider == "volcano_ark"
    assert err.model == "doubao-seed-2.0-pro"
    assert err.retries_attempted == 3
    assert err.is_retryable is True


def test_llm_error_user_message_mentions_provider():
    err = LLMError("fail", provider="mimo", model="mimo-v2.5-pro", is_retryable=False)
    msg = err.to_user_message()
    assert "mimo" in msg


def test_llm_error_log_dict_includes_extra_fields():
    err = LLMError("fail", provider="deepseek", model="ds-v3", retries_attempted=2)
    d = err.to_log_dict()
    assert d["provider"] == "deepseek"
    assert d["model"] == "ds-v3"
    assert d["retries_attempted"] == 2


# ---------------------------------------------------------------------------
# ToolExecutionError stores tool_name and step_id
# ---------------------------------------------------------------------------

def test_tool_execution_error_stores_fields():
    err = ToolExecutionError(
        "doc create failed",
        tool_name="doc.create",
        step_id="s1",
        input_summary="title=报告",
    )
    assert err.tool_name == "doc.create"
    assert err.step_id == "s1"
    assert err.input_summary == "title=报告"


def test_tool_execution_error_user_message():
    err = ToolExecutionError("err", tool_name="doc.append")
    msg = err.to_user_message()
    assert "doc.append" in msg


# ---------------------------------------------------------------------------
# PlanningError stores phase and plan_id
# ---------------------------------------------------------------------------

def test_planning_error_stores_fields():
    err = PlanningError("parse failed", phase="intent_detection", plan_id="plan_001")
    assert err.phase == "intent_detection"
    assert err.plan_id == "plan_001"


def test_planning_error_user_message():
    err = PlanningError("bad plan", phase="replan")
    msg = err.to_user_message()
    assert "意图" in msg or "简化" in msg or "重试" in msg


# ---------------------------------------------------------------------------
# FeishuAPIError – 4xx vs 5xx messages
# ---------------------------------------------------------------------------

def test_feishu_error_4xx_message():
    err = FeishuAPIError("forbidden", status_code=403, api_path="/v1/im")
    msg = err.to_user_message()
    assert "权限" in msg or "参数" in msg


def test_feishu_error_5xx_message():
    err = FeishuAPIError("server error", status_code=502, api_path="/v1/im")
    msg = err.to_user_message()
    assert "不可用" in msg or "重试" in msg


def test_feishu_error_unknown_status_message():
    err = FeishuAPIError("weird", status_code=0)
    msg = err.to_user_message()
    assert "飞书" in msg


def test_feishu_error_stores_request_id():
    err = FeishuAPIError("err", status_code=500, request_id="req_abc", api_path="/v1/chat")
    assert err.request_id == "req_abc"
    assert err.api_path == "/v1/chat"


# ---------------------------------------------------------------------------
# Inheritance: all custom exceptions are subclasses of AgentPilotError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [
    LLMError,
    ToolExecutionError,
    PlanningError,
    FeishuAPIError,
    ConfigError,
])
def test_exception_inherits_from_base(cls):
    assert issubclass(cls, AgentPilotError)
    assert issubclass(cls, Exception)


# ---------------------------------------------------------------------------
# Import tests – verify wiring in consumer modules
# ---------------------------------------------------------------------------

def test_llm_client_imports_llm_error():
    """LLMError should be importable in the llm_client context."""
    from llm.llm_client import LLMError as LLMErr  # noqa: F401
    assert LLMErr is LLMError


def test_orchestrator_imports_planning_and_tool_errors():
    """PlanningError and ToolExecutionError should be importable from core.exceptions."""
    from core.exceptions import PlanningError as PE  # noqa: F401
    from core.exceptions import ToolExecutionError as TE  # noqa: F401
    assert PE is PlanningError
    assert TE is ToolExecutionError


# ---------------------------------------------------------------------------
# Repr for debugging
# ---------------------------------------------------------------------------

def test_repr_is_readable():
    err = LLMError("timeout", provider="ark", model="doubao")
    r = repr(err)
    assert "LLMError" in r
    assert "timeout" in r
