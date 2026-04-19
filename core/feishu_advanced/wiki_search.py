"""Read-only Feishu Wiki search used by Rookie Buddy for org-style answers."""

from __future__ import annotations

import logging
from typing import List, Dict

logger = logging.getLogger("flowguard.feishu.wiki")


def search_wiki(query: str, *, limit: int = 5) -> List[Dict]:
    """Returns matching wiki nodes (best-effort)."""
    try:
        from bot.feishu_client import get_client
        from lark_oapi.api.wiki.v2 import SearchWikiNodeRequest, SearchWikiNodeRequestBody  # type: ignore
        client = get_client()
        req = (
            SearchWikiNodeRequest.builder()
            .request_body(SearchWikiNodeRequestBody.builder().query(query).build())
            .page_size(limit)
            .build()
        )
        resp = client.wiki.v2.space_node.search(req)
        if not resp.success() or not resp.data or not getattr(resp.data, "items", None):
            return []
        out: List[Dict] = []
        for it in resp.data.items[:limit]:
            out.append({
                "title": getattr(it, "title", ""),
                "node_token": getattr(it, "node_token", ""),
                "url": getattr(it, "url", ""),
            })
        return out
    except Exception as e:
        logger.debug("wiki search err: %s", e)
        return []
