"""Reflection Pattern · Self-critique + iterate."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("agent.patterns.reflection")


def reflect_and_improve(
    initial_output: str, *,
    task: str,
    llm: Callable[[str], str],
    max_iters: int = 3,
    quality_threshold: float = 0.8,
) -> Dict[str, Any]:
    """Iteratively refine via self-critique."""
    current = initial_output
    for i in range(max_iters):
        critique_prompt = (
            f"Task: {task}\n\n"
            f"Current answer:\n{current}\n\n"
            f"Critique this answer rigorously. Respond as JSON:\n"
            f'{{"score": 0.0-1.0, "issues": ["..."], "improvement": "..."}}\n'
        )
        critique = llm(critique_prompt)
        try:
            import json
            data = json.loads(critique.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
            score = float(data.get("score", 0))
            if score >= quality_threshold:
                return {"answer": current, "iterations": i + 1, "final_score": score}
            improve_prompt = (
                f"Task: {task}\n\n"
                f"Previous answer: {current}\n\n"
                f"Issues: {data.get('issues', [])}\n"
                f"Improvement guidance: {data.get('improvement', '')}\n\n"
                f"Write an improved answer:"
            )
            current = llm(improve_prompt)
        except Exception as e:
            logger.debug("reflection parse failed: %s", e)
            break
    return {"answer": current, "iterations": max_iters, "final_score": None}
