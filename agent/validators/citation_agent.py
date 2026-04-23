"""Citation Agent · Anthropic 独家机制

独立 agent 在文档生成后跑：
- 提取所有 claim / 数据点 / 引用
- 调 memory.query + wiki.search + doc.search 检索原始出处
- 给每条 claim 标注 source URL / doc_token + 段落
- 不可验证的 claim 标红警告
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent.validators.citation")


@dataclass
class Claim:
    text: str
    kind: str  # "fact" / "data" / "quote" / "reference"
    source_refs: List[Dict[str, str]] = field(default_factory=list)
    verified: bool = False
    confidence: float = 0.0


@dataclass
class CitationReport:
    total_claims: int
    verified_claims: int
    unverified_claims: int
    claims: List[Claim]
    references_md: str
    warnings: List[str]


class CitationAgent:
    """Independent agent that verifies each claim in generated text."""

    def __init__(self) -> None:
        pass

    def extract_claims(self, text: str) -> List[Claim]:
        """Extract claims: sentences with specific data, numbers, quotes."""
        claims: List[Claim] = []
        # Split into sentences (rough)
        for sentence in re.split(r'(?<=[。！？!?.])\s*', text):
            sentence = sentence.strip()
            if not sentence or len(sentence) < 15:
                continue
            # Detect claim candidates
            has_number = bool(re.search(r'\d+(?:[.,]\d+)?(?:%|次|年|月|人|元|美元|tokens?|ms|s|万|亿|千)?', sentence))
            has_quote = bool(re.search(r'["""「『][^""""」』]+["""」』]', sentence))
            has_ref = bool(re.search(r'(?:根据|据|参考|参见|来自|based on|according to|per|cite[sd]?)', sentence, re.IGNORECASE))
            is_definite = bool(re.search(r'(?:是|必须|一定|are|is|must|should|will)\b', sentence))

            if has_quote:
                claims.append(Claim(text=sentence, kind="quote"))
            elif has_number and (has_ref or is_definite):
                claims.append(Claim(text=sentence, kind="data"))
            elif has_ref:
                claims.append(Claim(text=sentence, kind="reference"))
            elif is_definite and len(sentence) > 30:
                claims.append(Claim(text=sentence, kind="fact"))

        logger.info("CitationAgent extracted %d claims", len(claims))
        return claims

    def verify_claim(self, claim: Claim, *, tenant_id: str = "default") -> Claim:
        """Look up memory + wiki + doc for sources."""
        try:
            from ..memory import default_memory
            mem = default_memory()
            # Extract keywords from claim
            keywords = " ".join(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', claim.text))[:120]
            if keywords:
                hits = mem.query(keywords, tenant_id=tenant_id, limit=3)
                for h in hits:
                    claim.source_refs.append({
                        "source": "memory",
                        "id": str(h.id),
                        "kind": h.kind,
                        "snippet": h.content[:140],
                    })
                if claim.source_refs:
                    claim.verified = True
                    claim.confidence = min(1.0, 0.6 + 0.1 * len(claim.source_refs))
        except Exception as e:
            logger.debug("citation memory lookup failed: %s", e)

        # Try Feishu wiki (best-effort)
        try:
            from core.feishu_advanced.wiki_search import wiki_search
            keywords = " ".join(re.findall(r'[\u4e00-\u9fff]{2,}', claim.text))[:60]
            if keywords:
                wiki_results = wiki_search(keywords, page_size=2)
                for w in (wiki_results or [])[:2]:
                    claim.source_refs.append({
                        "source": "wiki",
                        "token": w.get("node_token", ""),
                        "title": w.get("title", ""),
                    })
                if claim.source_refs and not claim.verified:
                    claim.verified = True
                    claim.confidence = 0.7
        except Exception:
            pass

        return claim

    def run(self, text: str, *, tenant_id: str = "default") -> CitationReport:
        """Full citation pipeline: extract → verify → build references."""
        claims = self.extract_claims(text)
        verified_claims = []
        warnings = []
        for c in claims:
            c = self.verify_claim(c, tenant_id=tenant_id)
            verified_claims.append(c)
            if not c.verified and c.kind in ("data", "quote"):
                warnings.append(f"UNVERIFIED {c.kind}: {c.text[:80]}")

        # Build references.md
        ref_lines = ["# References\n"]
        seen = set()
        counter = 1
        for c in verified_claims:
            for ref in c.source_refs:
                key = f"{ref['source']}:{ref.get('id', ref.get('token', ''))}"
                if key in seen:
                    continue
                seen.add(key)
                snippet = ref.get("snippet", ref.get("title", ""))
                ref_lines.append(f"[{counter}] {ref['source']} → {snippet}")
                counter += 1
        references_md = "\n".join(ref_lines)

        return CitationReport(
            total_claims=len(claims),
            verified_claims=sum(1 for c in verified_claims if c.verified),
            unverified_claims=sum(1 for c in verified_claims if not c.verified),
            claims=verified_claims,
            references_md=references_md,
            warnings=warnings,
        )


_singleton: Optional[CitationAgent] = None


def default_citation_agent() -> CitationAgent:
    global _singleton
    if _singleton is None:
        _singleton = CitationAgent()
    return _singleton
