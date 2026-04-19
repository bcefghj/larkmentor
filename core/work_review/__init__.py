"""Work Review – weekly / monthly / wrapped report generation.

Closes the loop on the user's original ask: "I want to see what I did this
week / this month so I can write my work report".

Stages
------

1. ``weekly_report`` – scans the user's working memory + archival store +
   interruption log for the past 7 days and asks the LLM for a structured
   markdown.
2. ``monthly_wrapped`` – Spotify-Wrapped style stats card for share-worthy
   moments.
3. ``publish_to_feishu`` – best-effort write to the user's recovery doc and
   archival store.
"""

from .weekly_report import generate_weekly_report  # noqa: F401
from .monthly_wrapped import generate_monthly_wrapped  # noqa: F401
