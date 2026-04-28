"""Security Auditor · 审查输出是否有安全问题（prompt injection, PII, secret leak）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..permissions import SECRET_PATTERNS


@dataclass
class SecurityReport:
    findings: List[str] = field(default_factory=list)
    severity: str = "low"  # low/medium/high/critical
    safe: bool = True


class SecurityAuditor:
    def audit(self, text: str) -> SecurityReport:
        report = SecurityReport()

        # Secret scan
        for name, pat in SECRET_PATTERNS:
            if re.search(pat, text):
                report.findings.append(f"CRITICAL: secret pattern '{name}' found")
                report.severity = "critical"
                report.safe = False

        # PII scan (simplified)
        pii_patterns = [
            ("phone_cn", r'\b1[3-9]\d{9}\b'),
            ("id_card_cn", r'\b\d{17}[\dXx]\b'),
            ("email", r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'),
            ("credit_card", r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'),
        ]
        for name, pat in pii_patterns:
            if re.search(pat, text):
                report.findings.append(f"PII detected: {name}")
                if report.severity in ("low", "medium"):
                    report.severity = "high"

        # Prompt injection patterns
        injection_patterns = [
            r'ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions',
            r'忽略\s*(?:之前|以上|上面)(?:的)?(?:指令|命令)',
            r'system\s*:\s*(?:you\s+are|act\s+as)',
            r'<\s*system\s*>',
        ]
        for pat in injection_patterns:
            if re.search(pat, text, re.IGNORECASE):
                report.findings.append(f"potential prompt injection pattern")
                if report.severity == "low":
                    report.severity = "medium"

        if report.findings:
            report.safe = report.severity not in ("high", "critical")
        return report


_singleton: Optional[SecurityAuditor] = None


def default_security_auditor() -> SecurityAuditor:
    global _singleton
    if _singleton is None:
        _singleton = SecurityAuditor()
    return _singleton
