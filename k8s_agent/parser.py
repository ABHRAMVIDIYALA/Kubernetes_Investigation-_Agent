import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from .models import K8sResourceContext

@dataclass
class ParsedLogEntry:
    line_number: int
    raw_text: str
    timestamp: Optional[str] = None
    level: Optional[str] = None
    message: str = ""
    is_json: bool = False
    json_data: Optional[Dict[str, Any]] = None
    stream: Optional[str] = None  # stdout, stderr

class K8sLogParser:
    # ISO 8601 / RFC 3339
    TIMESTAMP_REGEX = re.compile(
        r'\b(?P<ts>\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\b'
    )

    # Standard container log prefix (e.g., 2026-10-10T12:00:00.123456789Z stderr F message)
    CRI_PREFIX_REGEX = re.compile(
        r'^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\s+(?P<stream>stdout|stderr)\s+[FP]\s+(?P<msg>.*)$'
    )

    # Log levels
    LEVEL_REGEX = re.compile(
        r'\b(?P<lvl>FATAL|PANIC|EMERG|CRIT(?:ICAL)?|ERR(?:OR)?|WARN(?:ING)?|INFO|DEBUG|TRACE)\b',
        re.IGNORECASE
    )

    # Common Kubernetes entity extractors
    POD_REGEX = re.compile(r'\b(?:pod[s]?[\/:]\s*|\b)([a-z0-9][a-z0-9\-]{2,62}-[a-z0-9]{5,10}-[a-z0-9]{5})\b', re.IGNORECASE)
    NS_REGEX = re.compile(r'\b(?:namespace[s]?[\/:]\s*|\bns[\/:]\s*)([a-z0-9][a-z0-9\-]{1,62})\b', re.IGNORECASE)
    CONTAINER_REGEX = re.compile(r'\b(?:container[\/:]\s*|-c\s+)([a-z0-9][a-z0-9\-]{1,62})\b', re.IGNORECASE)
    EXIT_CODE_REGEX = re.compile(r'\b(?:exit(?:ed)?(?:\s+with)?(?:\s+code|\s+status)?[:=\s]+)(\d{1,3})\b', re.IGNORECASE)
    NODE_REGEX = re.compile(r'\b(?:node[\/:]\s*)([a-z0-9][a-z0-9\-\.]{1,62})\b', re.IGNORECASE)
    IMAGE_REGEX = re.compile(r'\b(?:image[:\s]+)([a-zA-Z0-9_\-\./]+:[a-zA-Z0-9_\-\.]+)\b')

    @classmethod
    def parse_line(cls, line_number: int, line: str) -> ParsedLogEntry:
        raw_text = line.rstrip("\r\n")
        trimmed = raw_text.strip()

        # Check if line is structured JSON
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                data = json.loads(trimmed)
                ts = data.get("time") or data.get("timestamp") or data.get("@timestamp")
                level = (
                    data.get("level") or data.get("severity") or data.get("log_level") or data.get("lvl")
                )
                msg = data.get("msg") or data.get("message") or data.get("error") or str(data)
                return ParsedLogEntry(
                    line_number=line_number,
                    raw_text=raw_text,
                    timestamp=str(ts) if ts else None,
                    level=str(level).upper() if level else None,
                    message=str(msg),
                    is_json=True,
                    json_data=data,
                )
            except json.JSONDecodeError:
                pass

        # Check CRI log prefix
        cri_match = cls.CRI_PREFIX_REGEX.match(raw_text)
        if cri_match:
            ts = cri_match.group("ts")
            stream = cri_match.group("stream")
            msg = cri_match.group("msg")
            lvl_match = cls.LEVEL_REGEX.search(msg)
            return ParsedLogEntry(
                line_number=line_number,
                raw_text=raw_text,
                timestamp=ts,
                level=lvl_match.group("lvl").upper() if lvl_match else ("ERROR" if stream == "stderr" else "INFO"),
                message=msg,
                stream=stream
            )

        # Standard plain text parsing
        ts = None
        ts_match = cls.TIMESTAMP_REGEX.search(raw_text)
        if ts_match:
            ts = ts_match.group("ts")

        lvl = None
        lvl_match = cls.LEVEL_REGEX.search(raw_text)
        if lvl_match:
            lvl = lvl_match.group("lvl").upper()

        return ParsedLogEntry(
            line_number=line_number,
            raw_text=raw_text,
            timestamp=ts,
            level=lvl,
            message=raw_text
        )

    @classmethod
    def parse_logs(cls, log_content: str) -> List[ParsedLogEntry]:
        lines = log_content.splitlines()
        entries = []
        for idx, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            entries.append(cls.parse_line(idx, line))
        return entries

    @classmethod
    def extract_resource_context(cls, entries: List[ParsedLogEntry]) -> K8sResourceContext:
        ctx = K8sResourceContext()
        for entry in entries:
            text = entry.raw_text

            if not ctx.pod_name:
                pod_m = cls.POD_REGEX.search(text)
                if pod_m:
                    ctx.pod_name = pod_m.group(1)

            if not ctx.namespace:
                ns_m = cls.NS_REGEX.search(text)
                if ns_m:
                    ctx.namespace = ns_m.group(1)

            if not ctx.container_name:
                c_m = cls.CONTAINER_REGEX.search(text)
                if c_m:
                    ctx.container_name = c_m.group(1)

            if not ctx.node_name:
                n_m = cls.NODE_REGEX.search(text)
                if n_m:
                    ctx.node_name = n_m.group(1)

            if not ctx.image:
                img_m = cls.IMAGE_REGEX.search(text)
                if img_m:
                    ctx.image = img_m.group(1)

            if ctx.exit_code is None:
                ec_m = cls.EXIT_CODE_REGEX.search(text)
                if ec_m:
                    try:
                        ctx.exit_code = int(ec_m.group(1))
                    except ValueError:
                        pass

        return ctx
