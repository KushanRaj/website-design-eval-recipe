from __future__ import annotations

import os
import json
import re
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .io import list_site_files
from .models import BuildReport

T = TypeVar("T", bound=BaseModel)


class AgentRuntimeError(RuntimeError):
    pass


class AgentRuntime(Protocol):
    async def run_json(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> T:
        ...

    async def build_site(
        self,
        *,
        agent_name: str,
        site_id: str,
        system_prompt: str,
        user_prompt: str,
        site_dir: str | Path,
    ) -> BuildReport:
        ...


def extract_json_payload(text: str) -> str:
    """Extract a JSON object from a model response."""

    stripped = text.strip()
    if not stripped:
        raise AgentRuntimeError("empty model response")

    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    if start < 0:
        raise AgentRuntimeError("model response did not contain a JSON object")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]

    raise AgentRuntimeError("unterminated JSON object in model response")


class ClaudeAgentRuntime:
    """Claude Agent SDK runtime with Pydantic validation at the boundary."""

    def __init__(
        self,
        *,
        model: str | None = None,
        cwd: str | Path | None = None,
        max_turns: int = 1,
        max_budget_usd: float | None = None,
    ) -> None:
        self.model = model or os.getenv("GENERATOR_CLAUDE_MODEL") or "sonnet"
        self.cwd = Path(cwd) if cwd is not None else None
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd

    async def run_json(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
    ) -> T:
        try:
            from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query
        except Exception as exc:  # pragma: no cover - exercised only without SDK installed
            raise AgentRuntimeError(
                "claude-agent-sdk is required for ClaudeAgentRuntime. "
                "Install it or run with the fake runtime."
            ) from exc

        schema = output_model.model_json_schema()
        prompt = f"""{user_prompt}

Return exactly one JSON object that validates this JSON Schema. Do not include
markdown, commentary, or extra keys.

Schema:
{json.dumps(schema, indent=2, sort_keys=True)}
"""
        options = ClaudeAgentOptions(
            system_prompt=f"{system_prompt}\n\nAgent name: {agent_name}",
            model=self.model,
            cwd=self.cwd,
            max_turns=self.max_turns,
            max_budget_usd=self.max_budget_usd,
            allowed_tools=[],
            permission_mode="default",
        )

        chunks: list[str] = []
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
                    elif hasattr(block, "text"):
                        chunks.append(str(block.text))
            elif isinstance(message, ResultMessage) and message.result:
                chunks.append(message.result)

        raw = "\n".join(chunks).strip()
        try:
            return output_model.model_validate_json(extract_json_payload(raw))
        except (ValidationError, ValueError, AgentRuntimeError) as exc:
            raise AgentRuntimeError(
                f"{agent_name} returned invalid {output_model.__name__}: {exc}\nRaw response:\n{raw}"
            ) from exc

    async def build_site(
        self,
        *,
        agent_name: str,
        site_id: str,
        system_prompt: str,
        user_prompt: str,
        site_dir: str | Path,
    ) -> BuildReport:
        try:
            from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query
        except Exception as exc:  # pragma: no cover - exercised only without SDK installed
            raise AgentRuntimeError(
                "claude-agent-sdk is required for ClaudeAgentRuntime. "
                "Install it or run with the fake runtime."
            ) from exc

        root = Path(site_dir)
        root.mkdir(parents=True, exist_ok=True)
        prompt = f"""{user_prompt}

You are currently operating inside the site root. Write files directly here.
Do not write outside this directory. When finished, reply with a concise summary
and the list of files you wrote.
"""
        options = ClaudeAgentOptions(
            system_prompt=f"{system_prompt}\n\nAgent name: {agent_name}",
            model=self.model,
            cwd=root,
            max_turns=max(self.max_turns, 20),
            max_budget_usd=self.max_budget_usd,
            allowed_tools=["Write", "Edit", "MultiEdit", "Read", "LS"],
            permission_mode="acceptEdits",
        )
        chunks: list[str] = []
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
                    elif hasattr(block, "text"):
                        chunks.append(str(block.text))
            elif isinstance(message, ResultMessage) and message.result:
                chunks.append(message.result)
        files = list_site_files(root)
        if not files:
            raise AgentRuntimeError(f"{agent_name} did not write any files into {root}")
        return BuildReport(
            site_id=site_id,
            site_dir=str(root),
            files_written=files,
            summary="\n".join(chunks).strip(),
        )
