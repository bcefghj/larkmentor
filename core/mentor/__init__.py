"""FlowGuard v4 · Rookie Mentor module.

Multi-role agent that coaches new employees on workplace communication:
- knowledge_base : per-user organisation RAG (Doubao embedding + sqlite, BM25 fallback)
- mentor_router   : light supervisor that dispatches to writing / task / weekly specialists
- coach_writing  : writing mentor (NVC framework + 3 versions)
- coach_task     : task mentor (active clarification with ambiguity scoring)
- coach_weekly   : weekly report mentor (STAR structure + citations)
- proactive_hook : auto-suggest reply when user receives P0/P1 in focus
- growth_doc     : auto-maintained growth journal in Feishu Docx
"""
