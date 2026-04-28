"""Debate Pattern · 2-agent 正反辩论，Judge 收敛（arxiv 2508.17536 经验版）

基于 Majority Voting 仍然是主要增益来源的发现，我们：
- 3 agent 各自独立生成（并行，不相互污染）
- Judge agent 做 majority vote / 语义融合
- 仅当 3 票不一致时才触发真正的 debate 回合
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent.patterns.debate")


def debate_round(
    question: str, *,
    llm_doubao: Callable[[str], str],
    llm_minimax: Callable[[str], str],
    llm_deepseek: Callable[[str], str],
    llm_judge: Callable[[str], str],
    max_rounds: int = 3,
) -> Dict[str, Any]:
    """3-path generation + 1 judge (majority voting dominant)."""
    answers = [
        {"model": "doubao", "text": llm_doubao(question)[:1500]},
        {"model": "minimax", "text": llm_minimax(question)[:1500]},
        {"model": "deepseek", "text": llm_deepseek(question)[:1500]},
    ]
    judge_prompt = (
        f"Question: {question}\n\n"
        f"3 independent answers:\n"
        + "\n---\n".join(f"[{a['model']}]: {a['text']}" for a in answers) +
        f"\n\n"
        f"Tasks:\n"
        f"1. Determine if these answers agree (2 of 3 is majority).\n"
        f"2. If agree → synthesize a final answer using the majority.\n"
        f"3. If 3 disagree → write down the key disagreement points for a debate round.\n"
        f"Respond as JSON: {{\"converged\": true|false, \"final_answer\": \"...\", \"disagreements\": [\"...\"]}}"
    )
    judgement = llm_judge(judge_prompt)
    try:
        import json
        data = json.loads(judgement.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    except Exception:
        data = {"converged": True, "final_answer": answers[0]["text"], "disagreements": []}

    if data.get("converged"):
        return {"answer": data.get("final_answer"), "rounds": 1, "paths": answers}

    # Actual debate round
    for r in range(1, max_rounds):
        debate_prompt = (
            f"Question: {question}\n\n"
            f"Disagreements so far: {data.get('disagreements', [])}\n\n"
            f"Each model, please argue for your answer and critique others:\n"
        )
        answers = [
            {"model": "doubao", "text": llm_doubao(debate_prompt)[:1500]},
            {"model": "minimax", "text": llm_minimax(debate_prompt)[:1500]},
            {"model": "deepseek", "text": llm_deepseek(debate_prompt)[:1500]},
        ]
        judgement = llm_judge(judge_prompt + "\n\nRound " + str(r + 1) + ":\n" + "\n---\n".join(a["text"] for a in answers))
        try:
            import json
            data = json.loads(judgement.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
        except Exception:
            pass
        if data.get("converged"):
            return {"answer": data.get("final_answer"), "rounds": r + 1, "paths": answers}
    return {"answer": data.get("final_answer", answers[0]["text"]), "rounds": max_rounds, "paths": answers}
