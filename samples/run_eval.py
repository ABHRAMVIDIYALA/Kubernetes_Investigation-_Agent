#!/usr/bin/env python3
import sys
import time
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from k8s_agent import K8sInvestigationAgent

def run_evaluation(dataset_path: str = "samples/evaluation_dataset.json", output_traces_path: str = "samples/evaluation_traces.json"):
    base_dir = Path(__file__).parent.parent
    data_file = base_dir / dataset_path
    out_file = base_dir / output_traces_path

    if not data_file.exists():
        print(f"❌ Error: Dataset file not found at {data_file}")
        sys.exit(1)

    with open(data_file, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    print("=" * 80)
    print("🛡️  KUBERNETES AGENT INCIDENT EVALUATION BENCHMARK")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Dataset  : {data_file.resolve()} ({len(test_cases)} test cases)")
    print("=" * 80)

    agent = K8sInvestigationAgent(enable_llm=False)
    traces = []
    category_matches = 0
    total_evidence = 0
    total_time_ms = 0.0

    for idx, tc in enumerate(test_cases, start=1):
        tc_id = tc["test_case_id"]
        title = tc["title"]
        expected_cat = tc["expected_agent_output"]["primary_category"]
        expected_sev = tc["expected_agent_output"].get("minimum_severity", "MEDIUM")

        # Prepare combined telemetry stream
        logs = tc["telemetry"].get("pod_logs", "")
        events = tc["telemetry"].get("k8s_events", "")
        status = tc["telemetry"].get("describe_status", "")
        combined_telemetry = f"{logs}\n\n--- KUBERNETES EVENTS ---\n{events}\n\n--- DESCRIBE STATUS ---\n{status}"

        # Execute agent with precise latency tracking
        start_t = time.perf_counter()
        result = agent.investigate(combined_telemetry)
        end_t = time.perf_counter()

        elapsed_ms = round((end_t - start_t) * 1000, 2)
        total_time_ms += elapsed_ms

        # Populate context if available in dataset
        res_ctx = tc.get("resource_context", {})
        if res_ctx.get("pod_name") and not result.resource_context.pod_name:
            result.resource_context.pod_name = res_ctx.get("pod_name")
        if res_ctx.get("namespace") and not result.resource_context.namespace:
            result.resource_context.namespace = res_ctx.get("namespace")
        if res_ctx.get("container_name") and not result.resource_context.container_name:
            result.resource_context.container_name = res_ctx.get("container_name")

        # Evaluate performance
        cat_match = (result.primary_category.value == expected_cat)
        if cat_match:
            category_matches += 1
        total_evidence += len(result.evidence_timeline)

        status_icon = "✅ PASS" if cat_match else "❌ FAIL"
        print(f"[{idx:02d}/10] {tc_id} | {status_icon} | Detected: {result.primary_category.value:25} | Expected: {expected_cat:25} | Conf: {result.confidence_score:.2f} | Evidence: {len(result.evidence_timeline)} | Latency: {elapsed_ms}ms")

        # Build detailed execution trace
        trace_entry = {
            "trace_id": str(uuid.uuid4())[:12],
            "test_case_id": tc_id,
            "title": title,
            "execution_timestamp": datetime.now(timezone.utc).isoformat(),
            "latency_ms": elapsed_ms,
            "evaluation_verdict": {
                "status": "PASS" if cat_match else "FAIL",
                "category_match": cat_match,
                "expected_category": expected_cat,
                "detected_category": result.primary_category.value,
                "detected_severity": result.severity.value,
                "confidence_score": result.confidence_score,
                "confidence_threshold_met": (result.confidence_score >= tc["expected_agent_output"].get("confidence_threshold", 0.8))
            },
            "step_1_input_ingestion": {
                "raw_telemetry_bytes": len(combined_telemetry.encode("utf-8")),
                "total_lines_parsed": len(combined_telemetry.splitlines()),
                "extracted_resource_context": result.resource_context.__dict__
            },
            "step_2_evidence_correlation": [
                {
                    "line_number": ev.line_number,
                    "matched_pattern": ev.matched_pattern,
                    "significance": ev.significance,
                    "timestamp": ev.timestamp,
                    "log_level": ev.log_level,
                    "raw_snippet": ev.raw_content
                }
                for ev in result.evidence_timeline
            ],
            "step_3_rca_and_remediation": {
                "summary": result.summary,
                "root_cause_analysis": result.root_cause_analysis,
                "remediation_steps": result.remediation_steps,
                "verification_commands": result.verification_commands
            }
        }
        traces.append(trace_entry)

    # Compute aggregate benchmark metrics
    accuracy = round((category_matches / len(test_cases)) * 100, 2)
    avg_latency = round(total_time_ms / len(test_cases), 2)
    avg_evidence = round(total_evidence / len(test_cases), 1)

    print("=" * 80)
    print(f"📈 EVALUATION BENCHMARK SUMMARY:")
    print(f"  • Total Incidents Evaluated: {len(test_cases)}")
    print(f"  • Category Accuracy Rate   : {accuracy}% ({category_matches}/{len(test_cases)})")
    print(f"  • Total Evidence Correlated: {total_evidence} items (avg {avg_evidence} per incident)")
    print(f"  • Total Execution Latency  : {round(total_time_ms, 2)}ms (avg {avg_latency}ms per incident)")
    print("=" * 80)

    # Export execution traces
    benchmark_payload = {
        "metadata": {
            "benchmark_name": "Kubernetes Diagnostic Agent Evaluation Benchmark",
            "execution_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_test_cases": len(test_cases),
            "accuracy_rate_pct": accuracy,
            "average_latency_ms": avg_latency,
            "total_evidence_extracted": total_evidence
        },
        "traces": traces
    }

    out_file.write_text(json.dumps(benchmark_payload, indent=2), encoding="utf-8")
    print(f"💾 Full execution traces saved to: {out_file.resolve()}\n")
    return benchmark_payload

if __name__ == "__main__":
    run_evaluation()
