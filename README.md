# 🛡️ Kubernetes Investigation Agent

An intelligent Python-based Kubernetes investigation agent. It uses the **`get_pod_logs`**, **`get_pod_events`**, and **`get_deployment_history`** tools to fetch logs, events, and deployment revision history directly from Kubernetes clusters, analyzes recent changes in pod versions/container images, extracts timeline evidence, identifies failure root causes, and generates actionable incident reports with remediation steps and rollback commands.

---

## 🚀 Features

- **Direct Cluster Tooling**:
  - **`get_pod_logs`** (`Get_Pod_logs`): Fetches logs directly from Kubernetes pods via `kubectl`, supporting namespaces, multi-container pods, line tailing, previous terminated instances, and timestamps.
  - **`get_pod_events`** (`Get_Pod_events`): Fetches chronological Kubernetes cluster events for specific pods, capturing events like `OOMKilling`, `BackOff`, `FailedScheduling`, `Unhealthy`, and `FailedMount`.
  - **`get_deployment_history`** (`Get_deployment_history`): Fetches and analyzes rollout history and revision pod templates to detect recent container image and pod version updates, tag changes, rollout causes, and generates instant rollback commands (`kubectl rollout undo`).
  - **`get_node_info`** (`Get_node_info`): Fetches and analyzes host node infrastructure health, conditions (`Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`), active taints (`NoSchedule`/`NoExecute`), allocatable vs capacity limits, and prescribes host-level remediation commands.
  - **`triage_low_confidence_incident`** (`triage_low_confidence`): Specifically designed for incidents where diagnostic confidence is low or evidence items are few. Performs deep multi-surface triage across previous termination logs (`--previous`), pod events, node health (`get_node_info`), and rollout changes (`get_deployment_history`) to elevate confidence or generate an SRE escalation triage playbook.
- **Pod Version & Rollout Correlation**: Automatically links application crashes and failure onset with recent deployment rollouts and image version updates.
- **Event-Log Correlation**: Merges runtime container crash logs with cluster-level lifecycle events for complete diagnostic confidence.
- **Multi-Format Log Parser**: Parses CRI container format (`stdout`/`stderr`), structured JSON logs, and plain syslog formats with timestamps.
- **Automatic Resource Context Extraction**: Detects Pod name, Namespace, Container, Node, Image, and Exit codes (e.g. `137`, `139`, `1`) automatically.
- **Deep Failure Detection**:
  - **`OOM_KILLED`**: Linux cgroup memory limit exceeded, JVM heap exhaustion, kernel OOM-killer invocations, Exit Code 137.
  - **`CRASH_LOOP_BACKOFF`**: Container start failures and exponential restart delays.
  - **`IMAGE_PULL_FAILURE`**: `ImagePullBackOff`, `ErrImagePull`, missing tags, registry authentication errors.
  - **`PROBE_FAILURE`**: Liveness, readiness, and startup probe timeouts and HTTP 5xx failures.
  - **`NETWORK_DNS_TIMEOUT`**: CoreDNS timeouts, upstream connection resets, TCP dial timeouts.
  - **`DATABASE_CONNECTION_ERROR`**: Pool exhaustion, deadlock, refused socket connections.
  - **`STORAGE_MOUNT_FAILURE`**: PVC attachment failures, volume mount timeouts, read-only filesystem.
  - **`RBAC_PERMISSION_DENIED`**: 403 Forbidden, missing ClusterRole / RoleBinding.
  - **`APPLICATION_PANIC`**: Uncaught runtime exceptions and segmentation faults (Exit code 139).
- **Evidence Timeline**: Pairs every hypothesis with exact line numbers, timestamps, log levels, and significance notes.
- **Actionable Remediation**: Generates tailored `kubectl` commands and manifest fixes.
- **Multiple Output Formats**: Supports styled **Console**, **Markdown**, and structured **JSON**.
- **Dual Engine**: Runs 100% offline via the built-in diagnostic rule engine, with optional **Google Gemini LLM synthesis** when `GEMINI_API_KEY` is provided.

---

## 📂 Project Structure

```
c:\K8agent\
├── k8s_agent/
│   ├── __init__.py           # Package exports (exposes get_deployment_history, get_pod_logs, get_pod_events)
│   ├── tools.py              # Cluster tools: get_pod_logs, get_pod_events, get_deployment_history
│   ├── models.py             # Dataclasses: InvestigationResult, EvidenceItem, K8sResourceContext
│   ├── parser.py             # Log parsing & entity extraction (JSON, CRI, Plain text)
│   ├── detectors.py          # Diagnostic rules & pattern engine
│   ├── remediation.py        # RCA generator & kubectl remediation advice
│   ├── formatter.py          # Markdown & Console report formatters
│   └── investigator.py       # Core K8sInvestigationAgent class
├── samples/
│   ├── sample_oom_kill.log       # Real-world OOMKilled scenario
│   ├── sample_crashloop_dns.log  # CoreDNS timeout & CrashLoopBackOff scenario
│   └── sample_probe_timeout.log  # Liveness/Readiness probe failure scenario
├── k8s_investigator.py       # CLI Entrypoint (prioritizes --pod with Get_Pod_logs & Get_Pod_events)
├── test_k8s_agent.py         # Unit & integration test suite (15 tests passing)
└── README.md
```

---

## 🛠️ Usage

### 1. Primary Usage: Live Pod Investigation
Specify the pod name and namespace to fetch logs, events, and deployment rollout history directly from the cluster:

```bash
# Investigate a pod in default namespace (fetches logs + correlates events & deployment history)
python k8s_investigator.py --pod payment-service-589f8dc94-p9w7c

# Specify namespace and tail count
python k8s_investigator.py --pod order-processor-abc -n ecommerce --tail 500

# Investigate a crashed or OOMKilled pod (fetches previous container instance logs)
python k8s_investigator.py --pod crashed-worker-xyz -n prod --previous

# Fetch only the events of a pod using get_pod_events
python k8s_investigator.py --pod payment-service-xyz -n prod --events-only

# Fetch and analyze recent pod version changes & rollout history using get_deployment_history
python k8s_investigator.py --pod payment-service-589f8dc94-p9w7c -n prod --history-only

# Analyze deployment rollout history by deployment name
python k8s_investigator.py --deployment payment-service -n prod --history-only

# Inspect a specific revision
python k8s_investigator.py -d payment-service -n prod --revision 2 --history-only
```

Export report directly to a Markdown or JSON file:
```bash
# Markdown report
python k8s_investigator.py -p payment-service-589f8dc94-p9w7c -n prod --format markdown -o report.md

# JSON output for automated CI/CD or Alertmanager webhooks
python k8s_investigator.py -p payment-service-589f8dc94-p9w7c -n prod --format json -o report.json
```

---

### 2. Offline / Fallback Usage

#### Run Built-in Demonstration
```bash
python k8s_investigator.py --demo
```

#### Investigate a Local Log File
```bash
python k8s_investigator.py --file samples/sample_oom_kill.log
```

---

## 🧪 Running Tests

The test suite validates the `get_pod_logs`, `get_pod_events`, and `get_deployment_history` tools, version diffing, pattern matching, parsing, and report generation:
```bash
python test_k8s_agent.py
```

---

## 🐍 Programmatic Python API

You can call **`get_deployment_history`**, **`get_pod_logs`**, and **`get_pod_events`** directly or use **`investigate_pod`**:

```python
from k8s_agent import (
    get_deployment_history,
    get_pod_logs,
    get_pod_events,
    get_node_info,
    triage_low_confidence_incident,
    K8sInvestigationAgent,
    ReportFormatter,
)

# 1. Analyze node infrastructure health & conditions:
node_report = get_node_info(
    node_name="k8s-worker-node-14",
    analyze_node_health=True,
)
print(node_report)

# 2. Automated multi-surface triage for low-confidence / low-evidence incidents:
triage_result = triage_low_confidence_incident(
    target="connection reset unexpectedly",
    pod_name="checkout-worker-5899-xyz",
    namespace="production",
)
print(triage_result["report"])

# 3. Analyze recent pod version & container image changes:
history_analysis = get_deployment_history(
    pod_name="payment-service-589f8dc94-p9w7c",
    namespace="production",
    analyze_pod_version=True,
)
print(history_analysis)

# 4. End-to-end investigation with automatic log, event, node, & deployment correlation:
agent = K8sInvestigationAgent()
result = agent.investigate_pod(
    pod_name="payment-service-589f8dc94-p9w7c",
    namespace="production",
    include_events=True,
    include_deployment_history=True,
    include_node_info=True,
)

print(f"Incident: {result.incident_id}")
print(f"Severity: {result.severity}")
print(f"Category: {result.primary_category}")
print(f"Root Cause: {result.root_cause_analysis}")

# Print Console / Markdown report
print(ReportFormatter.to_console(result))
```

