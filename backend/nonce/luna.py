"""Luna agents (OpenAI Agents SDK): client setup, model fallback and the time limit, shared by recall and tasks."""

import asyncio
import logging
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

_model: str | None = None
_setup_done = False


def configured() -> bool:
    s = settings()
    return bool(s.openai_api_key or (s.azure_openai_api_key and s.azure_openai_endpoint))


def _setup() -> None:
    from agents import set_default_openai_api, set_default_openai_client, set_default_openai_key, set_tracing_disabled
    from openai import AsyncOpenAI

    s = settings()
    set_tracing_disabled(True)
    if s.azure_openai_api_key and s.azure_openai_endpoint:
        set_default_openai_client(AsyncOpenAI(api_key=s.azure_openai_api_key, base_url=f"{s.azure_openai_endpoint.rstrip('/')}/openai/v1"))
    else:
        set_default_openai_key(s.openai_api_key or "")
    set_default_openai_api("responses")


def _model_missing(e: Exception) -> bool:
    status, code = getattr(e, "status_code", None), getattr(e, "code", None)
    return status == 404 or code in ("model_not_found", "DeploymentNotFound")


async def _run(name: str, instructions: str, task: str, output_type: type, tools: list, max_turns: int) -> Any:
    from agents import Agent, ModelSettings, Runner
    from openai.types.shared import Reasoning

    global _model, _setup_done
    s = settings()
    if not _setup_done:
        _setup()
        _setup_done = True
    _model = _model or s.luna_model
    while True:
        agent = Agent(
            name=name,
            instructions=instructions,
            model=_model,
            model_settings=ModelSettings(reasoning=Reasoning(effort=s.luna_effort), parallel_tool_calls=True),
            tools=tools,
            output_type=output_type,
        )
        try:
            return (await Runner.run(agent, task, max_turns=max_turns)).final_output
        except Exception as e:
            if _model != s.luna_fallback_model and _model_missing(e):
                log.warning("[luna] %s unavailable here; using %s", _model, s.luna_fallback_model)
                _model = s.luna_fallback_model
                continue
            raise


async def run(name: str, instructions: str, task: str, output_type: type, tools: list | None = None, max_turns: int = 1) -> Any:
    """The agent's structured output. Raises on failure or past `luna_timeout_s`; callers fall back."""
    return await asyncio.wait_for(_run(name, instructions, task, output_type, tools or [], max_turns), timeout=settings().luna_timeout_s)
