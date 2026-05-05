"""Tree-of-Thoughts Pattern · 并行假设 + LLM 评估 + 剪枝。

A real, callable implementation that:
- Generates multiple thought branches via actual LLM calls
- Evaluates each branch with a scoring prompt
- Prunes low-scoring branches at each depth level
- Tracks token usage per branch for cost awareness
- Emits observable events for each branch explored
- Supports early-stop if token budget is exceeded

Integration:
    from agent.providers import default_providers
    from agent.patterns.tree_of_thoughts import TreeOfThoughts

    tot = TreeOfThoughts(provider=default_providers())
    result = tot.solve("How to design a scalable microservice?")
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("agent.patterns.tree_of_thoughts")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ThoughtNode:
    """A single node in the thought tree."""

    node_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    depth: int = 0
    branch_index: int = 0
    parent_id: Optional[str] = None
    text: str = ""
    score: float = 0.0
    cumulative_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0
    pruned: bool = False
    children: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "depth": self.depth,
            "branch_index": self.branch_index,
            "parent_id": self.parent_id,
            "text_preview": self.text[:200],
            "score": round(self.score, 3),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_cny": round(self.cost_cny, 5),
            "pruned": self.pruned,
            "children_count": len(self.children),
        }


@dataclass
class ToTResult:
    """Final result of a Tree-of-Thoughts solve."""

    answer: str
    best_path: List[ThoughtNode]
    best_score: float
    total_branches_explored: int
    total_branches_pruned: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_cny: float
    depth_reached: int
    elapsed_sec: float
    budget_exceeded: bool = False
    all_nodes: List[ThoughtNode] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "best_score": round(self.best_score, 3),
            "best_path": [n.to_dict() for n in self.best_path],
            "total_branches_explored": self.total_branches_explored,
            "total_branches_pruned": self.total_branches_pruned,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_cny": round(self.total_cost_cny, 5),
            "depth_reached": self.depth_reached,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "budget_exceeded": self.budget_exceeded,
        }


@dataclass
class ToTEvent:
    """Observable event emitted during tree exploration."""

    kind: str  # "branch_generated", "branch_evaluated", "branch_pruned", "depth_complete", "budget_warning", "finalize"
    depth: int
    node_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


EventCallback = Callable[[ToTEvent], None]


# ---------------------------------------------------------------------------
# TreeOfThoughts
# ---------------------------------------------------------------------------


class TreeOfThoughts:
    """Tree-of-Thoughts solver with real LLM calls, evaluation, and pruning.

    Args:
        provider: A ProviderRouter instance (from agent.providers).
                  If None, creates the default singleton.
        on_event: Optional callback invoked for each observable event.
        token_budget: Max total tokens (input + output) before early-stop.
                      0 means unlimited.
        cost_budget_cny: Max total cost (CNY) before early-stop.
                         0.0 means unlimited.
        generate_task_kind: Provider routing task_kind for thought generation.
        evaluate_task_kind: Provider routing task_kind for evaluation/scoring.
    """

    def __init__(
        self,
        provider=None,
        on_event: Optional[EventCallback] = None,
        token_budget: int = 0,
        cost_budget_cny: float = 0.0,
        generate_task_kind: str = "reasoning",
        evaluate_task_kind: str = "critique",
    ) -> None:
        self._provider = provider
        self._on_event = on_event
        self._token_budget = token_budget
        self._cost_budget_cny = cost_budget_cny
        self._gen_task = generate_task_kind
        self._eval_task = evaluate_task_kind
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_cny = 0.0
        self._nodes: Dict[str, ThoughtNode] = {}

    @property
    def provider(self):
        if self._provider is None:
            from agent.providers import default_providers

            self._provider = default_providers()
        return self._provider

    def _emit(self, event: ToTEvent) -> None:
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as e:
                logger.debug("event callback error: %s", e)

    def _budget_exceeded(self) -> bool:
        if self._token_budget > 0:
            total = self._total_input_tokens + self._total_output_tokens
            if total >= self._token_budget:
                return True
        if self._cost_budget_cny > 0.0:
            if self._total_cost_cny >= self._cost_budget_cny:
                return True
        return False

    def _llm_call(
        self, messages: List[Dict[str, str]], *, task_kind: str, temperature: float = 0.7, max_tokens: int = 800
    ) -> str:
        """Make an LLM call via the provider router, tracking usage."""
        before_usage = list(self.provider.usage)
        result = self.provider.chat(
            messages,
            task_kind=task_kind,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        after_usage = self.provider.usage
        new_records = after_usage[len(before_usage) :]
        for rec in new_records:
            self._total_input_tokens += rec.input_tokens
            self._total_output_tokens += rec.output_tokens
            self._total_cost_cny += rec.cost_cny
        return result

    def solve(
        self,
        problem: str,
        num_thoughts: int = 3,
        max_depth: int = 3,
        prune_threshold: float = 0.3,
        beam_width: Optional[int] = None,
    ) -> ToTResult:
        """Solve a problem using Tree-of-Thoughts exploration.

        Args:
            problem: The problem/question to solve.
            num_thoughts: Number of thought branches to generate at each node.
            max_depth: Maximum depth of the thought tree.
            prune_threshold: Minimum score to keep a branch (0.0-1.0).
            beam_width: Max branches to keep per depth (None = num_thoughts).

        Returns:
            ToTResult with the best solution and metadata.
        """
        if beam_width is None:
            beam_width = num_thoughts

        start_time = time.time()
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_cny = 0.0
        self._nodes = {}
        budget_exceeded = False

        root = ThoughtNode(depth=0, text="[root]", cumulative_text="", score=0.5)
        self._nodes[root.node_id] = root
        current_leaves: List[ThoughtNode] = [root]

        total_explored = 0
        total_pruned = 0
        depth_reached = 0

        for depth in range(1, max_depth + 1):
            if self._budget_exceeded():
                budget_exceeded = True
                self._emit(
                    ToTEvent(
                        kind="budget_warning",
                        depth=depth,
                        data={
                            "total_tokens": self._total_input_tokens + self._total_output_tokens,
                            "total_cost_cny": self._total_cost_cny,
                        },
                    )
                )
                logger.warning("Budget exceeded at depth %d, stopping early", depth)
                break

            depth_reached = depth
            next_leaves: List[ThoughtNode] = []

            for leaf in current_leaves:
                if self._budget_exceeded():
                    budget_exceeded = True
                    break

                branches = self._generate_thoughts(problem, leaf, num_thoughts)
                total_explored += len(branches)

                for branch in branches:
                    self._nodes[branch.node_id] = branch
                    leaf.children.append(branch.node_id)
                    next_leaves.append(branch)

                    self._emit(
                        ToTEvent(
                            kind="branch_generated",
                            depth=depth,
                            node_id=branch.node_id,
                            data=branch.to_dict(),
                        )
                    )

            if not next_leaves:
                break

            if budget_exceeded:
                break

            self._evaluate_thoughts(problem, next_leaves)

            for node in next_leaves:
                self._emit(
                    ToTEvent(
                        kind="branch_evaluated",
                        depth=depth,
                        node_id=node.node_id,
                        data={"score": node.score, "text_preview": node.text[:100]},
                    )
                )

            # Prune: remove branches below threshold
            surviving: List[ThoughtNode] = []
            for node in next_leaves:
                if node.score < prune_threshold:
                    node.pruned = True
                    total_pruned += 1
                    self._emit(
                        ToTEvent(
                            kind="branch_pruned",
                            depth=depth,
                            node_id=node.node_id,
                            data={"score": node.score, "threshold": prune_threshold},
                        )
                    )
                else:
                    surviving.append(node)

            # Beam search: keep only top beam_width
            surviving.sort(key=lambda n: n.score, reverse=True)
            for node in surviving[beam_width:]:
                node.pruned = True
                total_pruned += 1
            surviving = surviving[:beam_width]

            if not surviving:
                next_leaves.sort(key=lambda n: n.score, reverse=True)
                surviving = next_leaves[:1]
                for n in surviving:
                    n.pruned = False

            current_leaves = surviving
            self._emit(
                ToTEvent(
                    kind="depth_complete",
                    depth=depth,
                    data={
                        "surviving_count": len(surviving),
                        "pruned_count": total_pruned,
                        "best_score": max(n.score for n in surviving) if surviving else 0,
                    },
                )
            )

        # Pick the best leaf and reconstruct path
        best_leaf = max(current_leaves, key=lambda n: n.score) if current_leaves else root
        best_path = self._reconstruct_path(best_leaf)

        # Generate final answer from best reasoning chain
        answer = self._finalize(problem, best_leaf)

        self._emit(
            ToTEvent(
                kind="finalize",
                depth=depth_reached,
                node_id=best_leaf.node_id,
                data={"best_score": best_leaf.score, "answer_preview": answer[:200]},
            )
        )

        elapsed = time.time() - start_time

        return ToTResult(
            answer=answer,
            best_path=best_path,
            best_score=best_leaf.score,
            total_branches_explored=total_explored,
            total_branches_pruned=total_pruned,
            total_input_tokens=self._total_input_tokens,
            total_output_tokens=self._total_output_tokens,
            total_cost_cny=self._total_cost_cny,
            depth_reached=depth_reached,
            elapsed_sec=elapsed,
            budget_exceeded=budget_exceeded,
            all_nodes=list(self._nodes.values()),
        )

    def _generate_thoughts(
        self,
        problem: str,
        parent: ThoughtNode,
        num_thoughts: int,
    ) -> List[ThoughtNode]:
        """Generate N thought branches from a parent node."""
        branches: List[ThoughtNode] = []

        for i in range(num_thoughts):
            prompt = (
                f"You are solving a complex problem step by step using Tree-of-Thoughts reasoning.\n\n"
                f"## Problem\n{problem}\n\n"
            )
            if parent.cumulative_text:
                prompt += f"## Reasoning so far\n{parent.cumulative_text}\n\n"
            prompt += (
                f"## Task\n"
                f"Generate thought branch #{i + 1} of {num_thoughts}. "
                f"Explore a DIFFERENT angle or approach than what's been considered. "
                f"Be creative but rigorous. Think step by step.\n\n"
                f"Write your next reasoning step (2-4 paragraphs):"
            )

            messages = [{"role": "user", "content": prompt}]

            try:
                response = self._llm_call(
                    messages,
                    task_kind=self._gen_task,
                    temperature=0.7 + (i * 0.1),  # slightly more creative each branch
                    max_tokens=600,
                )
            except Exception as e:
                logger.warning("thought generation failed branch=%d: %s", i, e)
                response = f"[Generation failed: {e}]"

            node = ThoughtNode(
                depth=parent.depth + 1,
                branch_index=i,
                parent_id=parent.node_id,
                text=response.strip(),
                cumulative_text=(
                    f"{parent.cumulative_text}\n\n--- Step {parent.depth + 1} (Branch {i + 1}) ---\n{response.strip()}"
                ).strip(),
            )
            branches.append(node)

        return branches

    def _evaluate_thoughts(
        self,
        problem: str,
        nodes: List[ThoughtNode],
    ) -> None:
        """Evaluate and score a batch of thought nodes."""
        if not nodes:
            return

        eval_prompt = (
            f"You are evaluating reasoning branches for a Tree-of-Thoughts solver.\n\n"
            f"## Problem\n{problem}\n\n"
            f"## Branches to evaluate\n"
        )
        for i, node in enumerate(nodes):
            preview = node.cumulative_text[-500:] if len(node.cumulative_text) > 500 else node.cumulative_text
            eval_prompt += f"\n### Branch [{i}]\n{preview}\n"

        eval_prompt += (
            f"\n## Task\n"
            f"Rate each branch on a scale of 0.0 to 1.0 for:\n"
            f"- Logical soundness (is the reasoning valid?)\n"
            f"- Progress toward solution (does it make meaningful progress?)\n"
            f"- Novelty (does it explore a unique angle?)\n"
            f"- Completeness (how much of the problem does it address?)\n\n"
            f"Respond with ONLY a JSON array of numbers, one score per branch.\n"
            f"Example for {len(nodes)} branches: [0.8, 0.6, 0.4]\n"
            f"Your response (JSON array only):"
        )

        messages = [{"role": "user", "content": eval_prompt}]

        try:
            response = self._llm_call(
                messages,
                task_kind=self._eval_task,
                temperature=0.2,
                max_tokens=200,
            )
            scores = self._parse_scores(response, len(nodes))
            for i, node in enumerate(nodes):
                if i < len(scores):
                    node.score = max(0.0, min(1.0, scores[i]))
                else:
                    node.score = 0.5
        except Exception as e:
            logger.warning("evaluation failed, assigning default scores: %s", e)
            for node in nodes:
                node.score = 0.5

    def _parse_scores(self, response: str, expected_count: int) -> List[float]:
        """Parse LLM response into a list of float scores."""
        # Try parsing as JSON array first
        cleaned = response.strip()
        # Extract JSON array from response
        match = re.search(r"\[[\s\d.,]+\]", cleaned)
        if match:
            try:
                scores = json.loads(match.group(0))
                return [float(s) for s in scores]
            except (json.JSONDecodeError, ValueError):
                pass  # JSON array parse failed; fall through to regex number extraction

        # Fallback: extract all numbers
        nums = re.findall(r"(\d+(?:\.\d+)?)", cleaned)
        scores = []
        for n in nums:
            val = float(n)
            if 0.0 <= val <= 1.0:
                scores.append(val)
            elif 1.0 < val <= 10.0:
                scores.append(val / 10.0)
        return scores[:expected_count] if scores else [0.5] * expected_count

    def _reconstruct_path(self, node: ThoughtNode) -> List[ThoughtNode]:
        """Walk from a leaf back to root, return root-to-leaf path."""
        path: List[ThoughtNode] = []
        current: Optional[ThoughtNode] = node
        while current is not None:
            path.append(current)
            if current.parent_id and current.parent_id in self._nodes:
                current = self._nodes[current.parent_id]
            else:
                break
        path.reverse()
        return path

    def _finalize(self, problem: str, best_leaf: ThoughtNode) -> str:
        """Generate a final polished answer from the best reasoning chain."""
        prompt = (
            f"You are finalizing the solution for a complex problem.\n\n"
            f"## Problem\n{problem}\n\n"
            f"## Best reasoning chain\n{best_leaf.cumulative_text}\n\n"
            f"## Task\n"
            f"Based on the reasoning above, write a clear, comprehensive, "
            f"and well-structured final answer to the problem. "
            f"Synthesize the key insights and present a complete solution."
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            return self._llm_call(
                messages,
                task_kind=self._gen_task,
                temperature=0.3,
                max_tokens=1500,
            )
        except Exception as e:
            logger.warning("finalize failed: %s", e)
            return best_leaf.cumulative_text


# ---------------------------------------------------------------------------
# Convenience function (backwards-compatible with old API)
# ---------------------------------------------------------------------------


def tree_of_thoughts(
    question: str,
    *,
    llm: Optional[Callable[[str], str]] = None,
    branches: int = 3,
    depth: int = 2,
    provider=None,
    on_event: Optional[EventCallback] = None,
    token_budget: int = 0,
    cost_budget_cny: float = 0.0,
) -> Dict[str, Any]:
    """Convenience wrapper: solve a question using Tree-of-Thoughts.

    Accepts either an ``llm`` callable (legacy API) or a ``provider``
    (ProviderRouter) for the new class-based API.

    Returns a dict with answer, metadata, and cost tracking.
    """
    if llm is not None and provider is None:
        # Legacy mode: wrap the callable into a minimal provider-like object
        tot = TreeOfThoughts(
            on_event=on_event,
            token_budget=token_budget,
            cost_budget_cny=cost_budget_cny,
        )
        # Monkey-patch _llm_call for legacy compatibility
        original_call = tot._llm_call

        def _legacy_call(messages, *, task_kind="default", temperature=0.7, max_tokens=800):
            prompt = messages[-1]["content"] if messages else ""
            return llm(prompt)

        tot._llm_call = _legacy_call  # type: ignore[assignment]
        result = tot.solve(question, num_thoughts=branches, max_depth=depth)
        return result.to_dict()

    tot = TreeOfThoughts(
        provider=provider,
        on_event=on_event,
        token_budget=token_budget,
        cost_budget_cny=cost_budget_cny,
    )
    result = tot.solve(question, num_thoughts=branches, max_depth=depth)
    return result.to_dict()
