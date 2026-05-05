"""Reasoning & Execution Patterns Library (对齐 Shannon patterns/)."""

from .chain_of_thought import cot_reason
from .debate import debate_round
from .multi_agent import fan_out, map_reduce, pipeline, specialist_delegation
from .react import react_loop
from .reflection import reflect_and_improve
from .tree_of_thoughts import TreeOfThoughts, tree_of_thoughts
from .builder_validator import BuilderValidator

__all__ = [
    "react_loop",
    "reflect_and_improve",
    "cot_reason",
    "debate_round",
    "tree_of_thoughts",
    "TreeOfThoughts",
    "BuilderValidator",
    "fan_out",
    "pipeline",
    "map_reduce",
    "specialist_delegation",
]
