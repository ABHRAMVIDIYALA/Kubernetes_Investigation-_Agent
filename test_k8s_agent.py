import unittest
from pathlib import Path
from k8s_agent import (
    K8sInvestigationAgent,
    K8sLogParser,
    FailureCategory,
    Severity,
    ReportFormatter,
    Get_Pod_logs,
    Get_Pod_events,
    Get_deployment_history,
    Get_deployment_histroy,
    get_deployment_history,
    get_pod_logs,
    get_pod_events,
    get_node_info,
    Get_node_info,
    Get_Node_info,
    triage_low_confidence_incident,
    triage_low_confidence,
    diagnose_low_confidence,
    parse_node_conditions,
    parse_node_taints,
    KubernetesLogFetchError,
    KubernetesEventFetchError,
    KubernetesDeploymentHistoryError,
    KubernetesNodeInfoError,
    register_mock_pod_logs,
    register_mock_pod_events,
    register_mock_deployment_history,
    register_mock_deployment_revision,
    register_mock_node_info,
    register_mock_pod_node,
    clear_mock_pod_logs,
    clear_mock_pod_events,
    clear_mock_deployment_history,
    clear_mock_deployment_revisions,
    clear_mock_node_info,
    infer_deployment_name,
)

class TestK8sInvestigationAgent(unittest.TestCase):
    def setUp(self):
        self.agent = K8sInvestigationAgent(enable_llm=False)
        self.sample_dir = Path(__file__).parent / "samples"
        clear_mock_pod_logs()
        clear_mock_node_info()

    def tearDown(self):
        clear_mock_pod_logs()
        clear_mock_node_info()

    def test_oom_killed_investigation(self):
        log_file = self.sample_dir / "sample_oom_kill.log"
        self.assertTrue(log_file.exists())
        result = self.agent.investigate_file(log_file)

        self.assertEqual(result.primary_category, FailureCategory.OOM_KILLED)
        self.assertEqual(result.severity, Severity.CRITICAL)
        self.assertGreaterEqual(result.confidence_score, 0.8)
        self.assertIn("payment-service-589f8dc94-p9w7c", result.resource_context.pod_name)
        self.assertEqual(result.resource_context.exit_code, 137)
        self.assertGreater(len(result.evidence_timeline), 0)

        # Check evidence contains the OOM kernel line
        has_oom_evidence = any("Memory cgroup out of memory" in e.raw_content for e in result.evidence_timeline)
        self.assertTrue(has_oom_evidence)

    def test_dns_crashloop_investigation(self):
        log_file = self.sample_dir / "sample_crashloop_dns.log"
        self.assertTrue(log_file.exists())
        result = self.agent.investigate_file(log_file)

        self.assertIn(result.primary_category, (FailureCategory.NETWORK_DNS_TIMEOUT, FailureCategory.CRASH_LOOP_BACKOFF))
        self.assertEqual(result.severity, Severity.HIGH)
        self.assertIn("order-processor-78d46bf7b-2v4lk", result.resource_context.pod_name)
        self.assertGreater(len(result.remediation_steps), 0)

    def test_probe_failure_investigation(self):
        log_file = self.sample_dir / "sample_probe_timeout.log"
        self.assertTrue(log_file.exists())
        result = self.agent.investigate_file(log_file)

        self.assertEqual(result.primary_category, FailureCategory.PROBE_FAILURE)
        self.assertEqual(result.severity, Severity.HIGH)
        self.assertIn("catalog-api-6d8794db54-k8mx9", result.resource_context.pod_name)

    def test_image_pull_failure_inline(self):
        raw_log = """
        2026-10-10T10:00:00Z kubelet: Pulling image "myrepo.azurecr.io/orders:v9.9.9"
        2026-10-10T10:00:02Z kubelet: Failed to pull image: rpc error: code = NotFound desc = failed to pull and unpack image: manifest for myrepo.azurecr.io/orders:v9.9.9 not found
        2026-10-10T10:00:03Z kubelet: Error: ErrImagePull
        2026-10-10T10:00:15Z kubelet: Error: ImagePullBackOff in pod order-worker-554488-88xzz
        """
        result = self.agent.investigate(raw_log)
        self.assertEqual(result.primary_category, FailureCategory.IMAGE_PULL_FAILURE)
        self.assertEqual(result.severity, Severity.HIGH)

    def test_json_log_parsing(self):
        json_logs = """
        {"time": "2026-10-10T12:00:00Z", "level": "info", "msg": "Worker started", "pod": "worker-1"}
        {"time": "2026-10-10T12:00:05Z", "level": "error", "msg": "connection to server at 10.0.0.5:5432 failed: Connection refused"}
        """
        result = self.agent.investigate(json_logs)
        self.assertEqual(result.primary_category, FailureCategory.DATABASE_CONNECTION_ERROR)
        self.assertGreater(len(result.evidence_timeline), 0)

    def test_markdown_and_console_formatters(self):
        log_file = self.sample_dir / "sample_oom_kill.log"
        result = self.agent.investigate_file(log_file)
        md = ReportFormatter.to_markdown(result)
        console = ReportFormatter.to_console(result, use_color=False)

        self.assertIn("# 🛡️ Kubernetes Investigation Report:", md)
        self.assertIn("Supporting Evidence", md)
        self.assertIn("KUBERNETES INCIDENT INVESTIGATION REPORT", console)

    def test_empty_log_handling(self):
        result = self.agent.investigate("   \n\n  ")
        self.assertEqual(result.confidence_score, 0.0)
        self.assertEqual(result.severity, Severity.INFO)

    def test_get_pod_logs_empty_param_validation(self):
        with self.assertRaises(ValueError):
            Get_Pod_logs("")
        with self.assertRaises(ValueError):
            Get_Pod_logs("   ")

    def test_get_pod_logs_with_mock_registry(self):
        mock_logs = (
            "2026-10-10T14:00:00Z stderr F java.lang.OutOfMemoryError: Java heap space\n"
            "2026-10-10T14:00:01Z stderr F kubelet: Container payment-app terminated with exit code 137 (OOMKilled)\n"
        )
        register_mock_pod_logs("payment-pod-123", mock_logs, namespace="finance")

        fetched = Get_Pod_logs("payment-pod-123", namespace="finance")
        self.assertEqual(fetched, mock_logs)

    def test_investigate_pod_end_to_end(self):
        mock_logs = (
            "2026-10-10T14:00:00Z stderr F java.lang.OutOfMemoryError: Java heap space\n"
            "2026-10-10T14:00:01Z stderr F kubelet: Container payment-app terminated with exit code 137 (OOMKilled)\n"
        )
        register_mock_pod_logs("payment-pod-123", mock_logs, namespace="finance")

        # Test investigator using Get_Pod_logs tool directly
        result = self.agent.investigate_pod("payment-pod-123", namespace="finance")

        self.assertEqual(result.primary_category, FailureCategory.OOM_KILLED)
        self.assertEqual(result.severity, Severity.CRITICAL)
        self.assertEqual(result.resource_context.pod_name, "payment-pod-123")
        self.assertEqual(result.resource_context.namespace, "finance")
        self.assertGreater(len(result.evidence_timeline), 0)

    def test_get_pod_logs_live_failure_raises_error(self):
        # Fetching non-existent pod without mock should raise KubernetesLogFetchError
        with self.assertRaises(KubernetesLogFetchError) as ctx:
            Get_Pod_logs("non-existent-pod-xyz-999", namespace="non-existent-ns")
        self.assertIn("Failed to fetch logs", str(ctx.exception))

    def test_get_pod_events_empty_param_validation(self):
        with self.assertRaises(ValueError):
            Get_Pod_events("")
        with self.assertRaises(ValueError):
            Get_Pod_events("   ")

    def test_get_pod_events_with_mock_registry(self):
        mock_events = (
            "LAST SEEN   TYPE      REASON       MESSAGE\n"
            "2m          Warning   OOMKilling   Memory cgroup out of memory: Kill process 123\n"
        )
        register_mock_pod_events("my-worker-pod", mock_events, namespace="batch")

        fetched = Get_Pod_events("my-worker-pod", namespace="batch")
        self.assertEqual(fetched, mock_events)

    def test_get_pod_events_live_failure_raises_error(self):
        with self.assertRaises(KubernetesEventFetchError) as ctx:
            Get_Pod_events("non-existent-pod-xyz-999", namespace="non-existent-ns")
        self.assertIn("Failed to fetch events", str(ctx.exception))

    def test_investigate_pod_with_events_correlation(self):
        mock_logs = "2026-10-10T12:00:00Z stdout F Starting worker process\n"
        mock_events = (
            "LAST SEEN   TYPE      REASON       MESSAGE\n"
            "10s         Warning   OOMKilling   Memory cgroup out of memory: Kill process 9999\n"
        )
        register_mock_pod_logs("data-sync-pod", mock_logs, namespace="analytics")
        register_mock_pod_events("data-sync-pod", mock_events, namespace="analytics")

        result = self.agent.investigate_pod("data-sync-pod", namespace="analytics", include_events=True)

        # The OOM event should be detected and reflected in the diagnosis
        self.assertEqual(result.primary_category, FailureCategory.OOM_KILLED)
        self.assertEqual(result.severity, Severity.CRITICAL)
        self.assertEqual(result.resource_context.pod_name, "data-sync-pod")

    def test_infer_deployment_name(self):
        self.assertEqual(infer_deployment_name("payment-service-589f8dc94-p9w7c"), "payment-service")
        self.assertEqual(infer_deployment_name("order-worker-78d46bf7b-2v4lk"), "order-worker")
        self.assertEqual(infer_deployment_name("custom-app-12345"), "custom-app")

    def test_get_deployment_history_validation(self):
        with self.assertRaises(ValueError):
            Get_deployment_history(deployment_name=None, pod_name=None)
        with self.assertRaises(ValueError):
            Get_deployment_history(deployment_name="   ", pod_name="   ")

    def test_get_deployment_history_mock(self):
        mock_history = (
            "REVISION  CHANGE-CAUSE\n"
            "1         Initial deployment\n"
            "2         Updated image to myrepo/payment:v2.4.1\n"
        )
        register_mock_deployment_history("payment-service", mock_history, namespace="production")

        # Test direct retrieval
        fetched = Get_deployment_history(deployment_name="payment-service", namespace="production")
        self.assertEqual(fetched, mock_history)

        # Test alias Get_deployment_histroy
        fetched_alias = Get_deployment_histroy(deployment_name="payment-service", namespace="production")
        self.assertEqual(fetched_alias, mock_history)

    def test_get_deployment_history_inferred_from_pod(self):
        mock_history = (
            "REVISION  CHANGE-CAUSE\n"
            "1         v1.0.0\n"
            "2         v2.0.0 (memory limit lowered)\n"
        )
        register_mock_deployment_history("checkout-api", mock_history, namespace="default")

        # Inferred from checkout-api-6879df-abcde
        fetched = Get_deployment_history(pod_name="checkout-api-6879dfbc12-abcde", namespace="default")
        self.assertEqual(fetched, mock_history)

    def test_get_deployment_history_live_failure_raises_error(self):
        with self.assertRaises(KubernetesDeploymentHistoryError) as ctx:
            Get_deployment_history(deployment_name="non-existent-deployment-999", namespace="non-existent-ns")
        self.assertIn("Failed to fetch deployment rollout history", str(ctx.exception))

    def test_investigate_pod_with_deployment_history_correlation(self):
        mock_logs = "2026-10-10T12:00:00Z stdout F [INFO] Worker launched\n"
        mock_history = (
            "REVISION  CHANGE-CAUSE\n"
            "3         Upgraded to image tag v2.4.1\n"
        )
        register_mock_pod_logs("billing-engine-79bf94f890-12345", mock_logs, namespace="billing")
        register_mock_deployment_history("billing-engine", mock_history, namespace="billing")

        result = self.agent.investigate_pod("billing-engine-79bf94f890-12345", namespace="billing", include_deployment_history=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.resource_context.pod_name, "billing-engine-79bf94f890-12345")

    def test_get_deployment_history_pod_version_analysis_mock(self):
        mock_history = (
            "REVISION  CHANGE-CAUSE\n"
            "1         Initial deployment\n"
            "2         Updated image to myrepo/payment:v2.4.1\n"
        )
        register_mock_deployment_history("payment-service", mock_history, namespace="production")

        analysis = get_deployment_history(deployment_name="payment-service", namespace="production")
        self.assertIn("POD VERSION & DEPLOYMENT ROLLOUT ANALYSIS", analysis)
        self.assertIn("Active Pod : Revision #2", analysis)
        self.assertIn("Prior Pod  : Revision #1", analysis)
        self.assertIn("myrepo/payment:v2.4.1", analysis)
        self.assertIn("kubectl rollout undo deployment/payment-service -n production --to-revision=1", analysis)

    def test_get_deployment_history_with_revision_details_mock(self):
        mock_history = (
            "REVISION  CHANGE-CAUSE\n"
            "1         Initial release\n"
            "2         Upgrade nginx\n"
        )
        rev1_template = (
            "deployment.apps/web-frontend with revision #1\n"
            "Pod Template:\n"
            "  Labels: app=web-frontend\n"
            "  Containers:\n"
            "   web-app:\n"
            "    Image: nginx:1.24\n"
            "    Port: 80/TCP\n"
        )
        rev2_template = (
            "deployment.apps/web-frontend with revision #2\n"
            "Pod Template:\n"
            "  Labels: app=web-frontend\n"
            "  Containers:\n"
            "   web-app:\n"
            "    Image: nginx:1.25.3\n"
            "    Port: 80/TCP\n"
        )
        register_mock_deployment_history("web-frontend", mock_history, namespace="staging")
        register_mock_deployment_revision("web-frontend", 1, rev1_template, namespace="staging")
        register_mock_deployment_revision("web-frontend", 2, rev2_template, namespace="staging")

        analysis = get_deployment_history(deployment_name="web-frontend", namespace="staging")
        self.assertIn("Container 'web-app': ⚠️ POD VERSION CHANGED", analysis)
        self.assertIn("Previous Image : nginx:1.24 (Revision #1)", analysis)
        self.assertIn("Current Image  : nginx:1.25.3 (Revision #2)", analysis)
        self.assertIn("Tag Transition : 1.24 ➔ 1.25.3", analysis)
        self.assertIn("kubectl rollout undo deployment/web-frontend -n staging --to-revision=1", analysis)

    def test_get_deployment_history_single_revision(self):
        mock_history = (
            "REVISION  CHANGE-CAUSE\n"
            "1         Initial deployment\n"
        )
        register_mock_deployment_history("single-service", mock_history, namespace="prod")

        analysis = get_deployment_history(deployment_name="single-service", namespace="prod")
        self.assertIn("Initial deployment (Revision #1)", analysis)
        self.assertIn("No previous pod versions to compare", analysis)

    def test_get_deployment_history_specific_revision(self):
        mock_history = (
            "REVISION  CHANGE-CAUSE\n"
            "1         v1.0.0\n"
            "2         v2.0.0\n"
        )
        rev2_template = (
            "deployment.apps/order-api with revision #2\n"
            "Pod Template:\n"
            "  Containers:\n"
            "   api:\n"
            "    Image: myrepo/order:v2.0.0\n"
        )
        register_mock_deployment_history("order-api", mock_history, namespace="default")
        register_mock_deployment_revision("order-api", 2, rev2_template, namespace="default")

        analysis = get_deployment_history(deployment_name="order-api", namespace="default", revision=2)
        self.assertIn("Inspecting Revision #2", analysis)
        self.assertIn("Container 'api': Image = myrepo/order:v2.0.0", analysis)

    def test_get_deployment_history_raw_flag(self):
        mock_history = (
            "REVISION  CHANGE-CAUSE\n"
            "1         Initial deployment\n"
            "2         Updated image to myrepo/payment:v2.4.1\n"
        )
        register_mock_deployment_history("payment-service", mock_history, namespace="production")

        raw_output = get_deployment_history(deployment_name="payment-service", namespace="production", raw=True)
        self.assertEqual(raw_output, mock_history)

    def test_lowercase_tool_aliases(self):
        mock_logs = "2026-10-10T12:00:00Z stdout F worker running\n"
        mock_events = "LAST SEEN TYPE REASON MESSAGE\n1m Normal Started Pod started\n"
        register_mock_pod_logs("alias-pod", mock_logs, namespace="test")
        register_mock_pod_events("alias-pod", mock_events, namespace="test")

        fetched_logs = get_pod_logs("alias-pod", namespace="test")
        fetched_events = get_pod_events("alias-pod", namespace="test")

        self.assertEqual(fetched_logs, mock_logs)
        self.assertEqual(fetched_events, mock_events)

        agent_events = self.agent.get_pod_events("alias-pod", namespace="test")
        agent_logs = self.agent.get_pod_logs("alias-pod", namespace="test")
        self.assertEqual(agent_events, mock_events)
        self.assertEqual(agent_logs, mock_logs)

    def test_get_node_info_memory_pressure_analysis(self):
        mock_node_text = (
            "Name:               k8s-worker-1\n"
            "Roles:              worker\n"
            "Taints:             node.kubernetes.io/memory-pressure:NoSchedule\n"
            "Conditions:\n"
            "  Type                 Status  LastHeartbeatTime                 Reason                       Message\n"
            "  ----                 ------  -----------------                 ------                       -------\n"
            "  NetworkUnavailable   False   Mon, 20 Oct 2026 04:00:00 +0000   RouteCreated                 RouteController created a route\n"
            "  MemoryPressure       True    Mon, 25 Oct 2026 08:10:00 +0000   KubeletHasMemoryPressure     kubelet has memory pressure\n"
            "  DiskPressure         False   Mon, 25 Oct 2026 08:10:00 +0000   KubeletHasNoDiskPressure     kubelet has no disk pressure\n"
            "  PIDPressure          False   Mon, 25 Oct 2026 08:10:00 +0000   KubeletHasSufficientPID      kubelet has sufficient PID available\n"
            "  Ready                True    Mon, 25 Oct 2026 08:10:00 +0000   KubeletReady                 kubelet is posting ready status\n"
            "Capacity:\n"
            "  cpu:     4\n"
            "  memory:  16384000Ki\n"
            "  pods:    110\n"
            "Allocatable:\n"
            "  cpu:     3800m\n"
            "  memory:  15000000Ki\n"
            "  pods:    110\n"
            "System Info:\n"
            "  OS Image:                   Ubuntu 22.04.3 LTS\n"
            "  Kernel Version:             5.15.0-aws\n"
            "  Container Runtime Version:  containerd://1.6.28\n"
            "  Kubelet Version:            v1.28.3\n"
            "Events:\n"
            "  Warning  EvictionThresholdMet  1m  kubelet  Attempting to evict pod due to memory pressure\n"
        )
        register_mock_node_info("k8s-worker-1", mock_node_text)

        report = get_node_info("k8s-worker-1")
        self.assertIn("Node Name : k8s-worker-1", report)
        self.assertIn("MemoryPressure", report)
        self.assertIn("MEMORY PRESSURE DETECTED", report)
        self.assertIn("node.kubernetes.io/memory-pressure:NoSchedule", report)
        self.assertIn("Allocatable = 3800m", report)
        self.assertIn("CORRELATED ROOT CAUSE DIAGNOSIS", report)
        self.assertIn("PRESCRIBED NODE REMEDIATION ACTIONS", report)

    def test_get_node_info_not_ready_pleg(self):
        mock_node_text = (
            "Name:               k8s-worker-14\n"
            "Roles:              worker\n"
            "Taints:             node.kubernetes.io/not-ready:NoSchedule\n"
            "Conditions:\n"
            "  Type                 Status  LastHeartbeatTime                 Reason                       Message\n"
            "  ----                 ------  -----------------                 ------                       -------\n"
            "  Ready                False   Mon, 25 Oct 2026 08:10:00 +0000   KubeletNotReady              PLEG is not healthy\n"
            "  MemoryPressure       False   Mon, 25 Oct 2026 08:10:00 +0000   KubeletHasNoMemoryPressure   kubelet has sufficient memory\n"
            "System Info:\n"
            "  OS Image:                   Ubuntu 22.04.3 LTS\n"
            "  Kernel Version:             5.15.0-aws\n"
            "  Container Runtime Version:  containerd://1.6.28\n"
            "  Kubelet Version:            v1.28.3\n"
        )
        register_mock_node_info("k8s-worker-14", mock_node_text)

        report = get_node_info("k8s-worker-14")
        self.assertIn("🔴 NOT READY / UNHEALTHY", report)
        self.assertIn("PLEG is not healthy", report)
        self.assertIn("node.kubernetes.io/not-ready:NoSchedule", report)
        self.assertIn("journalctl -u kubelet -u containerd", report)

    def test_get_node_info_raw_and_missing_args(self):
        mock_node_text = "Name: node-raw-1\nConditions:\n  Ready True\n"
        register_mock_node_info("node-raw-1", mock_node_text)

        raw = get_node_info("node-raw-1", raw=True)
        self.assertEqual(raw, mock_node_text)

        with self.assertRaises(ValueError):
            get_node_info()

    def test_get_node_info_inferred_from_pod(self):
        mock_node_text = (
            "Name:               node-alpha\n"
            "Conditions:\n"
            "  Ready True\n"
            "  MemoryPressure False\n"
        )
        register_mock_node_info("node-alpha", mock_node_text)
        register_mock_pod_node("order-pod-xyz", "node-alpha", namespace="production")

        report = get_node_info(pod_name="order-pod-xyz", namespace="production")
        self.assertIn("Node Name : node-alpha", report)

    def test_triage_low_confidence_elevated_by_node_pressure(self):
        # Baseline pod log has vague content without high confidence failure pattern
        vague_log = "2026-10-25T08:00:00Z stderr F process received termination signal; shutting down."
        mock_node_text = (
            "Name:               worker-node-beta\n"
            "Conditions:\n"
            "  Ready              True   Mon, 25 Oct 2026 08:10:00 +0000 KubeletReady kubelet ready\n"
            "  MemoryPressure     True   Mon, 25 Oct 2026 08:10:00 +0000 KubeletHasMemoryPressure kubelet has memory pressure\n"
            "Events:\n"
            "  Warning  EvictionThresholdMet  1m  kubelet  Attempting to evict pod checkout-worker to reclaim memory\n"
        )
        register_mock_node_info("worker-node-beta", mock_node_text)
        register_mock_pod_node("checkout-worker-5899-xyz", "worker-node-beta", namespace="ecommerce")

        # Baseline investigation yields low confidence (< 0.70)
        base_result = self.agent.investigate(vague_log)
        self.assertLess(base_result.confidence_score, 0.70)

        # Run multi-surface triage
        triage_res = triage_low_confidence_incident(
            target=base_result,
            pod_name="checkout-worker-5899-xyz",
            namespace="ecommerce",
        )

        self.assertTrue(triage_res["is_low_confidence"])
        self.assertEqual(triage_res["triage_status"], "ELEVATED")
        self.assertEqual(triage_res["resolved_category"], FailureCategory.NODE_MEMORY_PRESSURE.value)
        self.assertGreaterEqual(triage_res["elevated_confidence"], 0.80)
        self.assertGreaterEqual(triage_res["elevated_evidence_count"], 2)
        self.assertIn("ROOT CAUSE DISCOVERED VIA MULTI-SURFACE CORRELATION", triage_res["report"])

    def test_triage_low_confidence_already_confident(self):
        sample_log = (self.sample_dir / "sample_oom_kill.log").read_text(encoding="utf-8")
        high_conf_result = self.agent.investigate(sample_log)
        self.assertGreaterEqual(high_conf_result.confidence_score, 0.80)

        triage_res = triage_low_confidence_incident(high_conf_result)
        self.assertFalse(triage_res["is_low_confidence"])
        self.assertEqual(triage_res["status"], "CONFIDENT")

    def test_node_info_and_triage_aliases(self):
        mock_node_text = "Name: node-alias-1\nConditions:\n  Ready True\n"
        register_mock_node_info("node-alias-1", mock_node_text)

        report1 = Get_node_info("node-alias-1")
        report2 = Get_Node_info("node-alias-1")
        report3 = self.agent.get_node_info("node-alias-1")
        self.assertIn("Node Name : node-alias-1", report1)
        self.assertEqual(report1, report2)
        self.assertEqual(report1, report3)

        triage_call = self.agent.triage_low_confidence(
            target="unknown error line",
            pod_name="test-pod"
        )
        self.assertIn("is_low_confidence", triage_call)

if __name__ == "__main__":
    unittest.main()


