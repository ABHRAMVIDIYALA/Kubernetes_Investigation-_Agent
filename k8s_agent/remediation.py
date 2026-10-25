from typing import List, Tuple
from .models import FailureCategory, K8sResourceContext

class RemediationAdvisor:
    @staticmethod
    def get_advice(category: FailureCategory, ctx: K8sResourceContext) -> Tuple[str, str, List[str], List[str]]:
        """
        Returns:
            (summary, root_cause_analysis, remediation_steps, verification_commands)
        """
        pod = ctx.pod_name or "<pod-name>"
        ns = ctx.namespace or "default"
        container = f"-c {ctx.container_name}" if ctx.container_name else ""

        if category == FailureCategory.OOM_KILLED:
            summary = f"Container terminated due to Out-Of-Memory (OOMKilled - Exit code 137) in pod '{pod}'."
            rca = (
                f"The container exceeded its configured memory limit (`resources.limits.memory`) or the node experienced "
                f"severe memory pressure forcing the Linux kernel cgroup OOM killer to terminate the process (SIGKILL).\n"
                f"Supporting indicators: Exit code 137 (128 + SIGKILL 9), memory exhaustion events, or runtime heap errors."
            )
            remediation = [
                f"Inspect current resource limits and termination history:\n  kubectl describe pod {pod} -n {ns}",
                f"Monitor real-time memory usage of the container:\n  kubectl top pod {pod} -n {ns} --containers",
                "Increase `resources.limits.memory` and `resources.requests.memory` in the Deployment/StatefulSet specification.",
                "If running a JVM/Node application, tune runtime flags (e.g., `-XX:MaxRAMPercentage=75.0` or `--max-old-space-size=<mb>`) to leave headroom for non-heap native memory.",
                "Investigate potential memory leaks (e.g. unclosed file descriptors, cache accumulation, unbounded queues)."
            ]
            verification = [
                f"Check recent OOM termination events across the namespace:\n  kubectl get events -n {ns} --field-selector reason=OOMKilling",
                f"Verify pod stability and ensure restart count remains stable:\n  kubectl get pod {pod} -n {ns} -w"
            ]

        elif category == FailureCategory.CRASH_LOOP_BACKOFF:
            summary = f"Container is stuck in CrashLoopBackOff state in pod '{pod}'."
            rca = (
                f"The application process exited prematurely upon launch with an error status. "
                f"Kubelet detected the repeated crash and placed the pod into exponential back-off restart delays."
            )
            remediation = [
                f"Extract exit logs from the previously crashed container instance:\n  kubectl logs {pod} -n {ns} {container} --previous",
                f"Inspect termination reason, exit code, and start time:\n  kubectl get pod {pod} -n {ns} -o jsonpath='{{.status.containerStatuses[*].lastState.terminated}}'",
                "Review environment variables, secret mounts, and configuration dependencies required at startup.",
                f"Start a temporary interactive debugging container if needed:\n  kubectl debug {pod} -n {ns} -it --image=busybox"
            ]
            verification = [
                f"Confirm the container status transitions to 'Running':\n  kubectl get pod {pod} -n {ns}",
                f"Stream active logs to verify clean initialization:\n  kubectl logs -f {pod} -n {ns} {container}"
            ]

        elif category == FailureCategory.IMAGE_PULL_FAILURE:
            summary = f"Kubernetes cannot fetch or authenticate the container image for pod '{pod}'."
            rca = (
                f"Kubelet failed to pull the specified image tag from the remote registry. "
                f"Probable root causes include non-existent image tag, misspelled registry path, "
                f"missing or expired imagePullSecrets, or registry rate limits."
            )
            remediation = [
                f"Check exact image pull error event details:\n  kubectl describe pod {pod} -n {ns} | grep -E 'Failed|BackOff'",
                "Verify the image repository, tag, and architecture match the host cluster.",
                f"Verify `imagePullSecrets` is configured in the pod spec or ServiceAccount:\n  kubectl get serviceaccount default -n {ns} -o yaml",
                f"Ensure Docker registry credentials are valid and recreate secret if necessary:\n  kubectl create secret docker-registry regcred --docker-server=<server> --docker-username=<user> --docker-password=<token> -n {ns}"
            ]
            verification = [
                f"Observe container transition from ImagePullBackOff to Running:\n  kubectl get pod {pod} -n {ns} -w"
            ]

        elif category == FailureCategory.PROBE_FAILURE:
            summary = f"Liveness/Readiness probe failures detected on pod '{pod}'."
            rca = (
                f"Kubelet health check probes timed out, received an HTTP 5xx error, or failed TCP connection. "
                f"If a liveness probe fails, Kubelet restarts the container. If a readiness probe fails, "
                f"the pod is removed from Service endpoints, causing 502/503 errors upstream."
            )
            remediation = [
                f"Inspect probe definitions and failure thresholds:\n  kubectl describe pod {pod} -n {ns} | grep -A 8 'Liveness:'",
                "If the app requires extra time to initialize, introduce a `startupProbe` or increase `initialDelaySeconds`.",
                "Ensure health endpoints (`/healthz`, `/ready`) do not perform heavy database queries or external calls.",
                f"Port-forward directly to the pod to test health endpoint responsiveness:\n  kubectl port-forward {pod} -n {ns} 8080:8080"
            ]
            verification = [
                f"Verify endpoints are actively registered in the Service:\n  kubectl get endpoints -n {ns}",
                f"Confirm pod conditions report ContainersReady and Ready: True:\n  kubectl get pod {pod} -n {ns} -o jsonpath='{{.status.conditions}}'"
            ]

        elif category == FailureCategory.NETWORK_DNS_TIMEOUT:
            summary = f"Inter-service network communication or CoreDNS resolution timeout in pod '{pod}'."
            rca = (
                f"The application was unable to resolve hostname addresses or experienced TCP timeouts connecting "
                f"to internal cluster services or external APIs. This can stem from CoreDNS latency/overload, "
                f"misconfigured NetworkPolicies, or egress firewall rules."
            )
            remediation = [
                "Verify CoreDNS cluster deployment health:\n  kubectl get pods -n kube-system -l k8s-app=kube-dns",
                "Check CoreDNS logs for upstream forwarding timeouts or loops:\n  kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50",
                f"Inspect active NetworkPolicies affecting namespace '{ns}':\n  kubectl get networkpolicy -n {ns}",
                f"Run an ephemeral DNS diagnosis pod inside the cluster:\n  kubectl run dns-test --image=curlimages/curl -it --rm -- restart=Never -- nslookup kubernetes.default"
            ]
            verification = [
                f"Test connectivity from within the affected namespace to target services:\n  kubectl exec -it {pod} -n {ns} -- curl -Iv <target-service>"
            ]

        elif category == FailureCategory.DATABASE_CONNECTION_ERROR:
            summary = f"Database connection pool exhaustion or network unreachable for pod '{pod}'."
            rca = (
                "The application cannot communicate with its backend database. Possible causes include "
                "exhausted connection pool limits, database pod restart, incorrect connection credentials, "
                "or missing Kubernetes Secret values."
            )
            remediation = [
                "Check backend database pod status and connection count limits.",
                "Tune application connection pool sizing (`max_connections`, `pool_size`, `timeout`).",
                f"Verify database connection string and secret injection:\n  kubectl describe pod {pod} -n {ns} | grep -i db"
            ]
            verification = [
                f"Inspect app logs to confirm successful connection acquisition:\n  kubectl logs {pod} -n {ns} --tail=20"
            ]

        elif category == FailureCategory.STORAGE_MOUNT_FAILURE:
            summary = f"PersistentVolume / PVC attachment or mount failed on pod '{pod}'."
            rca = (
                "Kubelet was unable to attach or mount storage volumes. Common issues include volume already "
                "attached to another node (ReadWriteOnce conflict), volume driver timeout, or storage quota exceeded."
            )
            remediation = [
                f"Check VolumeAttachment and PVC status:\n  kubectl get pvc -n {ns}",
                f"Inspect pod storage events:\n  kubectl describe pod {pod} -n {ns} | grep -A 5 'Volumes:'",
                "If volume is stuck attached to another node, cordoned node or force unmount may be required."
            ]
            verification = [
                f"Verify PVC status is 'Bound':\n  kubectl get pvc -n {ns}"
            ]

        elif category == FailureCategory.RBAC_PERMISSION_DENIED:
            summary = f"RBAC 403 Forbidden authorization failure on pod '{pod}'."
            rca = (
                "The pod's assigned ServiceAccount lacks sufficient permissions in the cluster RBAC policy "
                "to perform the requested Kubernetes API operation."
            )
            remediation = [
                f"Identify ServiceAccount bound to pod:\n  kubectl get pod {pod} -n {ns} -o jsonpath='{{.spec.serviceAccountName}}'",
                f"Test ServiceAccount permissions using can-i:\n  kubectl auth can-i --as=system:serviceaccount:{ns}:<sa-name> list pods -n {ns}",
                "Create or bind appropriate Role/ClusterRole to the ServiceAccount."
            ]
            verification = [
                f"Verify authorization succeeds:\n  kubectl auth can-i --as=system:serviceaccount:{ns}:<sa-name> get <resource> -n {ns}"
            ]

        elif category == FailureCategory.APPLICATION_PANIC:
            summary = f"Application crashed due to unhandled exception or segmentation fault (SIGSEGV) in pod '{pod}'."
            rca = (
                "The containerized binary suffered an uncaught runtime exception, memory corruption, "
                "or panic, causing it to abort immediately."
            )
            remediation = [
                f"Inspect full crash stack trace:\n  kubectl logs {pod} -n {ns} {container} --previous",
                "Ensure required configuration files and environment secrets exist.",
                "Review code changes or dependency updates deployed in this container image."
            ]
            verification = [
                f"Confirm clean application start:\n  kubectl logs {pod} -n {ns} --tail=50"
            ]

        elif category == FailureCategory.CPU_THROTTLING:
            summary = f"Severe CPU throttling detected for pod '{pod}' under rigid CFS quota limits."
            rca = (
                "The container's CPU quota was exhausted within its 100ms Completely Fair Scheduler (CFS) period, "
                "causing the Linux kernel to freeze process threads. This leads to high event loop latency, "
                "thread pool saturation, and downstream 504 Gateway Timeout errors."
            )
            remediation = [
                f"Remove or increase `resources.limits.cpu` in the deployment manifest (set requests accurately while leaving limits unconstrained):\n  kubectl edit deployment <deploy-name> -n {ns}",
                f"Monitor real-time CPU throttling metrics:\n  kubectl top pod {pod} -n {ns} --containers",
                "Configure a HorizontalPodAutoscaler (HPA) to scale replicas based on CPU target utilization."
            ]
            verification = [
                f"Verify container responsiveness and latency reduction:\n  kubectl top pod {pod} -n {ns}"
            ]

        elif category == FailureCategory.NODE_MEMORY_PRESSURE:
            summary = f"Worker node experienced severe memory pressure causing pod eviction for '{pod}'."
            rca = (
                "The host node's available memory dropped below the Kubelet hard eviction threshold (typically <100Mi). "
                "To prevent an unrecoverable kernel panic, Kubelet actively evicted Burstable and BestEffort pods."
            )
            remediation = [
                "Cordon the pressurized node to prevent new pod scheduling:\n  kubectl cordon <node-name>",
                "Inspect memory consumers across the node:\n  kubectl describe node <node-name> | grep -A 7 'Allocated resources:'",
                "Set Guaranteed QoS (`requests.memory == limits.memory`) on mission-critical pods to protect them from eviction."
            ]
            verification = [
                "Verify node conditions show MemoryPressure=False:\n  kubectl get nodes -o wide"
            ]

        elif category == FailureCategory.NODE_NOT_READY:
            summary = f"Worker node transitioned to NotReady state due to Kubelet or PLEG failure."
            rca = (
                "The Kubelet Pod Lifecycle Event Generator (PLEG) missed its heartbeat deadline (>3 minutes), "
                "often caused by container runtime (containerd/dockerd) deadlock, disk I/O saturation, or D-Bus lockup."
            )
            remediation = [
                "SSH to the node and inspect kubelet and containerd service status:\n  sudo systemctl status kubelet containerd",
                "Restart the container runtime and kubelet:\n  sudo systemctl restart containerd && sudo systemctl restart kubelet",
                "If node remains degraded, drain workloads safely:\n  kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data"
            ]
            verification = [
                "Confirm node status recovers to 'Ready':\n  kubectl get nodes"
            ]

        elif category == FailureCategory.INCORRECT_RESOURCE_SPEC:
            summary = f"Pod '{pod}' is unschedulable due to impossible or invalid resource requests."
            rca = (
                "Kube-scheduler cannot place the pod onto any cluster node because requested CPU or memory "
                "exceeds the maximum allocatable capacity of any single available node (0/N nodes available)."
            )
            remediation = [
                "Check cluster node allocatable capacity:\n  kubectl get nodes -o custom-columns=NAME:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory",
                "Adjust `resources.requests` in the pod template to fit within node sizing limits.",
                "If huge capacity is genuinely required, provision specialized node groups with larger instance types."
            ]
            verification = [
                f"Confirm pod transitions from Pending to Scheduled:\n  kubectl get pod {pod} -n {ns} -w"
            ]

        elif category == FailureCategory.SERVICE_NO_ENDPOINTS:
            summary = f"Kubernetes Service has 0 endpoints matching pod selector for '{pod}'."
            rca = (
                "The Service's `spec.selector` labels do not match the labels defined on any Ready pods. "
                "As a result, EndpointSlice contains 0 IP addresses and all incoming traffic receives 503 or connection refused."
            )
            remediation = [
                f"Compare Service selector against pod labels:\n  kubectl get service <service-name> -n {ns} -o yaml | grep -A 4 'selector:'\n  kubectl get pods -n {ns} --show-labels",
                f"Patch Service selector to match pod labels:\n  kubectl patch service <service-name> -n {ns} -p '{{\"spec\":{{\"selector\":{{\"<correct-label>\":\"<val>\"}}}}}}'"
            ]
            verification = [
                f"Verify endpoints are actively populated:\n  kubectl get endpoints <service-name> -n {ns}"
            ]

        elif category == FailureCategory.SERVICE_ROUTES_TO_UNHEALTHY_PODS:
            summary = f"Service routes traffic to unhealthy or canary pods via an overly broad selector."
            rca = (
                "The Service selector matches unintended pods (such as canary, staging, or unready instances) "
                "because selector labels are shared across deployments without release/tier isolation."
            )
            remediation = [
                f"Inspect all pods matching the Service selector:\n  kubectl get pods -n {ns} -l <selector-key>=<selector-val> --show-labels",
                "Add discriminating labels (`release: stable`, `environment: production`) to isolate production traffic from canary pods.",
                "Ensure canary pods have proper readiness probes so traffic is not routed before initialization."
            ]
            verification = [
                f"Verify Service endpoints only point to healthy production pods:\n  kubectl get endpoints <service-name> -n {ns} -o wide"
            ]

        else:
            summary = f"Anomalous behavior or errors observed in logs for pod '{pod}'."
            rca = (
                "The logs contain error-level messages, but did not match a known catastrophic Kubernetes failure pattern. "
                "Review the isolated evidence lines for domain-specific errors."
            )
            remediation = [
                f"Check full pod logs:\n  kubectl logs {pod} -n {ns} --tail=100",
                f"Check recent events in namespace:\n  kubectl get events -n {ns} --sort-by='.lastTimestamp'"
            ]
            verification = [
                f"Verify pod health:\n  kubectl get pod {pod} -n {ns}"
            ]

        return summary, rca, remediation, verification
