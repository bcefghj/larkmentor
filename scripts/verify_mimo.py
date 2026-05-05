#!/usr/bin/env python3
"""Verify MiMo API connectivity and basic chat completion.

Usage:
    PYTHONPATH=. python scripts/verify_mimo.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def verify_mimo():
    from config import Config

    if not Config.MIMO_API_KEY:
        print("[SKIP] MIMO_API_KEY not configured")
        return False

    print(f"[INFO] MiMo base URL: {Config.MIMO_BASE_URL}")
    print(f"[INFO] MiMo model:    {Config.MIMO_MODEL}")
    print(f"[INFO] API key:       {Config.MIMO_API_KEY[:8]}...{Config.MIMO_API_KEY[-4:]}")

    from openai import OpenAI

    client = OpenAI(api_key=Config.MIMO_API_KEY, base_url=Config.MIMO_BASE_URL)

    print("\n[TEST] Simple chat completion...")
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=Config.MIMO_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Reply in Chinese."},
                {"role": "user", "content": "你好，请用一句话介绍自己。"},
            ],
            temperature=0.3,
            max_tokens=100,
            timeout=15,
        )
        elapsed = time.time() - t0
        content = resp.choices[0].message.content.strip()
        print(f"[OK]   Response ({elapsed:.2f}s): {content[:120]}")
        if resp.usage:
            print(f"[INFO] Tokens: prompt={resp.usage.prompt_tokens}, completion={resp.usage.completion_tokens}")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[FAIL] Error after {elapsed:.2f}s: {type(e).__name__}: {e}")
        return False


def verify_provider_selection():
    print("\n[TEST] Provider selection priority...")
    from llm.llm_client import _select_provider, get_active_model

    api_key, base_url = _select_provider()
    model = get_active_model()
    if api_key:
        print(f"[OK]   Selected provider: base_url={base_url}, model={model}")
        print(f"[OK]   API key: {api_key[:8]}...{api_key[-4:]}")
    else:
        print("[WARN] No LLM provider configured")


def verify_chat_wrapper():
    print("\n[TEST] llm_client.chat() wrapper...")
    t0 = time.time()
    try:
        from llm.llm_client import chat

        result = chat("请用一句话解释什么是 Agent-Pilot。", temperature=0.3)
        elapsed = time.time() - t0
        if result:
            print(f"[OK]   chat() response ({elapsed:.2f}s): {result[:120]}")
        else:
            print(f"[WARN] chat() returned empty after {elapsed:.2f}s")
    except Exception as e:
        print(f"[FAIL] chat() error: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("Agent-Pilot LLM Provider Verification")
    print("=" * 60)

    verify_provider_selection()
    ok = verify_mimo()
    if ok:
        verify_chat_wrapper()

    print("\n" + "=" * 60)
    print("Done." if ok else "Some checks failed - review output above.")
