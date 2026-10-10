# 🛡️ Kubernetes Investigation Agent

An intelligent Python-based Kubernetes investigation agent. It uses the **`Get_Pod_logs`** and **`Get_Pod_events`** tools to fetch logs and events directly from live Kubernetes cluster pods, extracts timeline evidence, identifies the root cause of failures, and generates an actionable incident investigation report with remediation steps and verification commands.

---

## 🚀 Features

- **Direct Cluster Tooling**:
  - **`Get_Pod_logs`**: Fetches logs directly from Kubernetes pods via `kubectl`, supporting namespaces, multi-container pods, line tailing, previous terminated instances, and timestamps.
  - **`Get_Pod_events`**: Fetches chronological Kubernetes cluster events for specific pods, capturing events like `OOMKilling`, `BackOff`, `FailedScheduling`, `Unhealthy`, and `FailedMount`.
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
│   ├── __init__.py           # Package exports (exposes Get_Pod_logs, Get_Pod_events, K8sInvestigationAgent)
│   ├── tools.py              # Cluster tools: Get_Pod_logs & Get_Pod_events
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
Specify the pod name and namespace to fetch both logs and events directly from the cluster:

```bash
# Investigate a pod in default namespace (fetches logs + correlates events)
python k8s_investigator.py --pod payment-service-589f8dc94-p9w7c

# Specify namespace and tail count
python k8s_investigator.py --pod order-processor-abc -n ecommerce --tail 500

# Investigate a crashed or OOMKilled pod (fetches previous container instance logs)
python k8s_investigator.py --pod crashed-worker-xyz -n prod --previous

# Fetch only the events of a pod using Get_Pod_events
python k8s_investigator.py --pod payment-service-xyz -n prod --events-only
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

The test suite validates the `Get_Pod_logs` and `Get_Pod_events` tools, pattern matching, parsing, and report generation:
```bash
python test_k8s_agent.py
```

---

## 🐍 Programmatic Python API

You can call **`Get_Pod_logs`** and **`Get_Pod_events`** directly or use **`investigate_pod`**:

```python
from k8s_agent import Get_Pod_logs, Get_Pod_events, K8sInvestigationAgent, ReportFormatter

# 1. Fetch pod events directly:
events = Get_Pod_events(
    pod_name="payment-service-589f8dc94-p9w7c",
    namespace="production"
)
print(events)

# 2. Fetch pod logs directly:
raw_logs = Get_Pod_logs(
    pod_name="payment-service-589f8dc94-p9w7c",
    namespace="production",
    previous=True
)

# 3. End-to-end investigation with automatic log & event correlation:
agent = K8sInvestigationAgent()
result = agent.investigate_pod(
    pod_name="payment-service-589f8dc94-p9w7c",
    namespace="production",
    include_events=True
)

print(f"Incident: {result.incident_id}")
print(f"Severity: {result.severity}")
print(f"Category: {result.primary_category}")
print(f"Root Cause: {result.root_cause_analysis}")

# Print Console / Markdown report
print(ReportFormatter.to_console(result))
```
