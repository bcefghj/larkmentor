"""ReAct Pattern · Reason → Act → Observe loop."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent.patterns.react")


def react_loop(
    question: str, *,
    tools: Dict[str, Callable],
    llm: Callable[[str], str],
    max_iters: int = 5,
) -> Dict[str, Any]:
    """Classic ReAct: loop Reason→Act→Observe until final answer."""
    scratch: List[str] = []
    prompt_template = (
        "You are solving a task using ReAct (Reason, Act, Observe).\n"
        "Available tools: {tools}\n\n"
        "Question: {q}\n\n"
        "Scratch:\n{scratch}\n\n"
        "Respond with either:\n"
        "  THOUGHT: <your reasoning>\n"
        "  ACTION: tool_name(arg1=..., arg2=...)\n"
        "OR\n"
        "  FINAL: <answer>\n"
    )
    for _ in range(max_iters):
        prompt = prompt_template.format(
            q=question, tools=", ".join(tools.keys()),
            scratch="\n".join(scratch),
        )
        out = llm(prompt).strip()
        if out.startswith("FINAL:"):
            return {"answer": out[len("FINAL:"):].strip(), "iters": len(scratch) // 2}
        if "ACTION:" in out:
            action_part = out.split("ACTION:", 1)[1].strip()
            # naive parse: tool(args)
            if "(" in action_part and action_part.endswith(")"):
                name = action_part.split("(", 1)[0].strip()
                args_str = action_part[action_part.index("(") + 1:-1]
                kwargs: Dict[str, Any] = {}
                for part in args_str.split(","):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        kwargs[k.strip()] = v.strip().strip("'\"")
                scratch.append(f"THOUGHT: {out.split('THOUGHT:')[1].split('ACTION:')[0].strip() if 'THOUGHT:' in out else ''}")
                scratch.append(f"ACTION: {action_part}")
                fn = tools.get(name)
                if fn:
                    try:
                        obs = fn(**kwargs)
                        scratch.append(f"OBSERVATION: {str(obs)[:400]}")
                    except Exception as e:
                        scratch.append(f"OBSERVATION: ERROR {e}")
                else:
                    scratch.append(f"OBSERVATION: tool_not_found {name}")
        else:
            scratch.append(f"THOUGHT: {out}")
    return {"answer": scratch[-1] if scratch else "no answer", "iters": max_iters}
