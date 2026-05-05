"""Legacy v1 Smart Shield interface - redirects to v3/classification engine.

Maintained for backward compatibility with tests and older code paths.
New code should use smart_shield_v3 or classification_engine directly.
"""

from core.smart_shield_v3 import process_message_v3 as process_message

try:
    from core.classification_engine import _contains_urgent_keyword
except ImportError:
    from config import Config

    def _contains_urgent_keyword(text: str) -> bool:
        lower = text.lower()
        return any(kw.lower() in lower for kw in Config.URGENT_KEYWORDS)


def classify_message(user, sender_name: str = "", sender_id: str = "", text: str = "", chat_name: str = "", **kwargs):
    """Legacy classify_message interface for backward compatibility.

    Original signature: classify_message(user, sender_name, sender_id, text, chat_name)
    Returns: {"level": "P0"/"P1"/"P2"/"P3", "reason": str, "score": float}
    """
    try:
        from core.classification_engine import classify as _classify
        from core.sender_profile import SenderProfile

        sp = SenderProfile(name=sender_name, open_id=sender_id)
        result = _classify(user, sp, text, chat_type="group" if chat_name else "p2p")
        return {"level": result.priority, "reason": result.reason, "score": result.final_score}
    except Exception:
        pass

    wl = getattr(user, "whitelist", []) if user else []
    if sender_name in wl or sender_id in wl:
        return {"level": "P0", "reason": "白名单", "score": 1.0}
    if _contains_urgent_keyword(text):
        return {"level": "P0", "reason": "紧急关键词命中", "score": 0.8}
    return {"level": "P2", "reason": "普通消息", "score": 0.3}


__all__ = ["process_message", "_contains_urgent_keyword", "classify_message"]
