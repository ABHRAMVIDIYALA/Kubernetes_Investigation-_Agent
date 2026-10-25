from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import json
import uuid

class FailureCategory(str, Enum):
    OOM_KILLED = "OOM_KILLED"
    CRASH_LOOP_BACKOFF = "CRASH_LOOP_BACKOFF"
    IMAGE_PULL_FAILURE = "IMAGE_PULL_FAILURE"
    PROBE_FAILURE = "PROBE_FAILURE"
    NETWORK_DNS_TIMEOUT = "NETWORK_DNS_TIMEOUT"
    DATABASE_CONNECTION_ERROR = "DATABASE_CONNECTION_ERROR"
    STORAGE_MOUNT_FAILURE = "STORAGE_MOUNT_FAILURE"
    RBAC_PERMISSION_DENIED = "RBAC_PERMISSION_DENIED"
    APPLICATION_PANIC = "APPLICATION_PANIC"
    CPU_THROTTLING = "CPU_THROTTLING"
    NODE_MEMORY_PRESSURE = "NODE_MEMORY_PRESSURE"
    NODE_NOT_READY = "NODE_NOT_READY"
    INCORRECT_RESOURCE_SPEC = "INCORRECT_RESOURCE_SPEC"
    SERVICE_NO_ENDPOINTS = "SERVICE_NO_ENDPOINTS"
    SERVICE_ROUTES_TO_UNHEALTHY_PODS = "SERVICE_ROUTES_TO_UNHEALTHY_PODS"
    UNKNOWN_ANOMALY = "UNKNOWN_ANOMALY"

class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

@dataclass
class EvidenceItem:
    line_number: int
    raw_content: str
    significance: str
    timestamp: Optional[str] = None
    log_level: Optional[str] = None
    matched_pattern: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class K8sResourceContext:
    pod_name: Optional[str] = None
    namespace: Optional[str] = None
    container_name: Optional[str] = None
    node_name: Optional[str] = None
    image: Optional[str] = None
    exit_code: Optional[int] = None
    restart_count: Optional[int] = None

@dataclass
class InvestigationResult:
    incident_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    investigation_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    primary_category: FailureCategory = FailureCategory.UNKNOWN_ANOMALY
    severity: Severity = Severity.MEDIUM
    confidence_score: float = 0.0
    summary: str = ""
    root_cause_analysis: str = ""
    resource_context: K8sResourceContext = field(default_factory=K8sResourceContext)
    evidence_timeline: List[EvidenceItem] = field(default_factory=list)
    remediation_steps: List[str] = field(default_factory=list)
    verification_commands: List[str] = field(default_factory=list)
    additional_notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)
