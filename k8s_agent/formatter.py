from typing import List
from .models import InvestigationResult, Severity, EvidenceItem

class ReportFormatter:
    SEVERITY_COLORS = {
        Severity.CRITICAL: "\033[91;1m",  # Bright Red
        Severity.HIGH: "\033[31m",       # Red
        Severity.MEDIUM: "\033[33m",     # Yellow
        Severity.LOW: "\033[36m",        # Cyan
        Severity.INFO: "\033[32m",       # Green
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    @classmethod
    def to_markdown(cls, res: InvestigationResult) -> str:
        md = []
        md.append(f"# 🛡️ Kubernetes Investigation Report: `{res.incident_id}`\n")
        md.append(f"**Generated:** {res.investigation_timestamp}  ")
        md.append(f"**Severity:** `{res.severity.value}` | **Primary Category:** `{res.primary_category.value}` | **Confidence:** `{res.confidence_score * 100:.1f}%`\n")

        # Resource Context
        md.append("## 📌 Detected Kubernetes Context")
        ctx = res.resource_context
        md.append(f"- **Pod:** `{ctx.pod_name or 'N/A'}`")
        md.append(f"- **Namespace:** `{ctx.namespace or 'default'}`")
        if ctx.container_name:
            md.append(f"- **Container:** `{ctx.container_name}`")
        if ctx.node_name:
            md.append(f"- **Node:** `{ctx.node_name}`")
        if ctx.image:
            md.append(f"- **Image:** `{ctx.image}`")
        if ctx.exit_code is not None:
            md.append(f"- **Exit Code:** `{ctx.exit_code}`")
        md.append("")

        # Summary & RCA
        md.append("## 🔍 Executive Summary")
        md.append(f"{res.summary}\n")

        md.append("## 🧠 Root Cause Analysis (RCA)")
        md.append(f"{res.root_cause_analysis}\n")

        # Evidence Timeline
        md.append("## 📜 Supporting Evidence & Timeline")
        if not res.evidence_timeline:
            md.append("_No definitive error signatures isolated in log stream._\n")
        else:
            md.append("| Line | Timestamp | Level | Significance | Excerpt |")
            md.append("| :--- | :--- | :--- | :--- | :--- |")
            for item in res.evidence_timeline[:12]:  # Limit top 12
                ts = item.timestamp or "—"
                lvl = item.log_level or "LOG"
                sig = item.significance
                raw = item.raw_content.replace("|", "\\|")
                if len(raw) > 90:
                    raw = raw[:87] + "..."
                md.append(f"| L{item.line_number} | `{ts}` | `{lvl}` | {sig} | `{raw}` |")
            if len(res.evidence_timeline) > 12:
                md.append(f"\n_... and {len(res.evidence_timeline) - 12} additional matching evidence lines._")
            md.append("")

        # Remediation
        md.append("## 🛠️ Recommended Remediation Steps")
        for i, step in enumerate(res.remediation_steps, 1):
            md.append(f"{i}. {step}")
        md.append("")

        # Verification
        md.append("## ✅ Verification Commands")
        for cmd in res.verification_commands:
            md.append(f"```bash\n{cmd}\n```")
        md.append("")

        if res.additional_notes:
            md.append(f"## 📝 Additional Notes\n{res.additional_notes}\n")

        return "\n".join(md)

    @classmethod
    def to_console(cls, res: InvestigationResult, use_color: bool = True) -> str:
        color = cls.SEVERITY_COLORS.get(res.severity, "") if use_color else ""
        reset = cls.RESET if use_color else ""
        bold = cls.BOLD if use_color else ""
        dim = cls.DIM if use_color else ""

        lines = []
        border = "=" * 76
        lines.append(f"{bold}{border}{reset}")
        lines.append(f"{bold} 🛡️  KUBERNETES INCIDENT INVESTIGATION REPORT: {res.incident_id}{reset}")
        lines.append(f"{bold}{border}{reset}")
        lines.append(f" Timestamp:  {res.investigation_timestamp}")
        lines.append(f" Severity:   {color}[{res.severity.value}]{reset}")
        lines.append(f" Category:   {bold}{res.primary_category.value}{reset}")
        lines.append(f" Confidence: {res.confidence_score * 100:.1f}%\n")

        # Context
        lines.append(f"{bold}--- AFFECTED RESOURCE CONTEXT ---{reset}")
        ctx = res.resource_context
        lines.append(f" Pod:        {ctx.pod_name or 'N/A'}")
        lines.append(f" Namespace:  {ctx.namespace or 'default'}")
        if ctx.container_name:
            lines.append(f" Container:  {ctx.container_name}")
        if ctx.node_name:
            lines.append(f" Node:       {ctx.node_name}")
        if ctx.exit_code is not None:
            lines.append(f" Exit Code:  {ctx.exit_code}")
        lines.append("")

        # Summary & RCA
        lines.append(f"{bold}--- EXECUTIVE SUMMARY ---{reset}")
        lines.append(f" {res.summary}\n")

        lines.append(f"{bold}--- ROOT CAUSE ANALYSIS (RCA) ---{reset}")
        for r_line in res.root_cause_analysis.split("\n"):
            lines.append(f" {r_line}")
        lines.append("")

        # Evidence
        lines.append(f"{bold}--- SUPPORTING EVIDENCE & LOG CITATIONS ({len(res.evidence_timeline)} items) ---{reset}")
        if not res.evidence_timeline:
            lines.append(" No specific error signatures identified.")
        else:
            for item in res.evidence_timeline[:8]:
                ts = f"[{item.timestamp}] " if item.timestamp else ""
                lvl = f"[{item.log_level}] " if item.log_level else ""
                lines.append(f" • {bold}Line {item.line_number}:{reset} {dim}{ts}{lvl}{reset}{item.significance}")
                lines.append(f"   {dim}> {item.raw_content[:100]}{reset}")
            if len(res.evidence_timeline) > 8:
                lines.append(f"   {dim}... {len(res.evidence_timeline) - 8} more evidence lines recorded.{reset}")
        lines.append("")

        # Remediation
        lines.append(f"{bold}--- RECOMMENDED REMEDIATION STEPS ---{reset}")
        for i, step in enumerate(res.remediation_steps, 1):
            lines.append(f" {i}. {step}")
        lines.append("")

        # Verification
        lines.append(f"{bold}--- VERIFICATION COMMANDS ---{reset}")
        for cmd in res.verification_commands:
            lines.append(f" $ {cmd}")
        lines.append(f"\n{bold}{border}{reset}\n")

        return "\n".join(lines)
