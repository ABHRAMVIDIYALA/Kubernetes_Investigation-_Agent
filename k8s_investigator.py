#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path
from k8s_agent import (
    K8sInvestigationAgent,
    ReportFormatter,
    get_deployment_history,
    Get_deployment_history,
    get_pod_logs,
    Get_Pod_logs,
    get_pod_events,
    Get_Pod_events,
    get_node_info,
    Get_node_info,
    triage_low_confidence_incident,
    KubernetesLogFetchError,
    KubernetesEventFetchError,
    KubernetesDeploymentHistoryError,
    KubernetesNodeInfoError,
)

def main():
    parser = argparse.ArgumentParser(
        description="🛡️ Kubernetes Investigation Agent — Fetches pod logs via get_pod_logs tool, correlates events, node health via get_node_info, and deployment rollout history via get_deployment_history."
    )
    # Primary live cluster pod flags
    parser.add_argument(
        "-p", "--pod",
        type=str,
        help="Name of the Kubernetes pod to investigate (uses get_pod_logs to fetch directly from cluster)."
    )
    parser.add_argument(
        "-n", "--namespace",
        type=str,
        default="default",
        help="Kubernetes namespace of the pod (default: 'default')."
    )
    parser.add_argument(
        "-c", "--container",
        type=str,
        help="Specific container name within multi-container pod."
    )
    parser.add_argument(
        "--tail",
        type=int,
        help="Number of most recent log lines to retrieve via get_pod_logs (e.g. 500)."
    )
    parser.add_argument(
        "--previous",
        action="store_true",
        help="Fetch logs for previous terminated container instance (e.g. after OOM or CrashLoopBackOff)."
    )
    parser.add_argument(
        "--events-only",
        action="store_true",
        help="Fetch and print only the pod events using get_pod_events tool (without running full investigation)."
    )
    parser.add_argument(
        "-d", "--deployment",
        type=str,
        help="Name of the Kubernetes deployment to inspect revision/version changes for."
    )
    parser.add_argument(
        "--revision",
        type=int,
        help="Specific deployment rollout revision number to inspect."
    )
    parser.add_argument(
        "--history-only",
        action="store_true",
        help="Fetch and print only the deployment rollout history and version changes using get_deployment_history."
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw unformatted rollout history output instead of deep pod version analysis."
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Do not correlate deployment rollout history when investigating a pod."
    )
    parser.add_argument(
        "--no-events",
        action="store_true",
        help="Do not correlate pod events when investigating a pod."
    )
    parser.add_argument(
        "--node",
        type=str,
        help="Name of the Kubernetes host node to inspect or correlate via get_node_info tool."
    )
    parser.add_argument(
        "--node-info-only",
        action="store_true",
        help="Fetch and print only node infrastructure health and conditions using get_node_info."
    )
    parser.add_argument(
        "--no-node-info",
        action="store_true",
        help="Do not correlate node infrastructure health when investigating a pod."
    )
    parser.add_argument(
        "--triage",
        action="store_true",
        help="Trigger automated multi-surface triage if confidence or evidence items are low."
    )

    # Offline / secondary input flags
    parser.add_argument(
        "-f", "--file",
        type=str,
        help="Path to an offline Kubernetes log file to investigate (fallback mode)."
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Paste logs interactively in the terminal."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run a demonstration against bundled real-world Kubernetes failure scenarios."
    )

    # Output options
    parser.add_argument(
        "--format",
        choices=["console", "markdown", "json"],
        default="console",
        help="Output format for the report (default: console)."
    )
    parser.add_argument(
        "-o", "--out",
        type=str,
        help="Save the investigation report to an output file."
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM synthesis (force pure offline rule-based heuristic engine)."
    )

    args = parser.parse_args()
    agent = K8sInvestigationAgent(enable_llm=not args.no_llm)

    log_content = ""

    if args.demo:
        run_demo(agent, args.format)
        return

    # Handle --history-only flag
    if args.history_only:
        target = args.deployment or args.pod
        if not target:
            print("❌ Error: --history-only requires --deployment or --pod to be specified.", file=sys.stderr)
            sys.exit(1)
        print(f"📡 Fetching deployment history and analyzing pod version for '{target}' in namespace '{args.namespace}' using get_deployment_history tool...\n", file=sys.stderr)
        try:
            history_output = get_deployment_history(
                deployment_name=args.deployment,
                pod_name=args.pod,
                namespace=args.namespace,
                revision=args.revision,
                analyze_pod_version=not args.raw,
                raw=args.raw,
            )
            print(history_output)
            sys.exit(0)
        except KubernetesDeploymentHistoryError as e:
            print(f"❌ Error fetching deployment history:\n{e}", file=sys.stderr)
            sys.exit(1)

    # Handle --node-info-only flag
    if args.node_info_only:
        target = args.node or args.pod
        if not target:
            print("❌ Error: --node-info-only requires --node or --pod to be specified.", file=sys.stderr)
            sys.exit(1)
        print(f"📡 Fetching node info for '{target}' using get_node_info tool...\n", file=sys.stderr)
        try:
            node_output = get_node_info(
                node_name=args.node,
                pod_name=args.pod,
                namespace=args.namespace,
                analyze_node_health=not args.raw,
                raw=args.raw,
            )
            print(node_output)
            sys.exit(0)
        except KubernetesNodeInfoError as e:
            print(f"❌ Error fetching node info:\n{e}", file=sys.stderr)
            sys.exit(1)

    # 1. Primary path: Fetch logs, events, node info, and deployment history directly from cluster using tools
    if args.pod:
        # Handle --events-only flag
        if args.events_only:
            print(f"📡 Fetching events for pod '{args.pod}' in namespace '{args.namespace}' using Get_Pod_events tool...\n", file=sys.stderr)
            try:
                events_output = Get_Pod_events(pod_name=args.pod, namespace=args.namespace)
                print(events_output)
                sys.exit(0)
            except KubernetesEventFetchError as e:
                print(f"❌ Error fetching pod events:\n{e}", file=sys.stderr)
                sys.exit(1)

        print(f"📡 Fetching logs for pod '{args.pod}' in namespace '{args.namespace}' using Get_Pod_logs tool...", file=sys.stderr)
        try:
            log_content = Get_Pod_logs(
                pod_name=args.pod,
                namespace=args.namespace,
                container=args.container,
                tail_lines=args.tail,
                previous=args.previous,
            )
            print(f"✅ Successfully retrieved logs for pod '{args.pod}'.", file=sys.stderr)
        except KubernetesLogFetchError as e:
            print(f"❌ Error fetching logs via Get_Pod_logs:\n{e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected error fetching logs: {e}", file=sys.stderr)
            sys.exit(1)

        # Correlate pod events if enabled
        if not args.no_events:
            try:
                events = get_pod_events(pod_name=args.pod, namespace=args.namespace)
                if events and "No events recorded" not in events:
                    log_content += f"\n\n--- KUBERNETES POD EVENTS ({args.pod}) ---\n" + events
                    print(f"✅ Correlated cluster events for pod '{args.pod}'.", file=sys.stderr)
            except Exception:
                # Non-blocking if events cannot be reached
                pass

        # Correlate deployment rollout history if enabled
        if not args.no_history:
            try:
                history = get_deployment_history(
                    deployment_name=args.deployment,
                    pod_name=args.pod,
                    namespace=args.namespace,
                    analyze_pod_version=True,
                )
                if history:
                    log_content += f"\n\n--- DEPLOYMENT ROLLOUT HISTORY & POD VERSION ANALYSIS ---\n" + history
                    print(f"✅ Correlated deployment rollout history & pod version analysis for pod '{args.pod}'.", file=sys.stderr)
            except Exception:
                # Non-blocking if deployment history cannot be reached
                pass

        # Correlate host node infrastructure health if enabled
        if not args.no_node_info:
            try:
                node_info = get_node_info(
                    node_name=args.node,
                    pod_name=args.pod,
                    namespace=args.namespace,
                    analyze_node_health=True,
                )
                if node_info:
                    log_content += f"\n\n--- KUBERNETES NODE INFRASTRUCTURE & HEALTH ---\n" + node_info
                    print(f"✅ Correlated node infrastructure health for pod '{args.pod}'.", file=sys.stderr)
            except Exception:
                # Non-blocking if node info cannot be reached
                pass

        print("Starting investigation...\n", file=sys.stderr)

    # 2. File fallback
    elif args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"❌ Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        log_content = file_path.read_text(encoding="utf-8", errors="replace")

    # 3. Interactive paste
    elif args.interactive:
        print("📋 Paste your Kubernetes logs below. Press Ctrl+Z (Windows) or Ctrl+D (Unix) then Enter to finish:")
        print("------------------------------------------------------------------------------------------------")
        try:
            log_content = sys.stdin.read()
        except KeyboardInterrupt:
            print("\nInvestigation aborted.", file=sys.stderr)
            sys.exit(0)

    # 4. Piped stdin
    elif not sys.stdin.isatty():
        log_content = sys.stdin.read()

    else:
        parser.print_help()
        print("\n💡 Primary Usage: Investigate a live pod using Get_Pod_logs:")
        print("   python k8s_investigator.py --pod payment-service-589f8dc94-p9w7c -n production")
        print("   python k8s_investigator.py --pod crashed-worker-abc --previous")
        print("   python k8s_investigator.py --node k8s-worker-node-14 --node-info-only")
        print("\n💡 Offline Demo:")
        print("   python k8s_investigator.py --demo")
        sys.exit(0)

    if not log_content.strip():
        print("❌ Error: No log content retrieved for investigation.", file=sys.stderr)
        sys.exit(1)

    # Perform investigation
    result = agent.investigate(log_content)

    # Ensure targeted pod and namespace are tracked in resource context if fetched via CLI
    if args.pod and not result.resource_context.pod_name:
        result.resource_context.pod_name = args.pod
    if args.namespace and not result.resource_context.namespace:
        result.resource_context.namespace = args.namespace
    if args.container and not result.resource_context.container_name:
        result.resource_context.container_name = args.container
    if args.node and not result.resource_context.node_name:
        result.resource_context.node_name = args.node

    # If --triage is requested or confidence/evidence is low, run automated triage
    if args.triage:
        triage_data = triage_low_confidence_incident(
            target=result,
            pod_name=args.pod,
            namespace=args.namespace,
            node_name=args.node,
        )
        if triage_data.get("is_low_confidence"):
            print("\n" + triage_data.get("report", "") + "\n", file=sys.stderr)
            if triage_data.get("enriched_result"):
                result = triage_data["enriched_result"]

    # Format output
    if args.format == "json":
        output = result.to_json()
    elif args.format == "markdown":
        output = ReportFormatter.to_markdown(result)
    else:
        output = ReportFormatter.to_console(result)

    print(output)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(output, encoding="utf-8")
        print(f"💾 Report saved to: {out_path.resolve()}", file=sys.stderr)


def run_demo(agent: K8sInvestigationAgent, fmt: str):
    sample_dir = Path(__file__).parent / "samples"
    scenarios = [
        ("1. Out-Of-Memory Termination (OOMKilled / Exit Code 137)", sample_dir / "sample_oom_kill.log"),
        ("2. CoreDNS Resolution Failure & CrashLoopBackOff", sample_dir / "sample_crashloop_dns.log"),
        ("3. Readiness & Liveness Probe Timeout Cascade", sample_dir / "sample_probe_timeout.log"),
    ]

    print("\n" + "=" * 76)
    print(" 🚀 RUNNING KUBERNETES INVESTIGATION AGENT DEMONSTRATION")
    print("=" * 76 + "\n")

    for title, log_file in scenarios:
        print(f"\n▶ Analyzing Scenario: {title}")
        print("-" * 76)
        if not log_file.exists():
            print(f"Warning: Sample file {log_file} missing, skipping.")
            continue
        content = log_file.read_text(encoding="utf-8")
        res = agent.investigate(content)
        if fmt == "markdown":
            print(ReportFormatter.to_markdown(res))
        elif fmt == "json":
            print(res.to_json())
        else:
            print(ReportFormatter.to_console(res))
        print("\n")


if __name__ == "__main__":
    main()
