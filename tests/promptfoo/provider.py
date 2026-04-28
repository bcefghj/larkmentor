"""promptfoo Python provider that adapts FlowGuard TranscriptClassifier."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "project"))

from core.security.transcript_classifier import classify_transcript  # noqa: E402


def classify(prompt: str, options=None, context=None):
    """promptfoo will call us with the rendered prompt as the first arg."""
    verdict = classify_transcript(prompt)
    return {
        "output": json.dumps({
            "action": verdict.action.value,
            "score": verdict.score,
            "reason": verdict.reason,
            "tags": verdict.tags,
            "used_llm": verdict.used_llm,
        }, ensure_ascii=False),
    }


if __name__ == "__main__":
    print(classify(sys.argv[1] if len(sys.argv) > 1 else "hello"))
