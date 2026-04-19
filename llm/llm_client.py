"""LLM client wrapper around the ARK (Doubao) chat completion API.

LarkMentor v2 (step11): all LLM calls now optionally inject the
``flow_memory.md`` 6-tier hierarchy as the system prompt. This means
Smart Shield 6-dim tie-break and Mentor draft generation share the same
"organisation default knowledge" — one of the 3 工程合体点 declared in
ARCHITECTURE.md §2 原则 3 合体点 1.

Toggles:
- ``LARKMENTOR_AUTO_INJECT_MEMORY`` env var (default "1") enables auto-injection
- Pass ``system=`` keyword to ``chat()`` / ``chat_json()`` to override
- Pass ``user_open_id=`` to scope the User-tier memory file to that user
"""

import json
import logging
import os

from openai import OpenAI

from config import Config

logger = logging.getLogger("flowguard.llm")

_client: "OpenAI" = None
_AUTO_INJECT = os.getenv("LARKMENTOR_AUTO_INJECT_MEMORY", "1") != "0"


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=Config.ARK_API_KEY,
            base_url=Config.ARK_BASE_URL,
        )
    return _client


def _build_system_prompt(
    system: str = "",
    user_open_id: str = "",
    enterprise_id: str = "default",
    workspace_id: str = "default",
    department_id: str = None,
    group_id: str = None,
    session_id: str = None,
) -> str:
    """Resolve the merged 6-tier ``flow_memory.md`` and merge with caller's system text.

    Always returns a string (possibly empty); never raises.
    """
    if not _AUTO_INJECT and not system:
        return ""
    pieces = []
    if _AUTO_INJECT:
        try:
            from core.flow_memory.flow_memory_md import resolve_memory_md
            md = resolve_memory_md(
                enterprise_id=enterprise_id,
                workspace_id=workspace_id,
                department_id=department_id,
                group_id=group_id,
                user_open_id=user_open_id or None,
                session_id=session_id,
            )
            if md:
                pieces.append("## 组织默契知识 (FlowMemory 6-tier)\n\n" + md)
        except Exception as e:
            logger.debug("memory inject skipped: %s", e)
    if system:
        pieces.append(system)
    return "\n\n".join(pieces)


def chat(
    prompt: str,
    temperature: float = 0.3,
    *,
    system: str = "",
    user_open_id: str = "",
    enterprise_id: str = "default",
    workspace_id: str = "default",
    department_id: str = None,
    group_id: str = None,
    session_id: str = None,
) -> str:
    """Chat completion with optional 6-tier memory auto-injection.

    Backwards compatible: existing callers passing only ``prompt`` continue
    to work unchanged. Memory injection is on by default but skipped if the
    resolver returns empty (no md tier files exist for this user yet).
    """
    try:
        client = _get_client()
        messages = []
        sys_text = _build_system_prompt(
            system=system, user_open_id=user_open_id,
            enterprise_id=enterprise_id, workspace_id=workspace_id,
            department_id=department_id, group_id=group_id,
            session_id=session_id,
        )
        if sys_text:
            messages.append({"role": "system", "content": sys_text})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=Config.ARK_MODEL,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return ""


def chat_json(
    prompt: str,
    temperature: float = 0.1,
    *,
    system: str = "",
    user_open_id: str = "",
    enterprise_id: str = "default",
    workspace_id: str = "default",
    department_id: str = None,
    group_id: str = None,
    session_id: str = None,
) -> dict:
    """Call LLM and parse the response as JSON. Same memory-inject options as ``chat``."""
    raw = chat(
        prompt, temperature,
        system=system, user_open_id=user_open_id,
        enterprise_id=enterprise_id, workspace_id=workspace_id,
        department_id=department_id, group_id=group_id, session_id=session_id,
    )
    if not raw:
        return {}
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON: %s", raw[:200])
        return {}
