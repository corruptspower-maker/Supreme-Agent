"""Reasoner: generates plans from user requests using LM Studio."""

from __future__ import annotations

from typing import Optional

from loguru import logger

from src.core.models import Plan, PlanStep, UserRequest
from src.utils.lm_studio_client import LMStudioClient
from src.utils.tokens import truncate_to_budget

_SYSTEM_PROMPT_TEMPLATE = """You are an executive agent planner. Given a user request and context,
you MUST call only one tool named run_agent and must not call any other tool directly.
Available tools: run_agent

Respond ONLY with valid JSON in this exact format:
{{Ha I'm a coder
  "reasoning": "why delegating to run_agent is appropriate",
  "confidence": 0.85,
  "steps": [
    {{"description": "delegate to supreme agent", "tool_name": "run_agent", "tool_args": {{"goal": "<user goal>"}}, "depends_on": []}}
  ]
}}"""

_FALLBACK_TOOLS = "run_agent"


def _get_tool_list() -> str:
    """Build tool list dynamically from the registry, with fallback."""
    try:
        from src.tools.registry import ToolRegistry
        registry = ToolRegistry()
        registry.autodiscover()
        names = sorted(t.name for t in registry.list_tools() if t.name)
        if names:
            return ", ".join(names)
    except Exception:
        pass
main
    return _FALLBACK_TOOLS


class Reasoner:
    """Generates execution plans using the local LLM."""

    def __init__(self, client: LMStudioClient) -> None:
        self._client = client

    async def plan(
        self,
        request: UserRequest,
        memory_context: str = "",
        conversation_history: Optional[list[dict]] = None,
        last_feedback: Optional[dict] = None,
    ) -> Plan:
        """Generate an execution plan for the given request."""
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(tool_list=_get_tool_list())
        messages = [{"role": "system", "content": system_prompt}]

        if memory_context:
            messages.append({
                "role": "system",
                "content": f"Relevant memory:\n{truncate_to_budget(memory_context, 2000)}",
            })

        if last_feedback:
            decision = last_feedback.get("decision", "")
            constraints = last_feedback.get("constraints", [])
            strategy = last_feedback.get("strategy", "")
            hint_parts = [f"Previous attempt outcome: decision={decision}"]
            if strategy:
                hint_parts.append(f"failed strategy: {strategy}")
            if constraints:
                hint_parts.append(f"avoid tools: {', '.join(constraints)}")
            messages.append({
                "role": "system",
                "content": " — ".join(hint_parts) + ". Do NOT repeat the failed strategy.",
            })

        if conversation_history:
            messages.extend(conversation_history[-10:])  # Last 10 exchanges

        messages.append({"role": "user", "content": request.text})

        try:
            data = await self._client.complete_json(messages, temperature=0.3)
            steps = [
                PlanStep(
                    description=s.get("description", ""),
                    tool_name=s.get("tool_name"),
                    tool_args=s.get("tool_args", {}),
                    depends_on=s.get("depends_on", []),
                )
                for s in data.get("steps", [])
            ]
            return Plan(
                task_id=request.id,
                steps=steps,
                reasoning=data.get("reasoning", ""),
                confidence=float(data.get("confidence", 0.5)),
            )
        except RuntimeError as e:
            logger.error(f"Reasoner failed to generate plan: {e}")
            return Plan(
                task_id=request.id,
                steps=[PlanStep(
                    description="Unable to plan — local model unavailable",
                    tool_name=None,
                    error=str(e),
                )],
                reasoning=f"Planning failed: {e}",
                confidence=0.0,
            )
