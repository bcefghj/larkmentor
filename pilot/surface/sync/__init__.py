"""Sync 层 — 多端 CRDT 实时同步.

设计:
  - WebSocket Hub: 管理 room（按 plan_id/session_id 划分）+ presence 广播
  - CRDT: 用 pycrdt（Yjs 兼容）；客户端可用 yjs-flutter / yjs-js
  - 离线: CRDT 天然支持，断网时本地写、联网后 reconcile（Good-1 加分项）
"""

from pilot.surface.sync.hub import SyncHub, default_hub  # noqa: F401

__all__ = ["SyncHub", "default_hub"]
