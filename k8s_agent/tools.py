import os
import shutil
import subprocess
from typing import Optional, Dict, Any
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

# In-memory mock registries for testing and offline development
_MOCK_POD_LOGS: Dict[str, str] = {}
_MOCK_POD_EVENTS: Dict[str, str] = {}
_MOCK_DEPLOYMENT_HISTORY: Dict[str, str] = {}

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

def clear_mock_pod_logs() -> None:
    """Clears all registered mock pod logs, events, and deployment history."""
    _MOCK_POD_LOGS.clear()
    _MOCK_POD_EVENTS.clear()
    _MOCK_DEPLOYMENT_HISTORY.clear()

def clear_mock_pod_events() -> None:
    """Clears all registered mock pod events."""
    _MOCK_POD_EVENTS.clear()

def clear_mock_deployment_history() -> None:
    """Clears all registered mock deployment history."""
    _MOCK_DEPLOYMENT_HISTORY.clear()

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

def Get_deployment_history(
    deployment_name: Optional[str] = None,
    pod_name: Optional[str] = None,
    namespace: str = "default",
    revision: Optional[int] = None,
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
                  If omitted, fetches the rollout history overview and detailed changes from the latest revision.
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
        return _MOCK_DEPLOYMENT_HISTORY[mock_key]

    # Check if a mock directory is specified via environment variable
    mock_dir = os.environ.get("K8S_MOCK_DEPLOYMENTS_DIR")
    if mock_dir:
        mock_path = Path(mock_dir) / f"{target_deploy}_history.log"
        if mock_path.exists():
            return mock_path.read_text(encoding="utf-8", errors="replace")

    # Verify kubectl is installed
    kubectl_bin = shutil.which("kubectl") or "kubectl"

    # Base rollout history command
    base_cmd = [kubectl_bin, "rollout", "history", f"deployment/{target_deploy}", "-n", namespace]

    if kubeconfig:
        base_cmd.extend(["--kubeconfig", str(kubeconfig)])
    if context:
        base_cmd.extend(["--context", str(context)])

    if revision is not None:
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

    # If general history was requested, also attempt to inspect the latest revision's pod template
    # to highlight container images and recent version changes
    if revision is None:
        try:
            # Query the latest revision details
            inspect_cmd = list(base_cmd) + ["--revision=0"]
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
                details = inspect_proc.stdout.strip()
                return f"{history_output}\n\n--- CURRENT REVISION POD TEMPLATE & IMAGES ---\n{details}"
        except Exception:
            pass

    return history_output

# Alias supporting user's exact query naming
Get_deployment_histroy = Get_deployment_history

