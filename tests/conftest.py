"""Root-level shared fixtures for Agent-Pilot test suite.

Provides commonly needed mocks, config overrides, and test data builders
so individual test files stay focused on assertions.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("FEISHU_APP_ID", "test_app_id")
os.environ.setdefault("FEISHU_APP_SECRET", "test_app_secret")
os.environ.setdefault("PYTHONPATH", str(ROOT))


@pytest.fixture(autouse=True)
def _reset_llm_clients():
    """Reset singleton LLM clients between tests."""
    import llm.llm_client as lc
    old_client = lc._client
    old_async = lc._async_client
    old_cache = dict(lc._prompt_cache)
    lc._client = None
    lc._async_client = None
    lc._prompt_cache.clear()
    yield
    lc._client = old_client
    lc._async_client = old_async
    lc._prompt_cache.clear()
    lc._prompt_cache.update(old_cache)


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client that returns predictable responses."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Mock LLM response"
    mock_resp.choices[0].message.tool_calls = None
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp
    return mock_client


@pytest.fixture
def mock_async_openai_client():
    """Mock AsyncOpenAI client."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Mock async LLM response"
    mock_resp.choices[0].message.tool_calls = None

    mock_client = AsyncMock()
    mock_client.chat.completions.create.return_value = mock_resp
    return mock_client


@pytest.fixture
def mock_config():
    """Override Config with test values."""
    with patch.multiple(
        "config.Config",
        MIMO_API_KEY="test_mimo_key",
        MIMO_BASE_URL="http://localhost:8888/v1",
        MIMO_MODEL="test-model",
        ARK_API_KEY="",
        MINIMAX_API_KEY="",
        FEISHU_APP_ID="test_app",
        FEISHU_APP_SECRET="test_secret",
        VERSION="12.0.0",
    ):
        yield


@pytest.fixture
def sample_plan_data():
    """Build a minimal DomainPlan for testing orchestrator logic."""
    return {
        "plan_id": "plan_test_001",
        "intent": "生成一份关于 AI 的文档",
        "steps": [
            {
                "step_id": "s1",
                "tool": "doc.create",
                "description": "创建文档",
                "args": {"title": "AI Report"},
                "depends_on": [],
                "status": "pending",
            },
            {
                "step_id": "s2",
                "tool": "doc.append",
                "description": "写入内容",
                "args": {"markdown": ""},
                "depends_on": ["s1"],
                "status": "pending",
            },
        ],
    }


@pytest.fixture
def sample_messages():
    """Sample Feishu-style IM messages for intent detection tests."""
    return [
        {"sender_open_id": "ou_abc123", "text": "帮我做一个季度汇报 PPT"},
        {"sender_open_id": "ou_def456", "text": "好的，内容包括销售数据和市场分析"},
        {"sender_open_id": "ou_abc123", "text": "对，重点突出 Q3 增长"},
    ]


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory with common subdirs."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "pilot_artifacts").mkdir()
    return tmp_path
