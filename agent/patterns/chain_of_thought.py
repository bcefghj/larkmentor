"""Chain-of-Thought Pattern · Step-by-step reasoning with confidence tracking."""

from __future__ import annotations

from typing import Callable, Dict


def cot_reason(question: str, *, llm: Callable[[str], str]) -> Dict[str, str]:
    prompt = (
        f"Think step-by-step, laying out each logical step clearly.\n\n"
        f"Question: {question}\n\n"
        f"Format your response as:\n"
        f"Step 1: ...\n"
        f"Step 2: ...\n"
        f"...\n"
        f"Final answer: ...\n"
        f"Confidence (0-1): ...\n"
    )
    out = llm(prompt)
    steps: list = []
    final = ""
    confidence = 0.0
    for line in out.splitlines():
        if line.startswith("Step "):
            steps.append(line)
        elif line.lower().startswith("final answer:"):
            final = line.split(":", 1)[1].strip()
        elif line.lower().startswith("confidence"):
            try:
                confidence = float(line.split(":", 1)[1].strip())
            except Exception:
                confidence = 0.0
    return {"steps": "\n".join(steps), "answer": final, "confidence": str(confidence)}
