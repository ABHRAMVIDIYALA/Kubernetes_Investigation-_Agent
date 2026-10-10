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
    KubernetesLogFetchError,
    KubernetesEventFetchError,
    KubernetesDeploymentHistoryError,
    register_mock_pod_logs,
    register_mock_pod_events,
    register_mock_deployment_history,
    clear_mock_pod_logs,
    clear_mock_pod_events,
    clear_mock_deployment_history,
    infer_deployment_name,
)

class TestK8sInvestigationAgent(unittest.TestCase):
    def setUp(self):
        self.agent = K8sInvestigationAgent(enable_llm=False)
        self.sample_dir = Path(__file__).parent / "samples"
        clear_mock_pod_logs()

    def tearDown(self):
        clear_mock_pod_logs()

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

if __name__ == "__main__":
    unittest.main()

