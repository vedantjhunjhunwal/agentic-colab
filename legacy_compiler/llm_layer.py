"""
Optional LLM review layer for the AI Workflow DSL Compiler.

This file is intentionally optional. The compiler and deterministic agent run
without LangChain, OpenAI, Gemini, or API keys. When an LLM provider is installed
and configured, this layer adds a higher-level natural-language review on top of
compiler artifacts without modifying lexer/parser/ICG/codegen behavior.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class LLMReview:
    enabled: bool
    provider: str
    model: str
    status: str
    summary: str
    recommendations: List[str]
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_text(self) -> str:
        lines = [
            f"LLM Enabled: {self.enabled}",
            f"Provider: {self.provider}",
            f"Model: {self.model}",
            f"Status: {self.status}",
            "",
            "LLM Summary:",
            f"  {self.summary}",
            "",
            "LLM Recommendations:",
        ]
        if self.recommendations:
            lines.extend(f"  - {item}" for item in self.recommendations)
        else:
            lines.append("  - No LLM recommendations generated.")
        return "\n".join(lines)


class OptionalLLMReviewer:
    """Provider adapter for optional LLM reasoning.

    Supported environment variables:
      - AI_COMPILER_LLM_PROVIDER=openai|gemini|none
      - AI_COMPILER_LLM_MODEL=<provider model name>
      - OPENAI_API_KEY for OpenAI via langchain-openai
      - GOOGLE_API_KEY for Gemini via langchain-google-genai
    """

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = (provider or os.getenv("AI_COMPILER_LLM_PROVIDER") or "none").lower()
        self.model = model or os.getenv("AI_COMPILER_LLM_MODEL") or self._default_model(self.provider)

    def review(self, source: str, compile_results: Dict[str, Any], deterministic_report: Dict[str, Any]) -> LLMReview:
        if self.provider in {"", "none", "off", "disabled"}:
            return self._disabled("LLM layer is disabled. Set AI_COMPILER_LLM_PROVIDER=openai or gemini to enable it.")

        prompt = self._build_prompt(source, compile_results, deterministic_report)

        try:
            if self.provider == "openai":
                return self._review_openai(prompt)
            if self.provider in {"gemini", "google"}:
                return self._review_gemini(prompt)
            return self._disabled(f"Unsupported provider '{self.provider}'. Use openai, gemini, or none.")
        except Exception as exc:
            return LLMReview(
                enabled=False,
                provider=self.provider,
                model=self.model,
                status="fallback",
                summary=f"LLM review could not run: {exc}",
                recommendations=[
                    "The deterministic compiler agent report is still available.",
                    "Install optional LLM dependencies and set the required API key to enable this layer.",
                ],
                raw="",
            )

    def _default_model(self, provider: str) -> str:
        if provider == "openai":
            return "gpt-4o-mini"
        if provider in {"gemini", "google"}:
            return "gemini-1.5-flash"
        return "none"

    def _disabled(self, reason: str) -> LLMReview:
        return LLMReview(
            enabled=False,
            provider=self.provider,
            model=self.model,
            status="disabled",
            summary=reason,
            recommendations=[],
            raw="",
        )

    def _build_prompt(self, source: str, compile_results: Dict[str, Any], deterministic_report: Dict[str, Any]) -> str:
        compact = {
            "source_language": compile_results.get("source_language"),
            "success": compile_results.get("success"),
            "token_count": len(compile_results.get("tokens", []) or []),
            "tac_count": len(compile_results.get("tac", []) or []),
            "asm_count": len(compile_results.get("asm", []) or []),
            "deterministic_agent_status": deterministic_report.get("status"),
            "deterministic_agent_score": deterministic_report.get("validation_score"),
            "findings": deterministic_report.get("findings", [])[:10],
            "workflow_graph": deterministic_report.get("workflow_graph", [])[:20],
            "source_preview": source[:4000],
        }
        return (
            "You are a senior AI agent compiler reviewer. Review this AI Workflow DSL compiler run. "
            "Do not change the compiler logic. Return concise JSON with keys: summary, recommendations. "
            "recommendations must be a list of practical engineering actions.\n\n"
            + json.dumps(compact, indent=2, default=str)
        )

    def _parse_response(self, text: str) -> LLMReview:
        summary = text.strip()
        recommendations: List[str] = []
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
            data = json.loads(cleaned)
            summary = str(data.get("summary", summary))
            recommendations = [str(x) for x in data.get("recommendations", [])]
        except Exception:
            recommendations = ["Use the LLM text review as advisory guidance only; deterministic compiler results remain source of truth."]
        return LLMReview(
            enabled=True,
            provider=self.provider,
            model=self.model,
            status="completed",
            summary=summary,
            recommendations=recommendations[:8],
            raw=text,
        )

    def _review_openai(self, prompt: str) -> LLMReview:
        if not os.getenv("OPENAI_API_KEY"):
            return self._disabled("OPENAI_API_KEY is not set, so OpenAI review is skipped.")
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ImportError("Install optional dependencies: pip install -r requirements-agent.txt") from exc
        llm = ChatOpenAI(model=self.model, temperature=0)
        response = llm.invoke(prompt)
        return self._parse_response(getattr(response, "content", str(response)))

    def _review_gemini(self, prompt: str) -> LLMReview:
        if not os.getenv("GOOGLE_API_KEY"):
            return self._disabled("GOOGLE_API_KEY is not set, so Gemini review is skipped.")
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise ImportError("Install optional dependencies: pip install -r requirements-agent.txt") from exc
        llm = ChatGoogleGenerativeAI(model=self.model, temperature=0)
        response = llm.invoke(prompt)
        return self._parse_response(getattr(response, "content", str(response)))
