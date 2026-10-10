import os
from typing import Optional, List, Union
from pathlib import Path

from .models import InvestigationResult, K8sResourceContext, FailureCategory, Severity, EvidenceItem
from .parser import K8sLogParser
from .detectors import K8sDiagnosticEngine
from .remediation import RemediationAdvisor
from .tools import Get_Pod_logs, Get_Pod_events, Get_deployment_history, KubernetesEventFetchError

class K8sInvestigationAgent:
    """
    Intelligent Kubernetes Log Investigation Agent.
    Combines rule-based diagnostics, Kubernetes event correlation,
    and optional LLM enhancement to deliver root-cause analysis with supporting evidence.
    """

    def __init__(self, enable_llm: bool = True):
        self.parser = K8sLogParser()
        self.diagnostic_engine = K8sDiagnosticEngine()
        self.enable_llm = enable_llm
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def investigate(self, log_content: str) -> InvestigationResult:
        if not log_content or not log_content.strip():
            return InvestigationResult(
                summary="No log content provided for investigation.",
                root_cause_analysis="Empty log input.",
                severity=Severity.INFO,
                confidence_score=0.0
            )

        # Step 1: Parse and normalize log entries
        parsed_entries = self.parser.parse_logs(log_content)
        resource_ctx = self.parser.extract_resource_context(parsed_entries)

        # Step 2: Diagnostic pattern matching & evidence extraction
        category, severity, confidence, evidence = self.diagnostic_engine.analyze_entries(parsed_entries)

        # Step 3: Generate RCA & remediation plan
        summary, rca, remediation, verification = RemediationAdvisor.get_advice(category, resource_ctx)

        # Step 4: Optional LLM Synthesis (if API key available)
        llm_notes = None
        if self.enable_llm and self.api_key:
            llm_notes = self._synthesize_with_gemini(log_content, category, evidence, resource_ctx)

        return InvestigationResult(
            primary_category=category,
            severity=severity,
            confidence_score=confidence,
            summary=summary,
            root_cause_analysis=rca,
            resource_context=resource_ctx,
            evidence_timeline=evidence,
            remediation_steps=remediation,
            verification_commands=verification,
            additional_notes=llm_notes
        )

    def investigate_file(self, file_path: Union[str, Path]) -> InvestigationResult:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Log file not found: {file_path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        return self.investigate(content)

    def investigate_pod(
        self,
        pod_name: str,
        namespace: str = "default",
        container: Optional[str] = None,
        tail_lines: Optional[int] = None,
        previous: bool = False,
        timestamps: bool = True,
        include_events: bool = True,
        include_deployment_history: bool = True,
        kubeconfig: Optional[str] = None,
        context: Optional[str] = None,
    ) -> InvestigationResult:
        """
        Fetches the logs of a target Kubernetes pod using the Get_Pod_logs tool,
        optionally correlates events using Get_Pod_events and deployment changes via Get_deployment_history,
        and performs an automated root cause investigation and evidence extraction.
        """
        logs = Get_Pod_logs(
            pod_name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
            previous=previous,
            timestamps=timestamps,
            kubeconfig=kubeconfig,
            context=context,
        )

        # Correlate pod events if requested
        if include_events:
            try:
                events = Get_Pod_events(
                    pod_name=pod_name,
                    namespace=namespace,
                    kubeconfig=kubeconfig,
                    context=context,
                )
                if events and "No events recorded" not in events:
                    logs += f"\n\n--- KUBERNETES POD EVENTS ({pod_name}) ---\n" + events
            except Exception:
                # Graceful non-blocking fallback if events cannot be fetched
                pass

        # Correlate recent deployment rollout history and version changes
        if include_deployment_history:
            try:
                history = Get_deployment_history(
                    pod_name=pod_name,
                    namespace=namespace,
                    kubeconfig=kubeconfig,
                    context=context,
                )
                if history:
                    logs += f"\n\n--- DEPLOYMENT ROLLOUT HISTORY & RECENT REVISION CHANGES ---\n" + history
            except Exception:
                # Graceful non-blocking fallback if deployment history cannot be fetched
                pass

        result = self.investigate(logs)

        # Ensure pod name & namespace are populated in resource context
        if not result.resource_context.pod_name:
            result.resource_context.pod_name = pod_name
        if not result.resource_context.namespace:
            result.resource_context.namespace = namespace
        if container and not result.resource_context.container_name:
            result.resource_context.container_name = container

        return result

    def get_pod_events(
        self,
        pod_name: str,
        namespace: str = "default",
        kubeconfig: Optional[str] = None,
        context: Optional[str] = None,
    ) -> str:
        """
        Directly fetches events for a specific pod using the Get_Pod_events tool.
        """
        return Get_Pod_events(
            pod_name=pod_name,
            namespace=namespace,
            kubeconfig=kubeconfig,
            context=context,
        )

    def get_deployment_history(
        self,
        deployment_name: Optional[str] = None,
        pod_name: Optional[str] = None,
        namespace: str = "default",
        revision: Optional[int] = None,
        kubeconfig: Optional[str] = None,
        context: Optional[str] = None,
    ) -> str:
        """
        Directly fetches and analyzes deployment rollout history and version changes using Get_deployment_history.
        """
        return Get_deployment_history(
            deployment_name=deployment_name,
            pod_name=pod_name,
            namespace=namespace,
            revision=revision,
            kubeconfig=kubeconfig,
            context=context,
        )

    def _synthesize_with_gemini(
        self,
        raw_logs: str,
        category: FailureCategory,
        evidence: List[EvidenceItem],
        ctx: K8sResourceContext
    ) -> Optional[str]:
        try:
            # Try importing google.genai or google.generativeai
            # pyrefly: ignore [missing-import]
            import google.genai as genai
            client = genai.Client(api_key=self.api_key)
            prompt = (
                f"You are a Kubernetes SRE specialist. Review this diagnostic hypothesis:\n"
                f"Category: {category.value}\n"
                f"Pod: {ctx.pod_name}, Namespace: {ctx.namespace}\n"
                f"Isolated Evidence count: {len(evidence)}\n"
                f"Logs snippet:\n{raw_logs[:2000]}\n\n"
                f"Provide a 2-3 sentence expert assessment and any subtle gotchas."
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            return response.text.strip()
        except Exception:
            # Non-blocking fallback if LLM client is missing or fails
            return None
