"""飞书 lark-oapi 客户端封装.

提供 V1 用到的薄封装：
  - send_text / send_card
  - docx_create / docx_append_blocks
  - drive_upload (.pptx)
  - transcribe_audio (ASR)
  - get_chat_messages (im_fetch)
  - cardkit 2.0 streaming patch (打字机效果)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger("pilot.surface.feishu.client")


class FeishuClient:
    """轻量飞书 OpenAPI 封装（不依赖 lark-oapi SDK，纯 httpx 实现）.

    需要 lark-oapi 长连接的场景由 bot.py 用 lark-oapi 单独处理；
    本类负责"主动调"飞书 API（创文档、发卡片等）。
    """

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self) -> None:
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self._token: str = ""
        self._token_expires: float = 0
        self._http: httpx.AsyncClient | None = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        client = await self._client()
        r = await client.post(
            f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书 token 获取失败: {data}")
        self._token = data["tenant_access_token"]
        self._token_expires = time.time() + data.get("expire", 7200)
        return self._token

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

    # ── IM ──
    async def send_text(self, *, receive_id: str, text: str, receive_id_type: str = "open_id") -> dict[str, Any]:
        token = await self._ensure_token()
        client = await self._client()
        r = await client.post(
            f"{self.BASE_URL}/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers=self._headers(token),
            json={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        r.raise_for_status()
        return r.json()

    async def send_card(
        self,
        *,
        receive_id: str,
        card: dict[str, Any],
        receive_id_type: str = "open_id",
    ) -> dict[str, Any]:
        token = await self._ensure_token()
        client = await self._client()
        r = await client.post(
            f"{self.BASE_URL}/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers=self._headers(token),
            json={
                "receive_id": receive_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
        )
        r.raise_for_status()
        return r.json()

    async def reply_text(self, *, message_id: str, text: str) -> dict[str, Any]:
        token = await self._ensure_token()
        client = await self._client()
        r = await client.post(
            f"{self.BASE_URL}/im/v1/messages/{message_id}/reply",
            headers=self._headers(token),
            json={
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        r.raise_for_status()
        return r.json()

    # ── CardKit 2.0 流式（70ms 打字机）──
    async def card_create(
        self,
        *,
        card: dict[str, Any],
        streaming_mode: bool = True,
    ) -> str:
        """CardKit 2.0：创建可流式更新的卡片实体；返回 card_id."""
        token = await self._ensure_token()
        client = await self._client()
        body: dict[str, Any] = {"card_data": card}
        if streaming_mode:
            body["card_settings"] = {
                "streaming_mode": True,
                "print_frequency_ms": 70,
                "print_step": 1,
                "print_strategy": "fast",
            }
        r = await client.post(
            f"{self.BASE_URL}/cardkit/v1/cards",
            headers=self._headers(token),
            json=body,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("card_id", "")

    async def card_text_stream(
        self,
        *,
        card_id: str,
        element_id: str,
        text_chunk: str,
    ) -> None:
        """CardKit 2.0：流式追加文本 chunk."""
        token = await self._ensure_token()
        client = await self._client()
        try:
            await client.put(
                f"{self.BASE_URL}/cardkit/v1/cards/{card_id}/elements/{element_id}/content",
                headers=self._headers(token),
                json={"content": text_chunk, "operation": "append"},
            )
        except Exception as e:
            logger.debug("card_text_stream failed: %s", e)

    # ── Docx ──
    async def docx_create(self, *, title: str, folder_token: str = "") -> dict[str, Any]:
        token = await self._ensure_token()
        client = await self._client()
        body: dict[str, Any] = {"title": title}
        if folder_token:
            body["folder_token"] = folder_token
        r = await client.post(
            f"{self.BASE_URL}/docx/v1/documents",
            headers=self._headers(token),
            json=body,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"docx_create error: {data}")
        return data.get("data", {})

    async def docx_append_blocks(self, *, doc_token: str, blocks: list[dict[str, Any]]) -> int:
        token = await self._ensure_token()
        client = await self._client()
        wrote = 0
        for batch_start in range(0, len(blocks), 50):
            batch = blocks[batch_start:batch_start + 50]
            r = await client.post(
                f"{self.BASE_URL}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
                headers=self._headers(token),
                json={"children": batch, "index": -1},
            )
            try:
                r.raise_for_status()
                wrote += len(batch)
            except Exception as e:
                resp_text = r.text[:300] if hasattr(r, 'text') else ""
                logger.warning("docx_append_blocks batch failed: %s | resp: %s", e, resp_text)
        return wrote

    # ── Drive ──
    async def drive_upload_file(
        self,
        *,
        local_path: str,
        parent_token: str = "",
    ) -> dict[str, Any]:
        token = await self._ensure_token()
        client = await self._client()
        with open(local_path, "rb") as f:
            data = f.read()
        size = len(data)
        # 简化：使用 upload_all（< 20MB）
        files = {
            "file_name": (None, os.path.basename(local_path)),
            "parent_type": (None, "explorer"),
            "parent_node": (None, parent_token or os.getenv("FEISHU_FOLDER_TOKEN", "")),
            "size": (None, str(size)),
            "file": (os.path.basename(local_path), data),
        }
        r = await client.post(
            f"{self.BASE_URL}/drive/v1/files/upload_all",
            headers={"Authorization": f"Bearer {token}"},
            files=files,
        )
        try:
            r.raise_for_status()
        except Exception as e:
            logger.warning("drive_upload_file failed: %s", e)
            return {}
        return r.json().get("data", {})

    # ── ASR ──
    async def transcribe_audio(self, *, message_id: str, file_key: str) -> str:
        """飞书消息音频 → 文本（用 speech_to_text v1 API）."""
        token = await self._ensure_token()
        client = await self._client()
        # 1. 下载音频
        r1 = await client.get(
            f"{self.BASE_URL}/im/v1/messages/{message_id}/resources/{file_key}",
            params={"type": "file"},
            headers=self._headers(token),
        )
        if r1.status_code != 200:
            return ""
        audio_bytes = r1.content
        # 2. 飞书 ASR
        import base64
        r2 = await client.post(
            f"{self.BASE_URL}/speech_to_text/v1/speech/file_recognize",
            headers=self._headers(token),
            json={
                "speech": {"speech": base64.b64encode(audio_bytes).decode("utf-8")},
                "config": {"file_id": "audio_1", "format": "opus", "engine_type": "16k_zh"},
            },
        )
        try:
            data = r2.json()
            return (data.get("data", {}) or {}).get("recognition_text", "") or ""
        except Exception:
            return ""

    async def get_chat_messages(self, *, chat_id: str, limit: int = 50) -> list[dict[str, Any]]:
        token = await self._ensure_token()
        client = await self._client()
        r = await client.get(
            f"{self.BASE_URL}/im/v1/messages",
            params={"container_id_type": "chat", "container_id": chat_id, "page_size": limit},
            headers=self._headers(token),
        )
        try:
            data = r.json()
            items = data.get("data", {}).get("items", []) or []
        except Exception:
            return []
        out = []
        for it in items:
            content = it.get("body", {}).get("content", "{}")
            try:
                content_obj = json.loads(content) if isinstance(content, str) else content
            except Exception:
                content_obj = {}
            text = content_obj.get("text", "") if isinstance(content_obj, dict) else ""
            out.append({
                "msg_id": it.get("message_id", ""),
                "sender": it.get("sender", {}).get("id", ""),
                "text": text,
                "ts": int(it.get("create_time", "0") or "0") // 1000,
            })
        return out

    # ── Drive 文档检索 ──
    async def drive_search(self, *, query: str, count: int = 10) -> list[dict[str, Any]]:
        """检索用户云文档（POST /drive/v1/files/search）.

        返回 [{token, name, type, url}] 简化结构。
        """
        token = await self._ensure_token()
        client = await self._client()
        try:
            r = await client.post(
                f"{self.BASE_URL}/drive/v1/files/search",
                headers=self._headers(token),
                json={"query": query, "count": min(int(count), 50)},
            )
            data = r.json()
        except Exception as e:
            logger.warning("drive_search failed: %s", e)
            return []
        items = (data.get("data") or {}).get("files", []) or []
        out = []
        for it in items:
            tk = it.get("token") or it.get("doc_token") or ""
            ttype = it.get("type") or "doc"
            url = it.get("url") or _fmt_drive_url(tk, ttype)
            out.append({
                "token": tk,
                "name": it.get("name", ""),
                "type": ttype,
                "url": url,
            })
        return out

    # ── Bitable（多维表格）记录检索 ──
    async def bitable_search(
        self,
        *,
        app_token: str = "",
        table_id: str = "",
        query: str = "",
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """检索 bitable 记录（POST /bitable/v1/apps/{app}/tables/{table}/records/search）.

        参数缺失时返回空列表（不抛）；上层调用方可根据 query 自动选 default app。
        """
        app_token = app_token or os.getenv("FEISHU_BITABLE_APP_TOKEN", "")
        if not app_token or not table_id:
            return []
        token = await self._ensure_token()
        client = await self._client()
        try:
            body: dict[str, Any] = {"page_size": min(int(page_size), 100)}
            if query:
                body["filter"] = {
                    "conjunction": "or",
                    "conditions": [{"operator": "contains", "value": [query]}],
                }
            r = await client.post(
                f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                headers=self._headers(token),
                json=body,
            )
            data = r.json()
        except Exception as e:
            logger.warning("bitable_search failed: %s", e)
            return []
        items = (data.get("data") or {}).get("items", []) or []
        return [
            {
                "record_id": it.get("record_id", ""),
                "fields": it.get("fields", {}) or {},
            }
            for it in items
        ]

    async def aclose(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None


def _fmt_drive_url(token: str, type_: str) -> str:
    if not token:
        return ""
    if type_ in ("docx",):
        return f"https://feishu.cn/docx/{token}"
    if type_ == "doc":
        return f"https://feishu.cn/doc/{token}"
    if type_ == "sheet":
        return f"https://feishu.cn/sheets/{token}"
    if type_ == "bitable":
        return f"https://feishu.cn/base/{token}"
    return f"https://feishu.cn/file/{token}"


_default: FeishuClient | None = None


def get_feishu_client() -> FeishuClient:
    global _default
    if _default is None:
        _default = FeishuClient()
    return _default
