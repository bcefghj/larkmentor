"""Tree-of-Thoughts Pattern · 并行假设 + 剪枝。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List


def tree_of_thoughts(
    question: str, *,
    llm: Callable[[str], str],
    branches: int = 3,
    depth: int = 2,
) -> Dict[str, Any]:
    """Generate N branches; at each depth, evaluate and prune."""
    current_leaves: List[Dict[str, Any]] = [{"path": [], "text": "", "score": 0.5}]
    for d in range(depth):
        next_leaves: List[Dict[str, Any]] = []
        for leaf in current_leaves:
            for b in range(branches):
                prompt = (
                    f"Question: {question}\n\n"
                    f"Partial reasoning so far: {leaf['text']}\n\n"
                    f"Generate next step option #{b+1}:"
                )
                extension = llm(prompt)[:500]
                next_leaves.append({
                    "path": leaf["path"] + [b],
                    "text": leaf["text"] + "\n" + extension,
                    "score": 0.5,
                })
        # Evaluate
        eval_prompt = (
            f"Question: {question}\n\n"
            f"Rate each partial reasoning on quality 0-1, return JSON list:\n\n"
            + "\n---\n".join(f"[{i}] {l['text'][:300]}" for i, l in enumerate(next_leaves))
        )
        scores_out = llm(eval_prompt)
        import re, json
        try:
            nums = [float(m.group(0)) for m in re.finditer(r"\d+(?:\.\d+)?", scores_out)]
            for i, l in enumerate(next_leaves):
                if i < len(nums):
                    l["score"] = min(1.0, nums[i])
        except Exception:
            pass
        # Keep top-K
        next_leaves.sort(key=lambda x: x["score"], reverse=True)
        current_leaves = next_leaves[:branches]

    best = max(current_leaves, key=lambda x: x["score"])
    final_prompt = f"Question: {question}\n\nBest reasoning: {best['text']}\n\nFinalize the answer:"
    return {"answer": llm(final_prompt), "branches_explored": branches ** depth, "best_score": best["score"]}
