import re
from typing import List, Dict, Any, Tuple
from .models import FailureCategory, Severity, EvidenceItem
from .parser import ParsedLogEntry

class DiagnosticRule:
    def __init__(
        self,
        name: str,
        category: FailureCategory,
        severity: Severity,
        patterns: List[str],
        significance_template: str,
        confidence_weight: float = 1.0,
        case_sensitive: bool = False
    ):
        self.name = name
        self.category = category
        self.severity = severity
        self.significance_template = significance_template
        self.confidence_weight = confidence_weight
        flags = 0 if case_sensitive else re.IGNORECASE
        self.regexes = [re.compile(p, flags) for p in patterns]

    def match(self, entry: ParsedLogEntry) -> Tuple[bool, str, str]:
        for reg in self.regexes:
            match = reg.search(entry.message) or reg.search(entry.raw_text)
            if match:
                matched_str = match.group(0)
                significance = self.significance_template.format(matched=matched_str)
                return True, matched_str, significance
        return False, "", ""

class K8sDiagnosticEngine:
    def __init__(self):
        self.rules: List[DiagnosticRule] = [
            # OOM Killed
            DiagnosticRule(
                name="cgroup_oom_killed",
                category=FailureCategory.OOM_KILLED,
                severity=Severity.CRITICAL,
                patterns=[
                    r"cgroup out of memory: Kill(?:ed)? process",
                    r"Memory cgroup out of memory",
                    r"Container.*terminated.*OOMKilled",
                    r"Killed process \d+ \([^\)]+\) total-vm:\d+kB, anon-rss:\d+kB",
                    r"oom_reaper: reaped process",
                    r"exit code[:=\s]+137\b",
                    r"exited with status 137\b"
                ],
                significance_template="Direct evidence of Linux cgroup OOM kill (kernel terminated process exceeding memory limit)",
                confidence_weight=1.5
            ),
            DiagnosticRule(
                name="runtime_memory_exhaustion",
                category=FailureCategory.OOM_KILLED,
                severity=Severity.CRITICAL,
                patterns=[
                    r"java\.lang\.OutOfMemoryError(?::\s+Java heap space)?",
                    r"fatal error: runtime: out of memory",
                    r"JavaScript heap out of memory",
                    r"MemoryError\b",
                    r"GC overhead limit exceeded"
                ],
                significance_template="Application runtime memory exhaustion observed prior to exit",
                confidence_weight=1.3
            ),

            # CrashLoopBackOff
            DiagnosticRule(
                name="crash_loop_backoff",
                category=FailureCategory.CRASH_LOOP_BACKOFF,
                severity=Severity.HIGH,
                patterns=[
                    r"CrashLoopBackOff",
                    r"Back-off restarting failed container",
                    r"Error: pod \S+ container \S+ is crashing",
                    r"restart count.*exceeded"
                ],
                significance_template="Kubelet reports container is repeatedly dying and placed into exponential back-off",
                confidence_weight=1.2
            ),

            # Image Pull Issues
            DiagnosticRule(
                name="image_pull_failure",
                category=FailureCategory.IMAGE_PULL_FAILURE,
                severity=Severity.HIGH,
                patterns=[
                    r"ImagePullBackOff",
                    r"ErrImagePull",
                    r"manifest for \S+ not found",
                    r"pull access denied for \S+",
                    r"failed to resolve reference \S+",
                    r"rpc error: code = NotFound desc = failed to pull and unpack image",
                    r"toomanyrequests: You have reached your pull rate limit"
                ],
                significance_template="Container runtime failed to download or authenticate image from registry",
                confidence_weight=1.4
            ),

            # Probe Failures
            DiagnosticRule(
                name="liveness_probe_failed",
                category=FailureCategory.PROBE_FAILURE,
                severity=Severity.HIGH,
                patterns=[
                    r"Liveness probe failed:.*(?:HTTP status code 5\d\d|connection refused|timeout)",
                    r"Readiness probe failed:.*(?:HTTP status code 5\d\d|connection refused|timeout)",
                    r"Startup probe failed:.*(?:HTTP status code 5\d\d|connection refused|timeout)",
                    r"Probe failed: Get \"https?:\/\/[^\"]+\": (?:context deadline exceeded|dial tcp)"
                ],
                significance_template="Kubernetes health check probe failed, triggering pod restart or traffic removal",
                confidence_weight=1.3
            ),

            # Network & DNS
            DiagnosticRule(
                name="dns_resolution_failure",
                category=FailureCategory.NETWORK_DNS_TIMEOUT,
                severity=Severity.HIGH,
                patterns=[
                    r"dial tcp: lookup \S+(?: on \S+:53)?: no such host",
                    r"read: connection reset by peer",
                    r"read udp \S+:53: i/o timeout",
                    r"Name or service not known",
                    r"dial tcp \S+: i/o timeout",
                    r"Client\.Timeout exceeded while awaiting headers"
                ],
                significance_template="Inter-pod network or CoreDNS resolution timeout encountered",
                confidence_weight=1.2
            ),

            # Database Connection Errors
            DiagnosticRule(
                name="db_connection_error",
                category=FailureCategory.DATABASE_CONNECTION_ERROR,
                severity=Severity.HIGH,
                patterns=[
                    r"connection to server at \S+ failed: Connection refused",
                    r"remaining connection slots are reserved for non-replication superuser connections",
                    r"Pool exhausted, timeout waiting for connection",
                    r"Communications link failure",
                    r"too many connections\b"
                ],
                significance_template="Database connection pool saturated or database unreachable from pod",
                confidence_weight=1.2
            ),

            # Storage & Volume Failures
            DiagnosticRule(
                name="storage_mount_error",
                category=FailureCategory.STORAGE_MOUNT_FAILURE,
                severity=Severity.HIGH,
                patterns=[
                    r"FailedAttachVolume",
                    r"FailedMount",
                    r"MountVolume\.SetUp failed for volume",
                    r"Read-only file system",
                    r"No space left on device"
                ],
                significance_template="PVC or volume mount failed to attach to host node",
                confidence_weight=1.4
            ),

            # RBAC
            DiagnosticRule(
                name="rbac_forbidden",
                category=FailureCategory.RBAC_PERMISSION_DENIED,
                severity=Severity.MEDIUM,
                patterns=[
                    r"is forbidden: User \"\S+\" cannot \S+ resource \"\S+\" in API group",
                    r"403 Forbidden",
                    r"User \S+ does not have permission to"
                ],
                significance_template="ServiceAccount lacks necessary RBAC ClusterRole or RoleBinding permissions",
                confidence_weight=1.3
            ),

            # Application Panic / Exception
            DiagnosticRule(
                name="app_panic_sigsegv",
                category=FailureCategory.APPLICATION_PANIC,
                severity=Severity.CRITICAL,
                patterns=[
                    r"panic: runtime error:",
                    r"fatal error: unexpected signal during runtime",
                    r"Segmentation fault",
                    r"exit code[:=\s]+139\b",
                    r"exited with status 139\b",
                    r"Unhandled exception\. System\."
                ],
                significance_template="Application crashed abruptly due to unhandled runtime panic or segmentation fault (SIGSEGV)",
                confidence_weight=1.3
            ),

            # CPU Throttling
            DiagnosticRule(
                name="cfs_cpu_throttling",
                category=FailureCategory.CPU_THROTTLING,
                severity=Severity.HIGH,
                patterns=[
                    r"CFS quota throttling",
                    r"CFS period consumed",
                    r"CPU quota exhausted",
                    r"execution periods throttled",
                    r"Event loop tick delay exceeded",
                    r"nr_throttled"
                ],
                significance_template="Process execution severely throttled by Linux CFS quota limit ({matched})",
                confidence_weight=1.4
            ),

            # Node Memory Pressure & Eviction
            DiagnosticRule(
                name="node_memory_pressure_eviction",
                category=FailureCategory.NODE_MEMORY_PRESSURE,
                severity=Severity.CRITICAL,
                patterns=[
                    r"NodeHasMemoryPressure",
                    r"The node was low on resource:\s*memory",
                    r"low on resource:\s*memory",
                    r"evicted due to node condition",
                    r"(?:evicting|evict)\s+pod\s+.*to\s+reclaim",
                    r"EvictionThresholdMet",
                    r"Host Memory Pressure",
                    r"MemoryPressure\s*:\s*True",
                    r"MemoryPressure\s+True",
                    r"KubeletHasMemoryPressure",
                    r"node\.kubernetes\.io/memory-pressure",
                    r"MEMORY PRESSURE DETECTED"
                ],
                significance_template="Kubelet actively evicting pods due to host node memory exhaustion ({matched})",
                confidence_weight=1.5
            ),

            # Node Not Ready
            DiagnosticRule(
                name="node_not_ready_pleg",
                category=FailureCategory.NODE_NOT_READY,
                severity=Severity.CRITICAL,
                patterns=[
                    r"PLEG is not healthy",
                    r"Node.*status is now:\s*NodeNotReady",
                    r"Kubelet stopped posting node status",
                    r"container runtime containerd did not respond",
                    r"KubeletNotReady",
                    r"Ready\s*:\s*(?:False|Unknown)",
                    r"Ready\s+(?:False|Unknown)",
                    r"node\.kubernetes\.io/not-ready",
                    r"node\.kubernetes\.io/unreachable",
                    r"NodeNotReady",
                    r"PLEGIsNotHealthy",
                    r"UNHEALTHY / NOT READY"
                ],
                significance_template="Node transition to NotReady due to Kubelet or containerd PLEG heartbeat failure ({matched})",
                confidence_weight=1.5
            ),

            # Incorrect Resource Specification / Unschedulable
            DiagnosticRule(
                name="incorrect_resource_spec_unschedulable",
                category=FailureCategory.INCORRECT_RESOURCE_SPEC,
                severity=Severity.HIGH,
                patterns=[
                    r"\d+/\d+ nodes are available:\s*\d+ Insufficient (?:cpu|memory)",
                    r"Insufficient cpu",
                    r"Insufficient memory",
                    r"FailedScheduling.*Insufficient",
                    r"No preemption victims found"
                ],
                significance_template="Pod unschedulable because requested CPU/RAM exceeds maximum allocatable node capacity ({matched})",
                confidence_weight=1.4
            ),

            # Service Has No Endpoints
            DiagnosticRule(
                name="service_no_endpoints",
                category=FailureCategory.SERVICE_NO_ENDPOINTS,
                severity=Severity.CRITICAL,
                patterns=[
                    r"Endpoints:\s*<none>",
                    r"Service has 0 endpoints matching selector",
                    r"matching selector .* has 0 endpoints",
                    r"NoEndpoints"
                ],
                significance_template="Kubernetes Service selector does not match any Ready pod labels, dropping all incoming traffic ({matched})",
                confidence_weight=1.4
            ),

            # Service Routes to Unhealthy / Canary Pods
            DiagnosticRule(
                name="service_routes_to_unhealthy_pods",
                category=FailureCategory.SERVICE_ROUTES_TO_UNHEALTHY_PODS,
                severity=Severity.HIGH,
                patterns=[
                    r"Updated endpoints with \d+ addresses:.*10\.\d+\.\d+\.\d+",
                    r"Missing Redis schema migration",
                    r"Readiness probe HTTP 500.*canary",
                    r"canary.*failing requests",
                    r"Responding HTTP 500 Internal Server Error"
                ],
                significance_template="Service selector overlapping with experimental/canary pods, routing user traffic to failing instances ({matched})",
                confidence_weight=1.3
            )
        ]

    def analyze_entries(self, entries: List[ParsedLogEntry]) -> Tuple[FailureCategory, Severity, float, List[EvidenceItem]]:
        category_scores: Dict[FailureCategory, float] = {}
        category_severities: Dict[FailureCategory, Severity] = {}
        evidence_list: List[EvidenceItem] = []

        for entry in entries:
            for rule in self.rules:
                matched, matched_str, significance = rule.match(entry)
                if matched:
                    # Update category score
                    category_scores[rule.category] = category_scores.get(rule.category, 0.0) + rule.confidence_weight
                    # Highest severity wins
                    if rule.category not in category_severities or self._is_higher_severity(rule.severity, category_severities[rule.category]):
                        category_severities[rule.category] = rule.severity

                    evidence = EvidenceItem(
                        line_number=entry.line_number,
                        raw_content=entry.raw_text,
                        significance=significance,
                        timestamp=entry.timestamp,
                        log_level=entry.level,
                        matched_pattern=matched_str,
                        metadata={"rule": rule.name, "category": rule.category.value}
                    )
                    evidence_list.append(evidence)

        if not category_scores:
            # Fallback check for general errors
            error_count = sum(1 for e in entries if e.level in ("ERROR", "FATAL", "CRITICAL", "PANIC"))
            if error_count > 0:
                return FailureCategory.UNKNOWN_ANOMALY, Severity.MEDIUM, 0.4, evidence_list
            return FailureCategory.UNKNOWN_ANOMALY, Severity.LOW, 0.1, []

        # Find top scoring category
        best_category = max(category_scores.items(), key=lambda x: x[1])[0]
        best_score = category_scores[best_category]
        severity = category_severities[best_category]

        # Normalize confidence to [0.5, 0.99]
        confidence = min(0.98, 0.5 + (best_score * 0.15))

        # Filter evidence to prioritize top category items first, then others
        sorted_evidence = sorted(
            evidence_list,
            key=lambda item: (0 if item.metadata.get("category") == best_category.value else 1, item.line_number)
        )

        return best_category, severity, confidence, sorted_evidence

    def _is_higher_severity(self, candidate: Severity, current: Severity) -> bool:
        rank = {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}
        return rank.get(candidate, 0) > rank.get(current, 0)
