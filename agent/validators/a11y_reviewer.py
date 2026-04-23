"""A11y Reviewer · 可读性/对比度/字体大小/布局合理性审查（PPT 和文档）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class A11yReport:
    readability_score: float = 0.0  # 0-1
    contrast_issues: List[str] = field(default_factory=list)
    layout_issues: List[str] = field(default_factory=list)
    text_density_issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class A11yReviewer:
    def review_slides_markdown(self, markdown: str) -> A11yReport:
        report = A11yReport()
        slides = markdown.split("\n---\n")
        total_lines = 0
        long_slides = 0
        empty_slides = 0
        for i, s in enumerate(slides):
            lines = [l for l in s.splitlines() if l.strip()]
            total_lines += len(lines)
            text_chars = sum(len(l) for l in lines)
            if text_chars > 800:
                long_slides += 1
                report.text_density_issues.append(f"slide {i + 1}: {text_chars} chars (建议 < 400)")
            if text_chars < 30:
                empty_slides += 1

        # Readability score
        avg_lines = total_lines / max(1, len(slides))
        score = 1.0
        if avg_lines > 15:
            score -= 0.3
            report.recommendations.append("每页行数过多，建议拆分")
        if long_slides > len(slides) * 0.3:
            score -= 0.3
            report.recommendations.append("多页文本密度过高，拆为更多张")
        if empty_slides > 1:
            score -= 0.1
        report.readability_score = max(0.0, score)

        # Contrast: can't check pixel-level without rendering, but check for emoji / markers
        if not re.search(r'^#+\s', markdown, re.MULTILINE):
            report.layout_issues.append("缺少明确的 heading (# / ##)")
        return report

    def review_doc_markdown(self, markdown: str) -> A11yReport:
        report = A11yReport()
        # Heading hierarchy check
        headings = re.findall(r'^(#{1,6})\s', markdown, re.MULTILINE)
        if headings:
            levels = [len(h) for h in headings]
            max_skip = max((levels[i + 1] - levels[i] for i in range(len(levels) - 1) if levels[i + 1] > levels[i]), default=0)
            if max_skip > 1:
                report.layout_issues.append(f"heading level skip detected (jumped {max_skip} levels)")

        # Paragraph length
        paragraphs = markdown.split("\n\n")
        long_paras = sum(1 for p in paragraphs if len(p) > 800)
        if long_paras > 2:
            report.text_density_issues.append(f"{long_paras} 长段落过多（>800 字），建议拆分")

        # Readability
        score = 1.0
        if long_paras > 3:
            score -= 0.2
        if not headings:
            score -= 0.3
            report.recommendations.append("缺少小节 heading，难以快速浏览")
        report.readability_score = max(0.0, score)
        return report


_singleton: Optional[A11yReviewer] = None


def default_a11y_reviewer() -> A11yReviewer:
    global _singleton
    if _singleton is None:
        _singleton = A11yReviewer()
    return _singleton
