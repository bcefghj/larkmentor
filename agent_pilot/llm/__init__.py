"""Agent-Pilot v13 LLM layer.

The actual provider client lives at ``llm.llm_client`` (top-level package, kept
for backwards compatibility). This submodule adds robustness helpers (safe JSON
parsing, few-shot prompt assembly) used by the v13 runtime.
"""

from agent_pilot.llm.safe_json import safe_json_parse  # noqa: F401

__all__ = ["safe_json_parse"]
