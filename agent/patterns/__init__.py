"""Reasoning & Execution Patterns Library (对齐 Shannon patterns/)."""

from .react import react_loop
from .reflection import reflect_and_improve
from .chain_of_thought import cot_reason
from .debate import debate_round
from .tree_of_thoughts import tree_of_thoughts
from .multi_agent import fan_out, pipeline, map_reduce, specialist_delegation

__all__ = [
    "react_loop", "reflect_and_improve", "cot_reason", "debate_round", "tree_of_thoughts",
    "fan_out", "pipeline", "map_reduce", "specialist_delegation",
]
