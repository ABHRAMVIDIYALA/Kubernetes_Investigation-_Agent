# ⚖️ Evaluation Benchmark Comparison: Latest vs. Baseline

**Comparison Date:** `2026-10-25T08:26:57.392189+00:00`  
**Latest Traces:** [`samples/evaluation_traces.json`](file:///c:/K8agent/samples/evaluation_traces.json)  
**Baseline Traces:** [`samples/baseline_traces.json`](file:///c:/K8agent/samples/baseline_traces.json)  
**Dataset:** [`samples/evaluation_dataset.json`](file:///c:/K8agent/samples/evaluation_dataset.json)  

---

## 📊 Aggregate Metric Comparison

| Benchmark Metric | Baseline (v1.0) | Latest (v2.0 with Node & Rollout Tools) | Absolute Delta | Relative Improvement | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Root Cause Accuracy** | `40.0%` (4/10) | **`100.0%` (10/10)** | **`+60.0%`** | **`+150.0%`** | 🟢 **MAJOR UPGRADE** |
| **Evidence Extraction** | `17 items` (avg 1.7) | **`45 items` (avg 4.5)** | **`+28 items`** | **`+164.7%`** | 🟢 **HIGH RECALL** |
| **Mean Diagnostic Confidence** | `0.563` | **`0.965`** | **`+0.402`** | **`+71.4%`** | 🟢 **OPTIMAL CALIBRATION** |
| **Mean Latency** | `2.25 ms` | **`2.03 ms`** | **`-0.22 ms`** | **`9.8% faster`** | 🟢 **SUB-3MS REAL-TIME** |
| **Overall Benchmark Grade** | `F (44.2%)` | **`A+ (99.1%)`** | **`+54.9 pts`** | **`+124.2%`** | 🟢 **EXCELLENCE** |

---

## 📋 Incident-by-Incident Comparison Matrix

| # | Case ID | Incident Scenario | Baseline Detected | Latest Detected | Baseline Conf. | Latest Conf. | Evidence Δ | Verdict Transition |
| :-: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | **`K8S-EVAL-001`** | Container OOMKilled via Linux Cgroup Memory Limit Exhaustion | `OOM_KILLED` | `OOM_KILLED` | `0.98` | **`0.98`** | 4 ➔ **7** (+3) | 🟢 PASS ➔ 🟢 **PASS** |
| 2 | **`K8S-EVAL-002`** | Severe CPU Throttling under Constrained CFS Quotas Causing P99 Latency Spikes | `UNKNOWN_ANOMALY` | `CPU_THROTTLING` | `0.40` | **`0.98`** | 0 ➔ **3** (+3) | 🔴 FAIL ➔ 🟢 **PASS** |
| 3 | **`K8S-EVAL-003`** | Application Runtime Crash / Panic (SIGSEGV Exit Code 139) | `APPLICATION_PANIC` | `APPLICATION_PANIC` | `0.98` | **`0.98`** | 4 ➔ **5** (+1) | 🟢 PASS ➔ 🟢 **PASS** |
| 4 | **`K8S-EVAL-004`** | Node Memory Pressure Leading to Eviction of Burstable Pods | `UNKNOWN_ANOMALY` | `NODE_MEMORY_PRESSURE` | `0.40` | **`0.98`** | 0 ➔ **5** (+5) | 🔴 FAIL ➔ 🟢 **PASS** |
| 5 | **`K8S-EVAL-005`** | CrashLoopBackOff Due to Missing Configuration Secret Dependency | `CRASH_LOOP_BACKOFF` | `CRASH_LOOP_BACKOFF` | `0.98` | **`0.98`** | 4 ➔ **5** (+1) | 🟢 PASS ➔ 🟢 **PASS** |
| 6 | **`K8S-EVAL-006`** | Node Transition to NotReady Due to PLEG (Pod Lifecycle Event Generator) Timeout | `UNKNOWN_ANOMALY` | `NODE_NOT_READY` | `0.40` | **`0.98`** | 0 ➔ **7** (+7) | 🔴 FAIL ➔ 🟢 **PASS** |
| 7 | **`K8S-EVAL-007`** | Readiness and Liveness Health Probe Failure Cascade Under Database Starvation | `PROBE_FAILURE` | `PROBE_FAILURE` | `0.89` | **`0.89`** | 3 ➔ **3** (+0) | 🟢 PASS ➔ 🟢 **PASS** |
| 8 | **`K8S-EVAL-008`** | Unschedulable Pod Due to Excessive and Impossible Resource Requests | `UNKNOWN_ANOMALY` | `INCORRECT_RESOURCE_SPEC` | `0.10` | **`0.98`** | 0 ➔ **3** (+3) | 🔴 FAIL ➔ 🟢 **PASS** |
| 9 | **`K8S-EVAL-009`** | Service Has No Endpoints Due to Label Selector Mismatch | `UNKNOWN_ANOMALY` | `SERVICE_NO_ENDPOINTS` | `0.10` | **`0.92`** | 0 ➔ **2** (+2) | 🔴 FAIL ➔ 🟢 **PASS** |
| 10 | **`K8S-EVAL-010`** | Service Routes Traffic to Unhealthy / Wrong Canary Pods via Overlapping Selector | `UNKNOWN_ANOMALY` | `SERVICE_ROUTES_TO_UNHEALTHY_PODS` | `0.40` | **`0.98`** | 2 ➔ **5** (+3) | 🔴 FAIL ➔ 🟢 **PASS** |

---

## 🔍 Key Architectural Leaps in Latest Release

1. **Host Node Infrastructure Telemetry (`get_node_info`)**:
   - *Baseline Failure:* Failed on `NODE_MEMORY_PRESSURE` (`K8S-EVAL-004`) and `NODE_NOT_READY` (`K8S-EVAL-006`) because baseline only parsed pod stdout/stderr and missed host-level kubelet evictions, PLEG heartbeat timeouts, and kernel D-state stalls.
   - *Latest Victory:* `get_node_info` extracts node conditions (`MemoryPressure`, `Ready: False`), taints (`node.kubernetes.io/not-ready`), and allocatables, elevating diagnostic accuracy on node incidents from 0% to 100%.

2. **Low-Confidence Automated Triage (`triage_low_confidence_incident`)**:
   - *Baseline Failure:* Terse logs without obvious error signatures fell back to `UNKNOWN_ANOMALY` with confidence scores as low as 0.10.
   - *Latest Victory:* When confidence is < 0.70 or evidence is scarce, the agent initiates multi-surface triage across previous termination logs (`--previous`), pod events, node health, and deployment rollout history, restoring evidence count and confidence to >= 0.85.

3. **Rollout Revision & Pod Version Diffing (`get_deployment_history`)**:
   - *Baseline Failure:* Incapable of associating sudden pod crashes with recent deployment revisions or faulty container image tags.
   - *Latest Victory:* Inspects revision history, container image tag transitions, and provides instant `kubectl rollout undo` commands.
