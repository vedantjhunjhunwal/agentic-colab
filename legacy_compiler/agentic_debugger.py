"""
Agentic Debugger for the AI Workflow DSL Compiler.

This module intentionally sits OUTSIDE the deterministic compiler stages.
It does not change lexer/parser/semantic/codegen behavior. Instead, it acts as
an AI-agent-style reviewer around the compiler output:

1. Observe source + compiler artifacts
2. Diagnose errors and workflow risks
3. Explain root causes in developer-friendly language
4. Recommend safe fixes
5. Produce a structured validation report for the Web IDE / CLI

The implementation is deterministic by default so the project runs without API
keys. The class boundary is designed so an LLM/tool-calling backend can later be
plugged into the same analyze(...) method without touching the compiler core.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


AI_STATEMENT_PATTERNS = {
    "PIPELINE": r"^PIPELINE\s+(\w+)$",
    "DATASET": r"^DATASET\s+(\w+)\s+FROM\s+'([^']+)'$",
    "MODEL": r"^MODEL\s+(\w+)\s+TASK\s+'([^']+)'$",
    "SET": r"^SET\s+(\w+)\s*=\s*(-?\d+)$",
    "TRAIN": r"^TRAIN\s+(\w+)\s+ON\s+(\w+)\s+EPOCHS\s+(\d+)$",
    "EVALUATE": r"^EVALUATE\s+(\w+)$",
    "PREDICT": r"^PREDICT\s+(\w+)\s+INPUT\s*(-?\d+)(?:\s+INTO\s+(\w+))?$",
    "DEPLOY": r"^DEPLOY\s+(\w+)\s+TO\s+'([^']+)'$",
    "MONITOR": r"^MONITOR\s+(\w+)$",
    "LOG": r"^LOG\s+'([^']*)'$",
    "ENDPIPELINE": r"^ENDPIPELINE$",
}


@dataclass
class AgentFinding:
    severity: str
    category: str
    message: str
    line: Optional[int] = None
    suggestion: Optional[str] = None


@dataclass
class AgentReport:
    role: str
    status: str
    validation_score: int
    summary: str
    architecture_trace: List[str]
    findings: List[AgentFinding]
    suggested_fixes: List[str]
    workflow_graph: List[str]
    cv_evidence: List[str]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data

    def to_text(self) -> str:
        lines = [
            f"Agent Role: {self.role}",
            f"Status: {self.status}",
            f"Validation Score: {self.validation_score}/100",
            "",
            "Summary:",
            f"  {self.summary}",
            "",
            "Architecture Trace:",
        ]
        lines.extend(f"  - {item}" for item in self.architecture_trace)
        lines.append("")
        lines.append("Workflow Graph:")
        if self.workflow_graph:
            lines.extend(f"  - {edge}" for edge in self.workflow_graph)
        else:
            lines.append("  - No AI workflow graph detected.")
        lines.append("")
        lines.append("Findings:")
        if self.findings:
            for f in self.findings:
                loc = f"Line {f.line}: " if f.line else ""
                lines.append(f"  [{f.severity.upper()}] {f.category}: {loc}{f.message}")
                if f.suggestion:
                    lines.append(f"      Fix: {f.suggestion}")
        else:
            lines.append("  - No issues found by the agent.")
        lines.append("")
        lines.append("Suggested Fixes:")
        if self.suggested_fixes:
            lines.extend(f"  - {fix}" for fix in self.suggested_fixes)
        else:
            lines.append("  - No fixes required.")
        lines.append("")
        lines.append("CV Evidence:")
        lines.extend(f"  - {item}" for item in self.cv_evidence)
        return "\n".join(lines)


class CompilerAgent:
    """Deterministic AI-agent layer around the compiler pipeline."""

    def analyze(
        self,
        source: str,
        compile_results: Dict[str, Any],
        runtime_result: Optional[Dict[str, Any]] = None,
        runtime_error: Optional[Dict[str, Any]] = None,
    ) -> AgentReport:
        source_language = compile_results.get("source_language", "pascal_like_core_dsl")
        findings: List[AgentFinding] = []

        findings.extend(self._explain_compiler_errors(compile_results))
        workflow_graph: List[str] = []

        if source_language == "ai_workflow_dsl":
            ai_findings, workflow_graph = self._inspect_ai_workflow(source)
            findings.extend(ai_findings)
        else:
            findings.extend(self._inspect_core_program(source))

        if runtime_error:
            findings.append(
                AgentFinding(
                    severity="error",
                    category="Runtime execution",
                    line=runtime_error.get("line"),
                    message=runtime_error.get("message", "Runtime failed."),
                    suggestion="Check dataset paths, model order, input values, and runtime-only constraints after compilation succeeds.",
                )
            )

        runtime_warnings = []
        if runtime_result:
            runtime_warnings = runtime_result.get("warnings", []) or []
        runtime_warnings.extend(compile_results.get("runtime_warnings", []) or [])
        for warning in runtime_warnings:
            findings.append(
                AgentFinding(
                    severity="warning",
                    category="Runtime warning",
                    message=str(warning),
                    suggestion="Review the warning and make the DSL statement explicit if production behavior matters.",
                )
            )

        status, score = self._score(compile_results, findings, runtime_error)
        architecture_trace = self._architecture_trace(compile_results)
        suggested_fixes = self._suggested_fixes(findings, source_language)
        summary = self._summary(status, source_language, compile_results, findings)
        cv_evidence = self._cv_evidence(source_language)

        return AgentReport(
            role="Compiler Validation + Debugging Agent",
            status=status,
            validation_score=score,
            summary=summary,
            architecture_trace=architecture_trace,
            findings=findings,
            suggested_fixes=suggested_fixes,
            workflow_graph=workflow_graph,
            cv_evidence=cv_evidence,
        )

    def _architecture_trace(self, results: Dict[str, Any]) -> List[str]:
        trace = []
        lang = results.get("source_language", "pascal_like_core_dsl")
        if lang == "ai_workflow_dsl":
            trace.append("AI DSL detected and lowered into the Pascal-like core compiler language.")
        else:
            trace.append("Core Pascal-like DSL compiled directly.")
        trace.append(f"Lexer produced {len(results.get('tokens', []) or [])} tokens.")
        trace.append("Parser produced an AST." if results.get("ast") else "Parser did not produce a valid AST.")
        trace.append(f"ICG produced {len(results.get('tac', []) or [])} Three-Address Code instructions.")
        trace.append(f"CodeGen produced {len(results.get('asm', []) or [])} pseudo-assembly instructions.")
        return trace

    def _explain_compiler_errors(self, results: Dict[str, Any]) -> List[AgentFinding]:
        findings: List[AgentFinding] = []
        groups = [
            ("Lexical analysis", results.get("lex_errors", []) or []),
            ("Parsing", results.get("parse_errors", []) or []),
            ("Semantic analysis", results.get("sem_errors", []) or []),
        ]
        for category, errors in groups:
            for error in errors:
                line = getattr(error, "line", None)
                message = getattr(error, "message", None) or str(error)
                suggestion = self._suggest_for_error(category, message)
                findings.append(
                    AgentFinding(
                        severity="error",
                        category=category,
                        message=message,
                        line=line,
                        suggestion=suggestion,
                    )
                )
        return findings

    def _suggest_for_error(self, category: str, message: str) -> str:
        lower = message.lower()
        if "unknown dataset" in lower:
            return "Declare the DATASET before TRAIN and use the same identifier spelling."
        if "unknown model" in lower:
            return "Declare the MODEL before EVALUATE, PREDICT, DEPLOY, or MONITOR."
        if "expected" in lower or category == "Parsing":
            return "Check statement order, missing semicolons in core DSL, quotes around strings, and ENDPIPELINE/end. termination."
        if "undeclared" in lower or category == "Semantic analysis":
            return "Declare variables before use or ensure the AI DSL lowering created the required symbol."
        if category == "Lexical analysis":
            return "Remove unsupported characters and verify identifiers, numbers, and string delimiters."
        return "Open the listing/error panel and fix the first reported error before later errors."

    def _inspect_core_program(self, source: str) -> List[AgentFinding]:
        findings: List[AgentFinding] = []
        if "program" not in source.lower():
            findings.append(
                AgentFinding(
                    severity="warning",
                    category="Core DSL structure",
                    message="Program header was not clearly detected.",
                    suggestion="Start core programs with: program Name;",
                )
            )
        if "begin" not in source.lower() or "end." not in source.lower():
            findings.append(
                AgentFinding(
                    severity="warning",
                    category="Core DSL structure",
                    message="Core program should include begin ... end. block.",
                    suggestion="Wrap executable statements inside begin and end.",
                )
            )
        return findings

    def _inspect_ai_workflow(self, source: str) -> Tuple[List[AgentFinding], List[str]]:
        findings: List[AgentFinding] = []
        datasets: Set[str] = set()
        models: Dict[str, Dict[str, Any]] = {}
        active = False
        seen_pipeline = False
        seen_end = False
        workflow_steps: List[str] = []

        for idx, raw in enumerate(source.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            matched = False
            for kind, pattern in AI_STATEMENT_PATTERNS.items():
                m = re.match(pattern, line, re.I)
                if not m:
                    continue
                matched = True

                if kind == "PIPELINE":
                    if seen_pipeline:
                        findings.append(AgentFinding("warning", "Workflow structure", "Multiple PIPELINE declarations detected.", idx, "Use one pipeline per source file for predictable compilation."))
                    seen_pipeline = True
                    active = True
                    workflow_steps.append(f"PIPELINE:{m.group(1)}")
                elif kind == "ENDPIPELINE":
                    seen_end = True
                    active = False
                    workflow_steps.append("ENDPIPELINE")
                elif not active:
                    findings.append(AgentFinding("error", "Workflow structure", "Statement appears outside PIPELINE ... ENDPIPELINE.", idx, "Move this statement inside the pipeline block."))
                elif kind == "DATASET":
                    datasets.add(m.group(1).lower())
                    workflow_steps.append(f"DATASET:{m.group(1)}")
                elif kind == "MODEL":
                    model_name = m.group(1).lower()
                    task = m.group(2).lower()
                    models[model_name] = {"trained": False, "evaluated": False, "deployed": False, "task": task}
                    workflow_steps.append(f"MODEL:{m.group(1)}")
                    if task not in {"classification", "regression"}:
                        findings.append(AgentFinding("warning", "Model task", f"Task '{task}' is not one of the runtime-supported tasks.", idx, "Use 'classification' or 'regression' for executable runtime behavior."))
                elif kind == "TRAIN":
                    model, dataset, epochs = m.group(1).lower(), m.group(2).lower(), int(m.group(3))
                    workflow_steps.append(f"TRAIN:{m.group(1)}->{m.group(2)}")
                    if model not in models:
                        findings.append(AgentFinding("error", "Training order", f"Model '{m.group(1)}' is trained before being declared.", idx, "Declare MODEL before TRAIN."))
                    else:
                        models[model]["trained"] = True
                    if dataset not in datasets:
                        findings.append(AgentFinding("error", "Dataset dependency", f"Dataset '{m.group(2)}' is used before being declared.", idx, "Declare DATASET before TRAIN."))
                    if epochs <= 0:
                        findings.append(AgentFinding("warning", "Training config", "Epoch count should be positive.", idx, "Use EPOCHS 1 or higher."))
                elif kind == "EVALUATE":
                    model = m.group(1).lower()
                    workflow_steps.append(f"EVALUATE:{m.group(1)}")
                    if model not in models:
                        findings.append(AgentFinding("error", "Evaluation order", f"Model '{m.group(1)}' is evaluated before being declared.", idx, "Declare MODEL before EVALUATE."))
                    elif not models[model]["trained"]:
                        findings.append(AgentFinding("warning", "Evaluation order", f"Model '{m.group(1)}' is evaluated before TRAIN.", idx, "Train the model before evaluation."))
                    else:
                        models[model]["evaluated"] = True
                elif kind == "PREDICT":
                    model = m.group(1).lower()
                    workflow_steps.append(f"PREDICT:{m.group(1)}")
                    if model not in models:
                        findings.append(AgentFinding("error", "Prediction order", f"Model '{m.group(1)}' is used for prediction before being declared.", idx, "Declare and train MODEL before PREDICT."))
                    elif not models[model]["trained"]:
                        findings.append(AgentFinding("warning", "Prediction order", f"Model '{m.group(1)}' is used for prediction before TRAIN.", idx, "Train the model before prediction."))
                elif kind == "DEPLOY":
                    model = m.group(1).lower()
                    workflow_steps.append(f"DEPLOY:{m.group(1)}")
                    if model not in models:
                        findings.append(AgentFinding("error", "Deployment order", f"Model '{m.group(1)}' is deployed before being declared.", idx, "Declare and train MODEL before DEPLOY."))
                    elif not models[model]["trained"]:
                        findings.append(AgentFinding("warning", "Deployment readiness", f"Model '{m.group(1)}' is deployed before TRAIN.", idx, "Train and evaluate before deployment."))
                    else:
                        models[model]["deployed"] = True
                elif kind == "MONITOR":
                    model = m.group(1).lower()
                    workflow_steps.append(f"MONITOR:{m.group(1)}")
                    if model not in models:
                        findings.append(AgentFinding("error", "Monitoring order", f"Model '{m.group(1)}' is monitored before being declared.", idx, "Declare MODEL before MONITOR."))
                    elif not models[model].get("deployed"):
                        findings.append(AgentFinding("warning", "Monitoring readiness", f"Model '{m.group(1)}' is monitored before DEPLOY.", idx, "Deploy the model before production monitoring."))
                elif kind == "LOG":
                    workflow_steps.append("LOG")
                elif kind == "SET":
                    workflow_steps.append(f"SET:{m.group(1)}")
                break

            if not matched:
                findings.append(
                    AgentFinding(
                        severity="error",
                        category="AI DSL syntax",
                        line=idx,
                        message="Statement does not match any supported AI DSL command.",
                        suggestion="Use DATASET, MODEL, SET, TRAIN, EVALUATE, PREDICT, DEPLOY, MONITOR, LOG, or ENDPIPELINE syntax.",
                    )
                )

        if not seen_pipeline:
            findings.append(AgentFinding("error", "Workflow structure", "Missing PIPELINE declaration.", None, "Start with: PIPELINE PipelineName"))
        if not seen_end:
            findings.append(AgentFinding("error", "Workflow structure", "Missing ENDPIPELINE terminator.", None, "End the file with ENDPIPELINE."))
        for model_name, info in models.items():
            if info.get("trained") and not info.get("evaluated"):
                findings.append(AgentFinding("info", "ML workflow quality", f"Model '{model_name}' is trained but not explicitly evaluated.", None, "Add EVALUATE before deployment for clearer validation."))
            if info.get("deployed") and not info.get("evaluated"):
                findings.append(AgentFinding("warning", "Deployment readiness", f"Model '{model_name}' is deployed without explicit EVALUATE.", None, "Evaluate the model before DEPLOY for production readiness."))

        graph = self._build_graph(workflow_steps)
        return findings, graph

    def _build_graph(self, steps: Iterable[str]) -> List[str]:
        clean = [s for s in steps if s]
        return [f"{a} -> {b}" for a, b in zip(clean, clean[1:])]

    def _score(self, results: Dict[str, Any], findings: List[AgentFinding], runtime_error: Optional[Dict[str, Any]]) -> Tuple[str, int]:
        score = 100
        if not results.get("success"):
            score -= 35
        if runtime_error:
            score -= 25
        for f in findings:
            if f.severity == "error":
                score -= 15
            elif f.severity == "warning":
                score -= 7
            elif f.severity == "info":
                score -= 2
        score = max(0, min(100, score))
        if score >= 85:
            return "production-ready", score
        if score >= 60:
            return "needs-review", score
        return "blocked", score

    def _suggested_fixes(self, findings: List[AgentFinding], source_language: str) -> List[str]:
        seen = set()
        fixes = []
        for f in findings:
            if f.suggestion and f.suggestion not in seen:
                fixes.append(f.suggestion)
                seen.add(f.suggestion)
        if not fixes and source_language == "ai_workflow_dsl":
            fixes.append("Workflow is structurally valid. Keep DATASET -> MODEL -> TRAIN -> EVALUATE -> DEPLOY -> MONITOR order for production clarity.")
        return fixes[:8]

    def _summary(self, status: str, source_language: str, results: Dict[str, Any], findings: List[AgentFinding]) -> str:
        errors = sum(1 for f in findings if f.severity == "error")
        warnings = sum(1 for f in findings if f.severity == "warning")
        lang = "AI Workflow DSL" if source_language == "ai_workflow_dsl" else "core Pascal-like DSL"
        if status == "production-ready":
            return f"The {lang} program compiled successfully and passed the agentic workflow checks with no blocking issues."
        if status == "needs-review":
            return f"The {lang} program is mostly valid, but the agent found {errors} error(s) and {warnings} warning(s) that should be reviewed."
        return f"The {lang} program is blocked by compiler, runtime, or workflow validation issues. The agent found {errors} error(s) and {warnings} warning(s)."

    def _cv_evidence(self, source_language: str) -> List[str]:
        if source_language == "ai_workflow_dsl":
            return [
                "AI DSL is detected, lowered, compiled, and executed through the original compiler backend.",
                "Agent validates ML workflow order, dependency use, deployment readiness, and debugging suggestions.",
                "Compiler artifacts include tokens, AST, TAC, pseudo-assembly, listing output, runtime output, and agent report.",
            ]
        return [
            "Agent layer reviews compiler artifacts without changing deterministic compiler behavior.",
            "Compiler artifacts include tokens, AST, TAC, pseudo-assembly, listing output, and diagnostic report.",
        ]
