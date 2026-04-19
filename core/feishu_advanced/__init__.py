"""Advanced Feishu API helpers added in v3.

These wrappers focus on the open-platform surfaces that the v1 codebase did
not yet touch:

* ``urgent_api``     – three-tier urgent notification (in-app / sms / phone)
* ``reaction_api``   – emoji reactions for low-friction acknowledgement
* ``reply_thread``   – reply-in-thread to keep groups tidy
* ``calendar_busy``  – auto-create busy events when focus turns on
* ``task_v2``        – create Feishu Tasks v2 from P0 messages with task hints
* ``minutes_fetch``  – pull Minutes (妙记) transcripts into Archival memory
* ``wiki_search``    – read-only Wiki search for Rookie Buddy

All helpers are best-effort: each returns ``{"ok": True/False, ...}`` and
never raises, so the calling code can degrade gracefully if a permission is
not yet approved by the Feishu open platform reviewer.
"""

from .urgent_api import send_urgent_app, send_urgent_sms, send_urgent_phone  # noqa: F401
from .reaction_api import add_reaction, list_reactions  # noqa: F401
from .reply_thread import reply_in_thread  # noqa: F401
from .calendar_busy import create_busy_event  # noqa: F401
from .task_v2 import create_task_from_message  # noqa: F401
from .minutes_fetch import fetch_recent_minutes  # noqa: F401
from .wiki_search import search_wiki  # noqa: F401
