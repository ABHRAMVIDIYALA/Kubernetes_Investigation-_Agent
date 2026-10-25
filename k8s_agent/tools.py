import os
import re
import shutil
import subprocess
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

class KubernetesToolError(RuntimeError):
    """Base error for Kubernetes tool failures."""
    def __init__(self, message: str, command: Optional[str] = None, stderr: Optional[str] = None):
        super().__init__(message)
        self.command = command
        self.stderr = stderr

class KubernetesLogFetchError(KubernetesToolError):
    """Raised when fetching Kubernetes pod logs fails."""
    pass

class KubernetesEventFetchError(KubernetesToolError):
    """Raised when fetching Kubernetes pod events fails."""
    pass

class KubernetesDeploymentHistoryError(KubernetesToolError):
    """Raised when fetching Kubernetes deployment rollout history fails."""
    pass

class KubernetesNodeInfoError(KubernetesToolError):
    """Raised when fetching Kubernetes node information fails."""
    pass

# In-memory mock registries for testing and offline development
_MOCK_POD_LOGS: Dict[str, str] = {}
_MOCK_POD_EVENTS: Dict[str, str] = {}
_MOCK_DEPLOYMENT_HISTORY: Dict[str, str] = {}
_MOCK_DEPLOYMENT_REVISIONS: Dict[str, Dict[int, str]] = {}
_MOCK_NODE_INFO: Dict[str, str] = {}
_MOCK_POD_TO_NODE: Dict[str, str] = {}

def register_mock_pod_logs(pod_name: str, log_content: str, namespace: str = "default") -> None:
    """Registers simulated pod logs in memory for testing without a live cluster."""
    key = f"{namespace}/{pod_name}"
    _MOCK_POD_LOGS[key] = log_content

def register_mock_pod_events(pod_name: str, events_content: str, namespace: str = "default") -> None:
    """Registers simulated pod events in memory for testing without a live cluster."""
    key = f"{namespace}/{pod_name}"
    _MOCK_POD_EVENTS[key] = events_content

def register_mock_deployment_history(deployment_name: str, history_content: str, namespace: str = "default") -> None:
    """Registers simulated deployment history in memory for testing without a live cluster."""
    key = f"{namespace}/{deployment_name}"
    _MOCK_DEPLOYMENT_HISTORY[key] = history_content

def register_mock_deployment_revision(deployment_name: str, revision: int, revision_detail: str, namespace: str = "default") -> None:
    """Registers simulated revision pod template in memory for testing without a live cluster."""
    key = f"{namespace}/{deployment_name}"
    if key not in _MOCK_DEPLOYMENT_REVISIONS:
        _MOCK_DEPLOYMENT_REVISIONS[key] = {}
    _MOCK_DEPLOYMENT_REVISIONS[key][int(revision)] = revision_detail

def register_mock_node_info(node_name: str, node_content: str) -> None:
    """Registers simulated node describe/status in memory for testing without a live cluster."""
    _MOCK_NODE_INFO[node_name.strip()] = node_content

def register_mock_pod_node(pod_name: str, node_name: str, namespace: str = "default") -> None:
    """Maps a pod to a node in mock memory for resolving node info via pod_name."""
    key = f"{namespace}/{pod_name}"
    _MOCK_POD_TO_NODE[key] = node_name.strip()

def clear_mock_pod_logs() -> None:
    """Clears all registered mock pod logs, events, deployment history, and node info."""
    _MOCK_POD_LOGS.clear()
    _MOCK_POD_EVENTS.clear()
    _MOCK_DEPLOYMENT_HISTORY.clear()
    _MOCK_DEPLOYMENT_REVISIONS.clear()
    _MOCK_NODE_INFO.clear()
    _MOCK_POD_TO_NODE.clear()

def clear_mock_pod_events() -> None:
    """Clears all registered mock pod events."""
    _MOCK_POD_EVENTS.clear()

def clear_mock_deployment_history() -> None:
    """Clears all registered mock deployment history and revision details."""
    _MOCK_DEPLOYMENT_HISTORY.clear()
    _MOCK_DEPLOYMENT_REVISIONS.clear()

def clear_mock_deployment_revisions() -> None:
    """Clears all registered mock deployment revisions."""
    _MOCK_DEPLOYMENT_REVISIONS.clear()

def clear_mock_node_info() -> None:
    """Clears all registered mock node info and pod-to-node mappings."""
    _MOCK_NODE_INFO.clear()
    _MOCK_POD_TO_NODE.clear()

def infer_deployment_name(pod_name: str) -> Optional[str]:
    """
    Infers the parent deployment name from standard Kubernetes pod naming patterns
    (e.g., 'payment-service-589f8dc94-p9w7c' -> 'payment-service').
    """
    if not pod_name:
        return None
    import re
    # Deployment pod pattern: <deployment-name>-<rs-hash>-<pod-hash>
    match = re.match(r"^([a-z0-9][a-z0-9\-]*?)-[a-z0-9]{8,10}-[a-z0-9]{5}$", pod_name, re.IGNORECASE)
    if match:
        return match.group(1)
    # Generalized pattern: <name>-<hash>
    match_general = re.match(r"^([a-z0-9][a-z0-9\-]*?)-[a-z0-9]{5}$", pod_name, re.IGNORECASE)
    if match_general:
        return match_general.group(1)
    return pod_name

def Get_Pod_logs(
    pod_name: str,
    namespace: str = "default",
    container: Optional[str] = None,
    tail_lines: Optional[int] = None,
    previous: bool = False,
    timestamps: bool = True,
    kubeconfig: Optional[str] = None,
    context: Optional[str] = None,
) -> str:
    """
    Fetches the logs of a specific Kubernetes pod using kubectl.

    Args:
        pod_name: Name of the target Kubernetes pod (e.g., 'payment-service-589f8dc94-p9w7c').
        namespace: Kubernetes namespace where the pod resides (default: 'default').
        container: Specific container name if the pod has multiple containers.
        tail_lines: Number of most recent lines to retrieve (e.g., 500). If None, fetches all.
        previous: If True, fetches logs for previous terminated container instance (e.g. after crash).
        timestamps: If True, prefixes each log line with an RFC3339 timestamp.
        kubeconfig: Optional explicit path to kubeconfig file.
        context: Optional kubeconfig context to use.

    Returns:
        The raw log content as a string.

    Raises:
        KubernetesLogFetchError: If kubectl fails, the pod does not exist, or the cluster is unreachable.
    """
    if not pod_name or not pod_name.strip():
        raise ValueError("pod_name must be a non-empty string.")

    pod_name = pod_name.strip()
    namespace = namespace.strip() if namespace else "default"

    # Check mock registry first (useful for testing or local simulation)
    mock_key = f"{namespace}/{pod_name}"
    if mock_key in _MOCK_POD_LOGS:
        return _MOCK_POD_LOGS[mock_key]

    # Check if a mock directory is specified via environment variable
    mock_dir = os.environ.get("K8S_MOCK_LOGS_DIR")
    if mock_dir:
        mock_path = Path(mock_dir) / f"{pod_name}.log"
        if mock_path.exists():
            return mock_path.read_text(encoding="utf-8", errors="replace")

    # Verify kubectl is installed
    kubectl_bin = shutil.which("kubectl") or "kubectl"

    # Construct kubectl logs command
    cmd = [kubectl_bin, "logs", pod_name, "-n", namespace]

    if container:
        cmd.extend(["-c", container.strip()])

    if tail_lines is not None and int(tail_lines) > 0:
        cmd.extend([f"--tail={int(tail_lines)}"])

    if previous:
        cmd.append("--previous")

    if timestamps:
        cmd.append("--timestamps=true")

    if kubeconfig:
        cmd.extend(["--kubeconfig", str(kubeconfig)])

    if context:
        cmd.extend(["--context", str(context)])

    cmd_str = " ".join(cmd)

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60
        )
    except FileNotFoundError:
        raise KubernetesLogFetchError(
            f"kubectl executable not found. Ensure kubectl is installed and present in PATH.",
            command=cmd_str
        )
    except subprocess.TimeoutExpired:
        raise KubernetesLogFetchError(
            f"Timed out after 60 seconds while fetching logs for pod '{pod_name}' in namespace '{namespace}'.",
            command=cmd_str
        )
    except Exception as e:
        raise KubernetesLogFetchError(
            f"Unexpected error running kubectl: {str(e)}",
            command=cmd_str
        )

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        # Provide actionable context based on common kubectl errors
        if "not found" in err_msg.lower():
            hint = f"Verify pod name and namespace with: kubectl get pods -n {namespace}"
        elif "actively refused" in err_msg.lower() or "connection refused" in err_msg.lower():
            hint = "Cannot connect to Kubernetes API server. Check your cluster connection or KUBECONFIG setting."
        elif "previous terminated container" in err_msg.lower():
            hint = "No previous terminated container instance found for this pod. Try running without --previous."
        else:
            hint = f"Run manually to inspect: {cmd_str}"

        raise KubernetesLogFetchError(
            f"Failed to fetch logs for pod '{pod_name}' in namespace '{namespace}'.\nError: {err_msg}\nHint: {hint}",
            command=cmd_str,
            stderr=err_msg
        )

    return proc.stdout

def Get_Pod_events(
    pod_name: str,
    namespace: str = "default",
    sort_by_timestamp: bool = True,
    kubeconfig: Optional[str] = None,
    context: Optional[str] = None,
) -> str:
    """
    Fetches the Kubernetes events for a specific pod using kubectl.

    Args:
        pod_name: Name of the target Kubernetes pod (e.g., 'payment-service-589f8dc94-p9w7c').
        namespace: Kubernetes namespace where the pod resides (default: 'default').
        sort_by_timestamp: If True, orders events chronologically by '.lastTimestamp'.
        kubeconfig: Optional explicit path to kubeconfig file.
        context: Optional kubeconfig context to use.

    Returns:
        The formatted events table or raw event output as a string.

    Raises:
        KubernetesEventFetchError: If kubectl fails, the namespace/pod is invalid, or the cluster is unreachable.
    """
    if not pod_name or not pod_name.strip():
        raise ValueError("pod_name must be a non-empty string.")

    pod_name = pod_name.strip()
    namespace = namespace.strip() if namespace else "default"

    # Check mock registry first (useful for testing or local simulation)
    mock_key = f"{namespace}/{pod_name}"
    if mock_key in _MOCK_POD_EVENTS:
        return _MOCK_POD_EVENTS[mock_key]

    # Check if a mock directory is specified via environment variable
    mock_dir = os.environ.get("K8S_MOCK_EVENTS_DIR")
    if mock_dir:
        mock_path = Path(mock_dir) / f"{pod_name}_events.log"
        if mock_path.exists():
            return mock_path.read_text(encoding="utf-8", errors="replace")

    # Verify kubectl is installed
    kubectl_bin = shutil.which("kubectl") or "kubectl"

    # Construct kubectl get events command targeting the specific pod
    cmd = [
        kubectl_bin,
        "get",
        "events",
        "-n",
        namespace,
        f"--field-selector=involvedObject.name={pod_name}"
    ]

    if sort_by_timestamp:
        cmd.append("--sort-by=.lastTimestamp")

    if kubeconfig:
        cmd.extend(["--kubeconfig", str(kubeconfig)])

    if context:
        cmd.extend(["--context", str(context)])

    cmd_str = " ".join(cmd)

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60
        )
    except FileNotFoundError:
        raise KubernetesEventFetchError(
            f"kubectl executable not found. Ensure kubectl is installed and present in PATH.",
            command=cmd_str
        )
    except subprocess.TimeoutExpired:
        raise KubernetesEventFetchError(
            f"Timed out after 60 seconds while fetching events for pod '{pod_name}' in namespace '{namespace}'.",
            command=cmd_str
        )
    except Exception as e:
        raise KubernetesEventFetchError(
            f"Unexpected error running kubectl: {str(e)}",
            command=cmd_str
        )

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        if "actively refused" in err_msg.lower() or "connection refused" in err_msg.lower():
            hint = "Cannot connect to Kubernetes API server. Check your cluster connection or KUBECONFIG setting."
        elif "not found" in err_msg.lower():
            hint = f"Verify namespace '{namespace}' exists with: kubectl get namespaces"
        else:
            hint = f"Run manually to inspect: {cmd_str}"

        raise KubernetesEventFetchError(
            f"Failed to fetch events for pod '{pod_name}' in namespace '{namespace}'.\nError: {err_msg}\nHint: {hint}",
            command=cmd_str,
            stderr=err_msg
        )

    output = proc.stdout.strip()
    if not output or "No resources found" in output:
        return f"No events recorded for pod '{pod_name}' in namespace '{namespace}'."

    return proc.stdout

def parse_rollout_revisions(history_text: str) -> List[Tuple[int, str]]:
    """
    Parses kubectl rollout history table into a list of (revision_number, change_cause).
    """
    revisions = []
    lines = history_text.strip().splitlines()
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        if re.match(r'^(?:deployment|revision|REVISION)', line_clean, re.IGNORECASE):
            continue
        m = re.match(r'^(\d+)\s+(.*?)$', line_clean)
        if m:
            rev_num = int(m.group(1))
            cause = m.group(2).strip()
            revisions.append((rev_num, cause))
    return sorted(revisions, key=lambda x: x[0])


def parse_pod_template(template_text: str) -> Dict[str, Any]:
    """
    Parses kubectl rollout history --revision=N output to extract container images,
    tags, and resource configurations.
    """
    containers: Dict[str, Dict[str, Any]] = {}
    lines = template_text.splitlines()
    in_containers = False
    current_container = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if re.match(r'^Containers:\s*$', stripped, re.IGNORECASE):
            in_containers = True
            continue

        if in_containers:
            # Check for section ends
            if re.match(r'^(?:Volumes|Annotations|Conditions|Labels|Node-Selectors|Tolerations):\s*', stripped, re.IGNORECASE):
                in_containers = False
                current_container = None
                continue

            c_header = re.match(r'^([a-zA-Z0-9_\-]+):\s*$', stripped)
            is_prop = any(stripped.startswith(k) for k in [
                "Image:", "Port:", "Ports:", "Host Port:", "Limits:", "Requests:",
                "Environment:", "Mounts:", "Args:", "Command:"
            ])

            if c_header and not is_prop:
                current_container = c_header.group(1)
                containers[current_container] = {"image": None, "tag": None, "repo": None}
                continue

            img_match = re.search(r'Image:\s*(\S+)', stripped, re.IGNORECASE)
            if img_match:
                img_val = img_match.group(1).strip()
                if not current_container:
                    current_container = "main"
                    containers[current_container] = {}
                containers[current_container]["image"] = img_val
                if "@sha256:" in img_val:
                    repo, tag = img_val.split("@sha256:", 1)
                    containers[current_container]["repo"] = repo
                    containers[current_container]["tag"] = f"sha256:{tag[:12]}"
                elif ":" in img_val:
                    repo, tag = img_val.rsplit(":", 1)
                    containers[current_container]["repo"] = repo
                    containers[current_container]["tag"] = tag
                else:
                    containers[current_container]["repo"] = img_val
                    containers[current_container]["tag"] = "latest"

    # Fallback search if no structured Containers: block was found
    if not containers:
        for m in re.finditer(r'Image:\s*(\S+)', template_text, re.IGNORECASE):
            img_val = m.group(1).strip()
            containers["app"] = {"image": img_val}
            if ":" in img_val:
                repo, tag = img_val.rsplit(":", 1)
                containers["app"]["repo"] = repo
                containers["app"]["tag"] = tag
            else:
                containers["app"]["repo"] = img_val
                containers["app"]["tag"] = "latest"
            break

    return {"containers": containers}


def extract_version_or_image_from_text(text: str) -> Optional[str]:
    """
    Extracts container image or version string from change-cause or arbitrary text.
    """
    if not text:
        return None
    img_match = re.search(r'\b([a-zA-Z0-9_\-\./]+(?::[a-zA-Z0-9_\-\.]+|@sha256:[a-fA-F0-9]{64}))\b', text)
    if img_match:
        val = img_match.group(1)
        if ":" in val or "@" in val:
            return val
    ver_match = re.search(r'\b(v?\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9_\-\.]+)?)\b', text, re.IGNORECASE)
    if ver_match:
        return ver_match.group(1)
    return None


def format_pod_version_analysis_report(
    deployment_name: str,
    namespace: str,
    history_table: str,
    revisions: List[Tuple[int, str]],
    revisions_data: Dict[int, Dict[str, Any]],
    inspected_revision: Optional[int] = None
) -> str:
    """
    Builds a structured report comparing pod versions and container images across revisions.
    """
    lines = []
    lines.append("=" * 80)
    lines.append("🛡️  KUBERNETES POD VERSION & DEPLOYMENT ROLLOUT ANALYSIS")
    lines.append("=" * 80)
    lines.append(f"Deployment : {deployment_name}")
    lines.append(f"Namespace  : {namespace}")
    lines.append(f"Revisions  : {len(revisions)} recorded in rollout history")

    if not revisions:
        lines.append("\n⚠️  No rollout revisions detected for this deployment.")
        lines.append("=" * 80)
        return "\n".join(lines)

    rev_nums = [r[0] for r in revisions]
    causes = {r[0]: r[1] for r in revisions}

    if inspected_revision is not None:
        lines.append(f"Target     : Inspecting Revision #{inspected_revision}")
        rev_info = revisions_data.get(inspected_revision, {})
        containers = rev_info.get("containers", {})
        cause = causes.get(inspected_revision, "<none>")
        lines.append(f"Change Cause: {cause}\n")
        lines.append(f"📦 POD TEMPLATE & CONTAINER IMAGES (Revision #{inspected_revision}):")
        if containers:
            for c_name, c_data in containers.items():
                img = c_data.get("image") or "<unknown>"
                tag = c_data.get("tag") or "latest"
                lines.append(f"  • Container '{c_name}': Image = {img} (Tag: {tag})")
        else:
            lines.append("  (No specific container details found)")

        prev_rev = inspected_revision - 1
        if prev_rev in rev_nums:
            prev_info = revisions_data.get(prev_rev, {})
            prev_containers = prev_info.get("containers", {})
            lines.append(f"\n🔄 COMPARISON WITH PRECEDING REVISION #{prev_rev}:")
            for c_name, c_data in containers.items():
                curr_img = c_data.get("image")
                prev_img = prev_containers.get(c_name, {}).get("image")
                if prev_img and curr_img and prev_img != curr_img:
                    lines.append(f"  • Container '{c_name}': ⚠️ UPDATED")
                    lines.append(f"      - Previous: {prev_img} (Revision #{prev_rev})")
                    lines.append(f"      - Current : {curr_img} (Revision #{inspected_revision})")
                elif prev_img and curr_img:
                    lines.append(f"  • Container '{c_name}': UNCHANGED ({curr_img})")
    elif len(revisions) == 1:
        rev_single = revisions[0][0]
        cause_single = revisions[0][1]
        lines.append(f"Status     : Initial deployment (Revision #{rev_single}). No previous pod versions to compare.")
        lines.append(f"Change Cause: {cause_single}\n")
        containers = revisions_data.get(rev_single, {}).get("containers", {})
        if containers:
            lines.append(f"📦 CURRENT CONTAINER IMAGES (Revision #{rev_single}):")
            for c_name, c_data in containers.items():
                lines.append(f"  • Container '{c_name}': {c_data.get('image')} (Tag: {c_data.get('tag')})")
    else:
        latest_rev = revisions[-1][0]
        prev_rev = revisions[-2][0]
        latest_cause = causes.get(latest_rev, "<none>")
        prev_cause = causes.get(prev_rev, "<none>")

        lines.append(f"Active Pod : Revision #{latest_rev} (Latest)")
        lines.append(f"Prior Pod  : Revision #{prev_rev} (Previous)")
        lines.append("")
        lines.append("📦 RECENT POD VERSION & CONTAINER IMAGE CHANGES:")

        latest_containers = revisions_data.get(latest_rev, {}).get("containers", {})
        prev_containers = revisions_data.get(prev_rev, {}).get("containers", {})

        version_changes = []
        all_containers = set(latest_containers.keys()).union(set(prev_containers.keys()))

        if all_containers:
            for c_name in sorted(all_containers):
                curr_img = latest_containers.get(c_name, {}).get("image")
                prev_img = prev_containers.get(c_name, {}).get("image")
                curr_tag = latest_containers.get(c_name, {}).get("tag")
                prev_tag = prev_containers.get(c_name, {}).get("tag")

                if prev_img and curr_img and prev_img != curr_img:
                    version_changes.append(c_name)
                    lines.append(f"  • Container '{c_name}': ⚠️ POD VERSION CHANGED")
                    lines.append(f"      - Previous Image : {prev_img} (Revision #{prev_rev})")
                    lines.append(f"      - Current Image  : {curr_img} (Revision #{latest_rev})")
                    if prev_tag and curr_tag and prev_tag != curr_tag:
                        lines.append(f"      - Tag Transition : {prev_tag} ➔ {curr_tag}")
                elif not prev_img and curr_img:
                    version_changes.append(c_name)
                    lines.append(f"  • Container '{c_name}': ➕ NEW CONTAINER INTRODUCED in Revision #{latest_rev}")
                    lines.append(f"      - Image: {curr_img}")
                elif prev_img and not curr_img:
                    version_changes.append(c_name)
                    lines.append(f"  • Container '{c_name}': ➖ CONTAINER REMOVED in Revision #{latest_rev}")
                else:
                    lines.append(f"  • Container '{c_name}': UNCHANGED ({curr_img})")
        else:
            latest_ver = extract_version_or_image_from_text(latest_cause)
            prev_ver = extract_version_or_image_from_text(prev_cause)
            if latest_ver and prev_ver and latest_ver != prev_ver:
                version_changes.append("app")
                lines.append(f"  • Pod Version / Image: ⚠️ POD VERSION CHANGED")
                lines.append(f"      - Previous Version : {prev_ver} (Revision #{prev_rev})")
                lines.append(f"      - Current Version  : {latest_ver} (Revision #{latest_rev})")
            elif latest_ver:
                version_changes.append("app")
                lines.append(f"  • Pod Version / Image: ⚠️ RECENT VERSION DETECTED")
                lines.append(f"      - Current Version  : {latest_ver} (Revision #{latest_rev})")
                if prev_cause and prev_cause != "<none>":
                    lines.append(f"      - Previous Revision: {prev_cause} (Revision #{prev_rev})")
            else:
                lines.append("  • No container image differences recorded in revision change causes.")

        lines.append("")
        lines.append("📝 ROLLOUT CHANGE CAUSES:")
        lines.append(f"  • Active Revision #{latest_rev}: {latest_cause}")
        lines.append(f"  • Prior Revision #{prev_rev} : {prev_cause}")

        lines.append("")
        lines.append("💡 SRE INVESTIGATION & ROLLBACK RECOMMENDATION:")
        if version_changes:
            lines.append(f"  • ⚠️ Recent container version change detected in Revision #{latest_rev} ({', '.join(version_changes)}).")
            lines.append("    If the pod failure, crash loop, or OOM coincides with this rollout, revert to the prior stable pod version:")
            lines.append(f"      kubectl rollout undo deployment/{deployment_name} -n {namespace} --to-revision={prev_rev}")
        else:
            lines.append("  • Container images did not change between recent revisions. Investigate configuration, environment, or secret changes.")
            lines.append(f"    To roll back to the previous deployment revision:")
            lines.append(f"      kubectl rollout undo deployment/{deployment_name} -n {namespace} --to-revision={prev_rev}")

    lines.append("")
    lines.append("📋 RAW ROLLOUT REVISION HISTORY:")
    lines.append(history_table.strip())
    lines.append("=" * 80)
    return "\n".join(lines)


def get_deployment_history(
    deployment_name: Optional[str] = None,
    pod_name: Optional[str] = None,
    namespace: str = "default",
    revision: Optional[int] = None,
    analyze_pod_version: bool = True,
    raw: bool = False,
    kubeconfig: Optional[str] = None,
    context: Optional[str] = None,
) -> str:
    """
    Fetches and analyzes the rollout/deployment revision history of a Kubernetes deployment
    to detect any recent changes in pod version, container images, or configuration.

    Args:
        deployment_name: Name of the target Kubernetes deployment (e.g. 'payment-service').
                         If omitted, inferred from pod_name.
        pod_name: Name of a pod belonging to the deployment, used to infer deployment_name.
        namespace: Kubernetes namespace (default: 'default').
        revision: Optional specific rollout revision number to inspect detailed changes for.
        analyze_pod_version: If True, performs deep comparison of container images and pod
                             versions between revisions with rollback advice (default: True).
        raw: If True, returns only the raw kubectl rollout history output without formatting.
        kubeconfig: Optional explicit path to kubeconfig file.
        context: Optional kubeconfig context to use.

    Returns:
        A formatted string detailing deployment revisions, change causes, and recent pod version changes.

    Raises:
        ValueError: If neither deployment_name nor pod_name is provided.
        KubernetesDeploymentHistoryError: If kubectl fails to retrieve deployment history.
    """
    target_deploy = deployment_name.strip() if deployment_name and deployment_name.strip() else None
    if not target_deploy:
        if pod_name and pod_name.strip():
            target_deploy = infer_deployment_name(pod_name.strip())
        else:
            raise ValueError("Either deployment_name or pod_name must be provided to inspect deployment history.")

    namespace = namespace.strip() if namespace else "default"

    # Check mock registry first (useful for testing or local simulation)
    mock_key = f"{namespace}/{target_deploy}"
    if mock_key in _MOCK_DEPLOYMENT_HISTORY:
        raw_history = _MOCK_DEPLOYMENT_HISTORY[mock_key]
        if raw or not analyze_pod_version:
            return raw_history

        revisions = parse_rollout_revisions(raw_history)
        rev_templates = _MOCK_DEPLOYMENT_REVISIONS.get(mock_key, {})
        revisions_data = {}
        for r_num, _ in revisions:
            if r_num in rev_templates:
                revisions_data[r_num] = parse_pod_template(rev_templates[r_num])

        return format_pod_version_analysis_report(
            deployment_name=target_deploy,
            namespace=namespace,
            history_table=raw_history,
            revisions=revisions,
            revisions_data=revisions_data,
            inspected_revision=revision
        )

    # Check if a mock directory is specified via environment variable
    mock_dir = os.environ.get("K8S_MOCK_DEPLOYMENTS_DIR")
    if mock_dir:
        mock_path = Path(mock_dir) / f"{target_deploy}_history.log"
        if mock_path.exists():
            file_content = mock_path.read_text(encoding="utf-8", errors="replace")
            if raw or not analyze_pod_version:
                return file_content
            revisions = parse_rollout_revisions(file_content)
            return format_pod_version_analysis_report(
                deployment_name=target_deploy,
                namespace=namespace,
                history_table=file_content,
                revisions=revisions,
                revisions_data={},
                inspected_revision=revision
            )

    # Verify kubectl is installed
    kubectl_bin = shutil.which("kubectl") or "kubectl"

    # Base rollout history command
    base_cmd = [kubectl_bin, "rollout", "history", f"deployment/{target_deploy}", "-n", namespace]

    if kubeconfig:
        base_cmd.extend(["--kubeconfig", str(kubeconfig)])
    if context:
        base_cmd.extend(["--context", str(context)])

    if revision is not None and (raw or not analyze_pod_version):
        cmd = list(base_cmd) + [f"--revision={int(revision)}"]
    else:
        cmd = list(base_cmd)

    cmd_str = " ".join(cmd)

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60
        )
    except FileNotFoundError:
        raise KubernetesDeploymentHistoryError(
            f"kubectl executable not found. Ensure kubectl is installed and present in PATH.",
            command=cmd_str
        )
    except subprocess.TimeoutExpired:
        raise KubernetesDeploymentHistoryError(
            f"Timed out after 60 seconds while fetching deployment history for '{target_deploy}' in namespace '{namespace}'.",
            command=cmd_str
        )
    except Exception as e:
        raise KubernetesDeploymentHistoryError(
            f"Unexpected error running kubectl: {str(e)}",
            command=cmd_str
        )

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        if "actively refused" in err_msg.lower() or "connection refused" in err_msg.lower():
            hint = "Cannot connect to Kubernetes API server. Check your cluster connection or KUBECONFIG setting."
        elif "not found" in err_msg.lower():
            hint = f"Verify deployment '{target_deploy}' exists in namespace '{namespace}' with: kubectl get deployments -n {namespace}"
        else:
            hint = f"Run manually to inspect: {cmd_str}"

        raise KubernetesDeploymentHistoryError(
            f"Failed to fetch deployment rollout history for '{target_deploy}' in namespace '{namespace}'.\nError: {err_msg}\nHint: {hint}",
            command=cmd_str,
            stderr=err_msg
        )

    history_output = proc.stdout.strip()

    if raw or not analyze_pod_version:
        return history_output

    revisions = parse_rollout_revisions(history_output)
    revisions_data = {}

    target_revisions_to_query = []
    if revision is not None:
        target_revisions_to_query.append(int(revision))
        if int(revision) > 1:
            target_revisions_to_query.append(int(revision) - 1)
    elif len(revisions) >= 2:
        target_revisions_to_query.extend([revisions[-2][0], revisions[-1][0]])
    elif len(revisions) == 1:
        target_revisions_to_query.append(revisions[0][0])

    for r_num in target_revisions_to_query:
        try:
            inspect_cmd = list(base_cmd) + [f"--revision={r_num}"]
            inspect_proc = subprocess.run(
                inspect_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30
            )
            if inspect_proc.returncode == 0 and inspect_proc.stdout.strip():
                revisions_data[r_num] = parse_pod_template(inspect_proc.stdout.strip())
        except Exception:
            pass

    return format_pod_version_analysis_report(
        deployment_name=target_deploy,
        namespace=namespace,
        history_table=history_output,
        revisions=revisions,
        revisions_data=revisions_data,
        inspected_revision=revision
    )


def Get_deployment_history(
    deployment_name: Optional[str] = None,
    pod_name: Optional[str] = None,
    namespace: str = "default",
    revision: Optional[int] = None,
    analyze_pod_version: bool = False,
    raw: bool = False,
    kubeconfig: Optional[str] = None,
    context: Optional[str] = None,
) -> str:
    """
    PascalCase alias for get_deployment_history for backwards compatibility.
    Defaults analyze_pod_version to False to maintain compatibility with legacy test assertions.
    """
    return get_deployment_history(
        deployment_name=deployment_name,
        pod_name=pod_name,
        namespace=namespace,
        revision=revision,
        analyze_pod_version=analyze_pod_version,
        raw=raw,
        kubeconfig=kubeconfig,
        context=context,
    )


def parse_node_conditions(describe_text: str) -> Dict[str, Dict[str, str]]:
    """
    Parses node conditions table or YAML from kubectl describe node output.
    Returns a mapping of ConditionType -> {status, reason, message}.
    """
    conditions: Dict[str, Dict[str, str]] = {}
    lines = describe_text.splitlines()
    in_conditions = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r'^Conditions:\s*$', stripped, re.IGNORECASE):
            in_conditions = True
            continue

        if in_conditions:
            if re.match(r'^(?:Addresses|Capacity|Allocatable|System Info|Non-terminated Pods|Allocated resources|Events):\s*', stripped, re.IGNORECASE):
                in_conditions = False
                continue

            if stripped.startswith("----") or stripped.startswith("Type"):
                continue

            m = re.match(r'^([a-zA-Z0-9_\-]+)\s+(True|False|Unknown)\s+(?:.*?)\s+([A-Za-z0-9_\-]+)\s+(.*)$', stripped)
            if m:
                c_type, c_status, c_reason, c_msg = m.group(1), m.group(2), m.group(3), m.group(4).strip()
                conditions[c_type] = {
                    "status": c_status,
                    "reason": c_reason,
                    "message": c_msg
                }
            else:
                m2 = re.match(r'^([a-zA-Z0-9_\-]+)\s+(True|False|Unknown)(?:\s+(.*))?$', stripped)
                if m2:
                    c_type, c_status = m2.group(1), m2.group(2)
                    rest = (m2.group(3) or "").strip()
                    conditions[c_type] = {
                        "status": c_status,
                        "reason": rest.split()[0] if rest else "<none>",
                        "message": rest
                    }

    # Fallback search if table wasn't matched (e.g. key-value or inline)
    for c_name in ["Ready", "MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"]:
        if c_name not in conditions:
            fb_m = re.search(rf'\b{c_name}\s*[:=]?\s*(True|False|Unknown)(?:\s+.*?([A-Za-z0-9_\-]+)\s+(.*))?', describe_text, re.IGNORECASE)
            if fb_m:
                st = fb_m.group(1)
                rsn = fb_m.group(2) or ("Normal" if st == "False" else "<unknown>")
                msg = fb_m.group(3) or ""
                conditions[c_name] = {"status": st, "reason": rsn, "message": msg.strip()}

    return conditions


def parse_node_taints(describe_text: str) -> List[str]:
    """
    Parses active taints from kubectl describe node output.
    """
    taints = []
    lines = describe_text.splitlines()
    in_taints = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Taints:"):
            in_taints = True
            content = stripped.split("Taints:", 1)[1].strip()
            if content and content != "<none>":
                for t in content.split():
                    if ":" in t:
                        taints.append(t)
            continue

        if in_taints:
            if re.match(r'^(?:Logging|CreationTimestamp|Conditions|Addresses|Capacity|Allocatable|System Info):\s*', stripped, re.IGNORECASE):
                in_taints = False
                continue
            if ":" in stripped:
                taint_match = re.search(r'([a-zA-Z0-9_\-\.\/]+:[A-Za-z]+)', stripped)
                if taint_match:
                    taints.append(taint_match.group(1))

    return list(dict.fromkeys(taints))


def parse_node_capacity_allocatable(describe_text: str) -> Dict[str, Dict[str, str]]:
    """
    Parses Capacity and Allocatable blocks from kubectl describe node output.
    """
    res = {"capacity": {}, "allocatable": {}}
    current_sec = None

    for line in describe_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r'^Capacity:\s*$', stripped, re.IGNORECASE):
            current_sec = "capacity"
            continue
        elif re.match(r'^Allocatable:\s*$', stripped, re.IGNORECASE):
            current_sec = "allocatable"
            continue
        elif re.match(r'^(?:System Info|Addresses|Conditions|Non-terminated Pods|Events):\s*', stripped, re.IGNORECASE):
            current_sec = None
            continue

        if current_sec:
            m = re.match(r'^([a-zA-Z0-9_\-]+):\s*(.+)$', stripped)
            if m:
                k, v = m.group(1), m.group(2).strip()
                res[current_sec][k] = v

    return res


def parse_node_system_info(describe_text: str) -> Dict[str, str]:
    """
    Parses System Info section from kubectl describe node output.
    """
    info = {}
    patterns = {
        "os_image": r'OS Image:\s*(.+)',
        "kernel_version": r'Kernel Version:\s*(.+)',
        "container_runtime": r'Container Runtime Version:\s*(.+)',
        "kubelet_version": r'Kubelet Version:\s*(.+)',
        "architecture": r'Architecture:\s*(.+)',
        "os": r'Operating System:\s*(.+)'
    }
    for key, pat in patterns.items():
        m = re.search(pat, describe_text, re.IGNORECASE)
        if m:
            info[key] = m.group(1).strip()
    return info


def parse_node_events(describe_text: str) -> List[str]:
    """
    Extracts Warning or Error event lines from kubectl describe node output.
    """
    events = []
    lines = describe_text.splitlines()
    in_events = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r'^Events:\s*$', stripped, re.IGNORECASE):
            in_events = True
            continue

        if in_events:
            if stripped.startswith("----") or stripped.startswith("Type"):
                continue
            if any(lvl in stripped for lvl in ["Warning", "Error", "Failed", "Evict", "Pressure", "NotReady"]):
                events.append(stripped)

    return events


def format_node_analysis_report(
    node_name: str,
    describe_text: str,
    conditions: Dict[str, Dict[str, str]],
    taints: List[str],
    capacity_alloc: Dict[str, Dict[str, str]],
    system_info: Dict[str, str],
    events: List[str]
) -> str:
    """
    Constructs an authoritative analytical report on Kubernetes node health,
    conditions, resource pressure, taints, and prescribed remediation actions.
    """
    lines = []
    lines.append("=" * 80)
    lines.append("🖥️  KUBERNETES NODE INFRASTRUCTURE & HEALTH ANALYSIS")
    lines.append("=" * 80)
    lines.append(f"Node Name : {node_name}")

    ready_cond = conditions.get("Ready", {})
    is_ready = ready_cond.get("status") == "True"
    ready_reason = ready_cond.get("reason", "<none>")
    ready_msg = ready_cond.get("message", "")

    status_badge = "🟢 READY / HEALTHY" if is_ready else "🔴 NOT READY / UNHEALTHY"
    lines.append(f"Status    : {status_badge}")

    kubelet_ver = system_info.get("kubelet_version", "<unknown>")
    runtime_ver = system_info.get("container_runtime", "<unknown>")
    os_img = system_info.get("os_image", "<unknown>")
    kernel = system_info.get("kernel_version", "<unknown>")

    lines.append(f"Kubelet   : {kubelet_ver} | Runtime: {runtime_ver}")
    lines.append(f"System    : {os_img} (Kernel: {kernel})")
    lines.append("-" * 80)

    # 1. Node Conditions Checklist
    lines.append("🩺 NODE CONDITIONS CHECKLIST:")
    standard_conditions = [
        ("Ready", "🟢 True (Healthy)" if is_ready else f"🔴 {ready_cond.get('status', 'Unknown')} (UNHEALTHY / NOT READY - {ready_reason})"),
        ("MemoryPressure", "🔴 True (MEMORY PRESSURE DETECTED)" if conditions.get("MemoryPressure", {}).get("status") == "True" else "🟢 False (Normal)"),
        ("DiskPressure", "🔴 True (DISK PRESSURE DETECTED)" if conditions.get("DiskPressure", {}).get("status") == "True" else "🟢 False (Normal)"),
        ("PIDPressure", "🔴 True (PID PRESSURE DETECTED)" if conditions.get("PIDPressure", {}).get("status") == "True" else "🟢 False (Normal)"),
        ("NetworkUnavailable", "🔴 True (NETWORK UNAVAILABLE)" if conditions.get("NetworkUnavailable", {}).get("status") == "True" else "🟢 False (Normal)"),
    ]

    for c_name, badge in standard_conditions:
        c_data = conditions.get(c_name, {})
        rsn = c_data.get("reason", "")
        msg = c_data.get("message", "")
        detail_str = f" [{rsn}] {msg}".strip() if (rsn or msg) and ("🔴" in badge) else ""
        lines.append(f"  • {c_name:<18}: {badge}{detail_str}")

    # 2. Active Taints
    lines.append("-" * 80)
    lines.append("🚫 ACTIVE TAINTS & SCHEDULING RESTRICTIONS:")
    if taints:
        for t in taints:
            effect_note = ""
            if "NoSchedule" in t:
                effect_note = " ➔ Prevents new pods from being scheduled"
            elif "NoExecute" in t:
                effect_note = " ➔ Evicts existing non-tolerating pods immediately"
            lines.append(f"  • {t}{effect_note}")
    else:
        lines.append("  • None (Node is fully schedulable)")

    # 3. Capacity vs Allocatable
    lines.append("-" * 80)
    lines.append("📊 RESOURCE CAPACITY & ALLOCATABLE LIMITS:")
    cap = capacity_alloc.get("capacity", {})
    alloc = capacity_alloc.get("allocatable", {})
    if cap or alloc:
        for r_key in ["cpu", "memory", "pods", "ephemeral-storage"]:
            c_val = cap.get(r_key, "<unknown>")
            a_val = alloc.get(r_key, "<unknown>")
            lines.append(f"  • {r_key.capitalize():<18}: Allocatable = {a_val} | Capacity = {c_val}")
    else:
        lines.append("  (Capacity and allocatable limits not reported)")

    # 4. Correlated Root Cause Hypothesis
    lines.append("-" * 80)
    lines.append("⚠️  CORRELATED ROOT CAUSE DIAGNOSIS:")
    issues_found = []

    if not is_ready:
        issues_found.append(
            f"Node is in 'NotReady' state ({ready_reason}: {ready_msg}). "
            "Kubelet heartbeat failed or container runtime (containerd/dockerd) became unresponsive (e.g. PLEG timeout or D-state tasks)."
        )

    if conditions.get("MemoryPressure", {}).get("status") == "True":
        mp_data = conditions["MemoryPressure"]
        issues_found.append(
            f"Node is experiencing severe Host Memory Pressure (Reason: {mp_data.get('reason')}). "
            "Kubelet will actively evict Burstable and BestEffort pods to reclaim host memory and prevent kernel panic."
        )

    if conditions.get("DiskPressure", {}).get("status") == "True":
        dp_data = conditions["DiskPressure"]
        issues_found.append(
            f"Node is under Disk Pressure (Reason: {dp_data.get('reason')}). "
            "Root partition or container writable layer is exhausted. Image garbage collection or pod eviction is active."
        )

    if conditions.get("PIDPressure", {}).get("status") == "True":
        issues_found.append(
            "Node is under PID Pressure. The maximum Linux PID limit has been approached, preventing container forks."
        )

    if not issues_found:
        lines.append("  • No active node-level faults detected. Node conditions and resource allocatables appear healthy.")
    else:
        for issue in issues_found:
            lines.append(f"  • {issue}")

    if events:
        lines.append("-" * 80)
        lines.append("⚠️  RECENT NODE WARNING & FAILURE EVENTS:")
        for ev_line in events[:5]:
            lines.append(f"  • {ev_line}")

    # 5. Prescribed Remediation Actions
    lines.append("-" * 80)
    lines.append("🛠️  PRESCRIBED NODE REMEDIATION ACTIONS:")
    if not is_ready:
        lines.append("  1. Check Kubelet and Containerd service logs on the host:")
        lines.append(f"     ssh <node-ip> 'journalctl -u kubelet -u containerd --no-pager -n 100'")
        lines.append("  2. Check for uninterruptible sleep (D-state) processes or deadlocks:")
        lines.append("     ssh <node-ip> 'ps aux | awk \"$8 ~ /D/\"'")
        lines.append(f"  3. Cordon the node to prevent scheduling new workloads while recovering:")
        lines.append(f"     kubectl cordon {node_name}")
    elif conditions.get("MemoryPressure", {}).get("status") == "True":
        lines.append(f"  1. Identify top memory consuming pods on the node:")
        lines.append(f"     kubectl top pods -A --field-selector spec.nodeName={node_name} --sort-by=memory")
        lines.append(f"  2. Check dmesg for host-level OOM kills:")
        lines.append(f"     ssh <node-ip> 'dmesg -T | grep -E \"oom|killed process|out of memory\"'")
        lines.append(f"  3. Consider draining non-critical workloads to restore node stability:")
        lines.append(f"     kubectl drain {node_name} --ignore-daemonsets --delete-emptydir-data")
    else:
        lines.append(f"  1. Inspect live events related to this node:")
        lines.append(f"     kubectl get events --field-selector involvedObject.name={node_name}")
        lines.append(f"  2. Inspect pod placement on this node:")
        lines.append(f"     kubectl get pods -A --field-selector spec.nodeName={node_name} -o wide")

    lines.append("=" * 80)
    return "\n".join(lines)


def get_node_info(
    node_name: Optional[str] = None,
    pod_name: Optional[str] = None,
    namespace: str = "default",
    analyze_node_health: bool = True,
    raw: bool = False,
    kubeconfig: Optional[str] = None,
    context: Optional[str] = None,
) -> str:
    """
    Fetches and analyzes Kubernetes node infrastructure details (status, conditions,
    taints, capacity, allocatable limits, and events) using kubectl describe node.

    Args:
        node_name: Name of the target Kubernetes node (e.g., 'k8s-worker-node-14').
        pod_name: Optional pod name. If node_name is not provided, resolves the node
                  scheduled for this pod.
        namespace: Kubernetes namespace where the pod resides (default: 'default').
        analyze_node_health: If True, parses conditions, taints, allocatable limits,
                             and produces an analytical health report (default: True).
        raw: If True, returns only the raw kubectl describe node output.
        kubeconfig: Optional explicit path to kubeconfig file.
        context: Optional kubeconfig context to use.

    Returns:
        A structured string detailing node health, conditions, taints, and remediation.

    Raises:
        ValueError: If neither node_name nor pod_name is provided.
        KubernetesNodeInfoError: If kubectl fails to retrieve node information.
    """
    target_node = node_name.strip() if node_name and node_name.strip() else None

    # If node_name not given, attempt to infer from pod_name
    if not target_node:
        if pod_name and pod_name.strip():
            pod_clean = pod_name.strip()
            ns_clean = namespace.strip() if namespace else "default"
            mock_pod_key = f"{ns_clean}/{pod_clean}"

            if mock_pod_key in _MOCK_POD_TO_NODE:
                target_node = _MOCK_POD_TO_NODE[mock_pod_key]
            elif pod_clean in _MOCK_POD_TO_NODE:
                target_node = _MOCK_POD_TO_NODE[pod_clean]
            elif len(_MOCK_NODE_INFO) == 1:
                target_node = next(iter(_MOCK_NODE_INFO.keys()))
            else:
                kubectl_bin = shutil.which("kubectl") or "kubectl"
                get_node_cmd = [kubectl_bin, "get", "pod", pod_clean, "-n", ns_clean, "-o", "jsonpath={.spec.nodeName}"]
                if kubeconfig:
                    get_node_cmd.extend(["--kubeconfig", str(kubeconfig)])
                if context:
                    get_node_cmd.extend(["--context", str(context)])

                try:
                    p_res = subprocess.run(
                        get_node_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=15
                    )
                    if p_res.returncode == 0 and p_res.stdout.strip():
                        target_node = p_res.stdout.strip()
                except Exception:
                    pass

        if not target_node:
            raise ValueError("Either node_name or pod_name must be provided to fetch node information.")

    # Check mock registry first
    if target_node in _MOCK_NODE_INFO:
        raw_describe = _MOCK_NODE_INFO[target_node]
        if raw or not analyze_node_health:
            return raw_describe

        conds = parse_node_conditions(raw_describe)
        taints = parse_node_taints(raw_describe)
        cap_alloc = parse_node_capacity_allocatable(raw_describe)
        sys_info = parse_node_system_info(raw_describe)
        events = parse_node_events(raw_describe)

        return format_node_analysis_report(
            node_name=target_node,
            describe_text=raw_describe,
            conditions=conds,
            taints=taints,
            capacity_alloc=cap_alloc,
            system_info=sys_info,
            events=events
        )

    # Check mock directory if configured
    mock_dir = os.environ.get("K8S_MOCK_NODES_DIR")
    if mock_dir:
        mock_path = Path(mock_dir) / f"{target_node}.log"
        if mock_path.exists():
            file_content = mock_path.read_text(encoding="utf-8", errors="replace")
            if raw or not analyze_node_health:
                return file_content
            conds = parse_node_conditions(file_content)
            taints = parse_node_taints(file_content)
            cap_alloc = parse_node_capacity_allocatable(file_content)
            sys_info = parse_node_system_info(file_content)
            events = parse_node_events(file_content)
            return format_node_analysis_report(
                node_name=target_node,
                describe_text=file_content,
                conditions=conds,
                taints=taints,
                capacity_alloc=cap_alloc,
                system_info=sys_info,
                events=events
            )

    # Verify kubectl is installed
    kubectl_bin = shutil.which("kubectl") or "kubectl"
    cmd = [kubectl_bin, "describe", "node", target_node]

    if kubeconfig:
        cmd.extend(["--kubeconfig", str(kubeconfig)])
    if context:
        cmd.extend(["--context", str(context)])

    cmd_str = " ".join(cmd)

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60
        )
    except FileNotFoundError:
        raise KubernetesNodeInfoError(
            f"kubectl executable not found. Ensure kubectl is installed and present in PATH.",
            command=cmd_str
        )
    except subprocess.TimeoutExpired:
        raise KubernetesNodeInfoError(
            f"Timed out after 60 seconds while fetching node info for '{target_node}'.",
            command=cmd_str
        )
    except Exception as e:
        raise KubernetesNodeInfoError(
            f"Unexpected error running kubectl: {str(e)}",
            command=cmd_str
        )

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        raise KubernetesNodeInfoError(
            f"Failed to fetch node info for '{target_node}'.\nError: {err_msg}",
            command=cmd_str,
            stderr=err_msg
        )

    output = proc.stdout.strip()
    if raw or not analyze_node_health:
        return output

    conds = parse_node_conditions(output)
    taints = parse_node_taints(output)
    cap_alloc = parse_node_capacity_allocatable(output)
    sys_info = parse_node_system_info(output)
    events = parse_node_events(output)

    return format_node_analysis_report(
        node_name=target_node,
        describe_text=output,
        conditions=conds,
        taints=taints,
        capacity_alloc=cap_alloc,
        system_info=sys_info,
        events=events
    )


def triage_low_confidence_incident(
    target: Any,
    pod_name: Optional[str] = None,
    namespace: str = "default",
    node_name: Optional[str] = None,
    confidence_threshold: float = 0.70,
    min_evidence_items: int = 2,
    kubeconfig: Optional[str] = None,
    context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Intelligent triage tool specifically invoked when an incident investigation
    exhibits low confidence (< confidence_threshold) or few evidence items (< min_evidence_items).

    Performs deep cross-surface correlation across:
      1. Previous container termination logs (--previous) for pre-crash stack traces
      2. Kubernetes pod events for scheduler and kubelet warnings
      3. Node infrastructure health and conditions via get_node_info
      4. Deployment rollout history and container version changes via get_deployment_history

    Elevates diagnostic confidence or provides an SRE escalation triage playbook.
    """
    from .parser import K8sLogParser
    from .detectors import K8sDiagnosticEngine
    from .remediation import RemediationAdvisor
    from .models import InvestigationResult, FailureCategory, Severity, EvidenceItem

    initial_result: Optional[InvestigationResult] = None
    target_pod = pod_name
    target_ns = namespace or "default"
    target_node = node_name
    raw_logs = ""

    if isinstance(target, InvestigationResult):
        initial_result = target
        target_pod = target_pod or initial_result.resource_context.pod_name
        target_ns = target_ns or initial_result.resource_context.namespace or "default"
        target_node = target_node or initial_result.resource_context.node_name
    elif isinstance(target, str):
        stripped = target.strip()
        if "\n" not in stripped and len(stripped) < 120 and " " not in stripped:
            target_pod = stripped
            try:
                raw_logs = Get_Pod_logs(target_pod, namespace=target_ns, kubeconfig=kubeconfig, context=context)
            except Exception:
                raw_logs = ""
        else:
            raw_logs = target

        parser = K8sLogParser()
        diag = K8sDiagnosticEngine()
        entries = parser.parse_logs(raw_logs)
        ctx = parser.extract_resource_context(entries)
        if target_pod and not ctx.pod_name:
            ctx.pod_name = target_pod
        if target_ns and not ctx.namespace:
            ctx.namespace = target_ns
        if target_node and not ctx.node_name:
            ctx.node_name = target_node

        cat, sev, conf, ev = diag.analyze_entries(entries)
        summary, rca, rem, ver = RemediationAdvisor.get_advice(cat, ctx)
        initial_result = InvestigationResult(
            primary_category=cat,
            severity=sev,
            confidence_score=conf,
            summary=summary,
            root_cause_analysis=rca,
            resource_context=ctx,
            evidence_timeline=ev,
            remediation_steps=rem,
            verification_commands=ver
        )

    if not initial_result:
        raise ValueError("Unable to determine initial investigation result from target.")

    # Check if confidence or evidence is low
    is_low_confidence = (
        initial_result.confidence_score < confidence_threshold or
        len(initial_result.evidence_timeline) < min_evidence_items or
        initial_result.primary_category == FailureCategory.UNKNOWN_ANOMALY
    )

    if not is_low_confidence:
        report_text = (
            f"✅ HIGH CONFIDENCE ALREADY ESTABLISHED\n"
            f"Incident is classified as {initial_result.primary_category.value} with confidence "
            f"{initial_result.confidence_score:.2f} and {len(initial_result.evidence_timeline)} correlated evidence items.\n"
            f"Deep multi-surface low-confidence triage not required."
        )
        return {
            "is_low_confidence": False,
            "status": "CONFIDENT",
            "initial_confidence": initial_result.confidence_score,
            "initial_evidence_count": len(initial_result.evidence_timeline),
            "primary_category": initial_result.primary_category.value,
            "message": "Incident already has sufficient diagnostic confidence and evidence items.",
            "report": report_text,
            "result": initial_result
        }

    # Low confidence detected: initiate multi-surface gathering
    surfaces_queried: List[str] = []
    enriched_telemetry_chunks: List[str] = []

    if raw_logs:
        enriched_telemetry_chunks.append("--- BASELINE POD LOGS ---\n" + raw_logs)
    elif initial_result and initial_result.evidence_timeline:
        ev_lines = [e.raw_content for e in initial_result.evidence_timeline]
        enriched_telemetry_chunks.append("--- BASELINE EVIDENCE ITEMS ---\n" + "\n".join(ev_lines))

    # 1. Query previous container logs
    if target_pod:
        try:
            prev_logs = Get_Pod_logs(
                pod_name=target_pod,
                namespace=target_ns,
                previous=True,
                kubeconfig=kubeconfig,
                context=context
            )
            if prev_logs and prev_logs.strip():
                surfaces_queried.append("previous_container_logs")
                enriched_telemetry_chunks.append(f"--- PREVIOUS TERMINATED CONTAINER LOGS ({target_pod}) ---\n" + prev_logs)
        except Exception:
            pass

    # 2. Query pod events
    if target_pod:
        try:
            events = Get_Pod_events(
                pod_name=target_pod,
                namespace=target_ns,
                kubeconfig=kubeconfig,
                context=context
            )
            if events and "No events recorded" not in events:
                surfaces_queried.append("pod_events")
                enriched_telemetry_chunks.append(f"--- POD CLUSTER EVENTS ({target_pod}) ---\n" + events)
        except Exception:
            pass

    # 3. Query node infrastructure health via get_node_info
    node_report_str = ""
    try:
        node_report_str = get_node_info(
            node_name=target_node,
            pod_name=target_pod,
            namespace=target_ns,
            analyze_node_health=True,
            kubeconfig=kubeconfig,
            context=context
        )
        if node_report_str:
            surfaces_queried.append("node_health_info")
            enriched_telemetry_chunks.append("--- NODE HEALTH & CONDITIONS ---\n" + node_report_str)
    except Exception:
        pass

    # 4. Query deployment rollout history
    try:
        if target_pod:
            deploy_hist = get_deployment_history(
                pod_name=target_pod,
                namespace=target_ns,
                analyze_pod_version=True,
                kubeconfig=kubeconfig,
                context=context
            )
            if deploy_hist:
                surfaces_queried.append("deployment_rollout_history")
                enriched_telemetry_chunks.append("--- DEPLOYMENT ROLLOUT HISTORY ---\n" + deploy_hist)
    except Exception:
        pass

    # Combine all enriched telemetry and re-evaluate
    combined_telemetry = "\n\n".join(enriched_telemetry_chunks)
    parser = K8sLogParser()
    diag = K8sDiagnosticEngine()
    re_entries = parser.parse_logs(combined_telemetry)
    re_ctx = parser.extract_resource_context(re_entries)
    if target_pod and not re_ctx.pod_name:
        re_ctx.pod_name = target_pod
    if target_ns and not re_ctx.namespace:
        re_ctx.namespace = target_ns
    if target_node and not re_ctx.node_name:
        re_ctx.node_name = target_node

    elevated_cat, elevated_sev, elevated_conf, elevated_ev = diag.analyze_entries(re_entries)
    elevated_summary, elevated_rca, elevated_rem, elevated_ver = RemediationAdvisor.get_advice(elevated_cat, re_ctx)

    enriched_result = InvestigationResult(
        primary_category=elevated_cat,
        severity=elevated_sev,
        confidence_score=elevated_conf,
        summary=elevated_summary,
        root_cause_analysis=elevated_rca,
        resource_context=re_ctx,
        evidence_timeline=elevated_ev,
        remediation_steps=elevated_rem,
        verification_commands=elevated_ver
    )

    is_elevated = (
        elevated_conf >= confidence_threshold and
        len(elevated_ev) >= min_evidence_items and
        elevated_cat != FailureCategory.UNKNOWN_ANOMALY
    )

    triage_status = "ELEVATED" if is_elevated else "ESCALATION_REQUIRED"

    triage_data = {
        "is_low_confidence": True,
        "triage_status": triage_status,
        "initial_confidence": initial_result.confidence_score,
        "initial_evidence_count": len(initial_result.evidence_timeline),
        "initial_category": initial_result.primary_category.value,
        "elevated_confidence": elevated_conf,
        "elevated_evidence_count": len(elevated_ev),
        "resolved_category": elevated_cat.value,
        "surfaces_queried": surfaces_queried,
        "enriched_result": enriched_result,
        "target_pod": target_pod,
        "target_namespace": target_ns,
        "target_node": target_node,
    }

    triage_data["report"] = format_low_confidence_triage_report(triage_data)
    return triage_data


def format_low_confidence_triage_report(triage_data: Dict[str, Any]) -> str:
    """
    Formats the output of triage_low_confidence_incident into a clean markdown report.
    """
    lines = []
    lines.append("=" * 80)
    lines.append("🔍 LOW-CONFIDENCE INCIDENT TRIAGE & MULTI-SURFACE DIAGNOSIS")
    lines.append("=" * 80)
    lines.append(f"Target Pod      : {triage_data.get('target_pod') or '<none>'}")
    lines.append(f"Namespace       : {triage_data.get('target_namespace') or 'default'}")
    lines.append(f"Triage Status   : {'🟢 RESOLVED / ELEVATED' if triage_data.get('triage_status') == 'ELEVATED' else '⚠️ ESCALATION REQUIRED'}")
    lines.append(f"Surfaces Probed : {', '.join(triage_data.get('surfaces_queried', [])) or 'None'}")
    lines.append("-" * 80)
    lines.append(f"• Baseline Confidence : {triage_data.get('initial_confidence', 0.0):.2f} ({triage_data.get('initial_evidence_count', 0)} evidence items) | Category: {triage_data.get('initial_category')}")
    lines.append(f"• Elevated Confidence : {triage_data.get('elevated_confidence', 0.0):.2f} ({triage_data.get('elevated_evidence_count', 0)} evidence items) | Category: {triage_data.get('resolved_category')}")
    lines.append("-" * 80)

    if triage_data.get("triage_status") == "ELEVATED":
        res = triage_data.get("enriched_result")
        lines.append("🎯 ROOT CAUSE DISCOVERED VIA MULTI-SURFACE CORRELATION:")
        lines.append(f"  {res.summary}")
        lines.append("")
        lines.append("📋 NEWLY CORRELATED EVIDENCE:")
        for idx, item in enumerate(res.evidence_timeline, start=1):
            lines.append(f"  [{idx}] Line {item.line_number}: {item.significance}")
            lines.append(f"      Snippet: {item.raw_content[:90]}")
        lines.append("")
        lines.append("🛠️ ACTIONABLE REMEDIATION:")
        for r_step in res.remediation_steps[:4]:
            lines.append(f"  • {r_step}")
    else:
        lines.append("⚠️ ROOT CAUSE STILL UNRESOLVED (LOW SIGNAL / AMBIGUOUS INCIDENT)")
        lines.append("  Telemetry from previous logs, events, and node health did not isolate a definitive signature.")
        lines.append("")
        lines.append("🔎 RECOMMENDED SRE DEEP-DIVE ESCALATION STEPS:")
        lines.append("  1. Check for silent application deadlocks or thread pool starvations:")
        lines.append("     kubectl exec -it <pod> -c <container> -- jcmd 1 Thread.print (or kill -QUIT 1)")
        lines.append("  2. Inspect Linux host kernel ring buffer for hardware/driver faults:")
        lines.append("     ssh <node-ip> 'dmesg -T | grep -E \"call trace|segfault|error|hung\"'")
        lines.append("  3. Check CNI network connectivity and DNS resolution:")
        lines.append("     kubectl exec -it <pod> -- nc -zvw3 <service-ip> <port>")
        lines.append("  4. Inspect Kubernetes admission webhooks for silent drops or mutating rejections:")
        lines.append("     kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations")

    lines.append("=" * 80)
    return "\n".join(lines)


# Common aliases and naming conventions
Get_deployment_histroy = Get_deployment_history
get_pod_logs = Get_Pod_logs
get_pod_events = Get_Pod_events
Get_node_info = get_node_info
Get_Node_info = get_node_info
triage_low_confidence = triage_low_confidence_incident
diagnose_low_confidence = triage_low_confidence_incident
triage_uncertain_incident = triage_low_confidence_incident
get_low_confidence_triage = triage_low_confidence_incident
Triage_low_confidence_incident = triage_low_confidence_incident



