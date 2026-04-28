"""Verify MiniMax 2.7 + Doubao 双供应商连通性。

Used in P0 audit and CI smoke. Returns 0 on success.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()


def check_doubao() -> tuple[bool, str, float]:
    """Doubao via OpenAI-compatible API."""
    try:
        from openai import OpenAI
        api_key = os.getenv("ARK_API_KEY")
        base_url = os.getenv("ARK_CHAT_URL") or os.getenv("ARK_BASE_URL")
        model = os.getenv("ARK_CHAT_MODEL") or os.getenv("ARK_MODEL", "doubao-seed-2.0-pro")
        if not api_key or not base_url:
            return False, "missing ARK_API_KEY or ARK_CHAT_URL", 0.0
        cli = OpenAI(api_key=api_key, base_url=base_url)
        t = time.time()
        resp = cli.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "用一句中文回复 ok"}],
            max_tokens=20,
            temperature=0.1,
        )
        dt = time.time() - t
        text = (resp.choices[0].message.content or "").strip()
        return True, text[:60], dt
    except Exception as e:
        return False, f"err: {e}", 0.0


def check_minimax() -> tuple[bool, str, float]:
    """MiniMax M2.7 via OpenAI-compatible coding endpoint."""
    try:
        from openai import OpenAI
        api_key = os.getenv("MINIMAX_API_KEY")
        if not api_key:
            return False, "missing MINIMAX_API_KEY", 0.0
        # MiniMax coding (Cursor-like) endpoint
        base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
        model = os.getenv("MINIMAX_MODEL", "MiniMax-M2")
        cli = OpenAI(api_key=api_key, base_url=base_url)
        t = time.time()
        resp = cli.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "用一句中文回复 ok"}],
            max_tokens=20,
            temperature=0.1,
        )
        dt = time.time() - t
        text = (resp.choices[0].message.content or "").strip()
        return True, text[:60], dt
    except Exception as e:
        return False, f"err: {e}"[:200], 0.0


def main() -> int:
    print("=== LLM Provider Connectivity ===")

    print("\n[1] Doubao (ARK)")
    ok, msg, dt = check_doubao()
    print(f"    status: {'OK' if ok else 'FAIL'}  ({dt:.2f}s)  reply: {msg}")
    doubao_ok = ok

    print("\n[2] MiniMax M2.7")
    ok, msg, dt = check_minimax()
    print(f"    status: {'OK' if ok else 'FAIL'}  ({dt:.2f}s)  reply: {msg}")
    minimax_ok = ok

    print("\n=== Summary ===")
    print(f"  Doubao   : {'OK' if doubao_ok else 'FAIL'}")
    print(f"  MiniMax  : {'OK' if minimax_ok else 'FAIL'}")

    if not (doubao_ok or minimax_ok):
        print("  Both providers failed.")
        return 1
    if not doubao_ok or not minimax_ok:
        print("  One provider failed; failover available.")
        return 0
    print("  Both providers OK; full multi-provider available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
