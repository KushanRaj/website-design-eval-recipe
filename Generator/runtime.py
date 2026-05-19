from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .io import list_site_files
from .models import BuildReport

T = TypeVar("T", bound=BaseModel)


logger = logging.getLogger("Generator.runtime")


def _normalize_api_key_env() -> None:
    """The Claude Agent SDK / CLI authenticates via ANTHROPIC_API_KEY. Users
    here keep their key under CLAUDE_API_KEY, so bridge it once at import time."""

    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    bridge_keys = ("CLAUDE_API_KEY", "CLAUDE_CODE_API_KEY", "ANTHROPIC_KEY")
    for key in bridge_keys:
        value = os.environ.get(key)
        if value:
            os.environ["ANTHROPIC_API_KEY"] = value
            logger.info("ANTHROPIC_API_KEY not set; bridged from %s.", key)
            return


_normalize_api_key_env()


class AgentRuntimeError(RuntimeError):
    pass


def _truncate(value: Any, limit: int = 200) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + f"…(+{len(text) - limit} chars)"


def _claude_options(options_type: type, **kwargs):
    """Build ClaudeAgentOptions across minor SDK signature changes.

    Silently drops kwargs the installed SDK does not recognize and logs them
    so a stale option name is loud instead of invisible."""

    parameters = inspect.signature(options_type).parameters
    supported: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in kwargs.items():
        if key in parameters:
            supported[key] = value
        else:
            dropped.append(key)
    if dropped:
        logger.warning("ClaudeAgentOptions ignored kwargs not in installed SDK: %s", dropped)
    return options_type(**supported)


class AgentRuntime(Protocol):
    async def run_json(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
        image_paths: list[Path] | None = None,
    ) -> T: ...

    async def build_site(
        self,
        *,
        agent_name: str,
        site_id: str,
        system_prompt: str,
        user_prompt: str,
        site_dir: str | Path,
    ) -> BuildReport: ...


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


def _result_message_summary(message: Any) -> dict[str, Any]:
    """Compact dump of the SDK ResultMessage. Excludes the giant 'usage' dict
    so it can be appended at the end of the log line instead of poisoning the
    middle."""

    summary: dict[str, Any] = {}
    for field in (
        "subtype",
        "is_error",
        "duration_ms",
        "duration_api_ms",
        "num_turns",
        "total_cost_usd",
        "session_id",
        "error",
        "error_message",
    ):
        value = getattr(message, field, None)
        if value is not None:
            summary[field] = value
    return summary


def _heartbeat(agent_name: str, stage: str, started_at: float, site_dir: Path | None) -> str:
    elapsed = time.monotonic() - started_at
    extra = ""
    if site_dir is not None:
        try:
            files = list_site_files(site_dir)
            extra = f" files_on_disk={len(files)}"
        except Exception:
            pass
    return f"agent={agent_name} stage={stage} heartbeat elapsed={elapsed:.0f}s{extra}"


class _RunAccounting:
    """Process-wide running totals so end-of-run summaries are honest."""

    def __init__(self) -> None:
        self.total_cost_usd = 0.0
        self.total_calls = 0
        self.per_agent_cost: dict[str, float] = {}

    def record(self, agent_name: str, summary: dict[str, Any]) -> None:
        cost = float(summary.get("total_cost_usd") or 0.0)
        self.total_cost_usd += cost
        self.total_calls += 1
        self.per_agent_cost[agent_name] = self.per_agent_cost.get(agent_name, 0.0) + cost

    def snapshot(self) -> dict[str, Any]:
        return {
            "running_cost_usd": round(self.total_cost_usd, 4),
            "total_calls": self.total_calls,
            "per_agent_cost_usd": {k: round(v, 4) for k, v in self.per_agent_cost.items()},
        }


ACCOUNTING = _RunAccounting()


def _log_tool_use(agent_name: str, block: Any, turn_counter: list[int]) -> None:
    name = getattr(block, "name", None)
    if not name:
        return
    raw_input = getattr(block, "input", None)
    try:
        # truncate any large field values inside the dict so log lines stay sane
        if isinstance(raw_input, dict):
            preview = {
                k: _truncate(v, 160) if isinstance(v, str) else v
                for k, v in raw_input.items()
            }
        else:
            preview = _truncate(raw_input, 320) if raw_input is not None else None
    except Exception:
        preview = "<unrepr-able>"
    turn_counter[0] += 1
    logger.info(
        "agent=%s tool_use turn=%d name=%s input=%s",
        agent_name,
        turn_counter[0],
        name,
        preview,
    )


def _log_thinking(agent_name: str, block: Any) -> None:
    text = getattr(block, "thinking", None) or getattr(block, "text", None)
    if not text:
        return
    logger.info("agent=%s thinking=%s", agent_name, _truncate(text, 280))


def _is_thinking_block(block: Any) -> bool:
    cls = type(block).__name__
    return cls == "ThinkingBlock" or hasattr(block, "thinking")


def _is_tool_use_block(block: Any) -> bool:
    cls = type(block).__name__
    return cls == "ToolUseBlock" or (
        getattr(block, "name", None) is not None and getattr(block, "input", None) is not None
    )


async def _prompt_as_stream(prompt_text: str):
    """Wrap a single-string prompt as an AsyncIterable user message so the
    SDK's can_use_tool callback path is enabled (it refuses string prompts)."""

    yield {
        "type": "user",
        "message": {"role": "user", "content": prompt_text},
    }


def _encode_image_block(image_path: Path) -> dict[str, Any]:
    """Build an Anthropic-format image content block from a local PNG/JPEG."""

    import base64

    suffix = image_path.suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")
    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


async def _prompt_as_stream_with_images(prompt_text: str, image_paths: list[Path]):
    """Wrap a string prompt + list of image paths as an AsyncIterable user
    message. The text comes first, then one image block per path (so the
    model sees the question, then the visual evidence)."""

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    for image_path in image_paths:
        try:
            content.append(_encode_image_block(image_path))
        except OSError as exc:
            logger.warning("could not encode image %s: %s", image_path, exc)
    yield {
        "type": "user",
        "message": {"role": "user", "content": content},
    }


def _make_cwd_path_guard(cwd: Path, agent_name: str):
    """Build a can_use_tool callback that enforces every file-writing tool
    target a path *inside* the agent's cwd.

    Closes two specific holes:

    1. Hallucinated absolute paths like ``/Users/.../code/fleet/site/index.html``
       or ``/root/site/...``. The Write tool would otherwise happily create
       the directory and write there, outside our managed site dir.
    2. Relative-traversal escapes like ``../outside.html`` or
       ``../../somewhere/file.html``. These look harmless (not absolute) but
       resolve outside cwd just the same.

    Every candidate (relative or absolute) is resolved as ``(cwd / candidate).resolve()``
    and required to be ``relative_to(cwd.resolve())``. Anything that doesn't fit
    gets a corrective DENY message back to the model.
    """

    cwd_resolved = cwd.resolve()
    file_writing_tools = {"Write", "Edit", "MultiEdit"}

    async def hook(tool_name: str, tool_input: dict[str, Any], _ctx: Any):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        if tool_name not in file_writing_tools:
            return PermissionResultAllow()

        candidate = tool_input.get("file_path")
        if not isinstance(candidate, str) or not candidate:
            return PermissionResultAllow()

        candidate_path = Path(candidate)
        if candidate_path.is_absolute():
            resolved = candidate_path.resolve()
        else:
            resolved = (cwd_resolved / candidate_path).resolve()

        try:
            relative = resolved.relative_to(cwd_resolved)
        except ValueError:
            message = (
                f"file_path must resolve inside the site directory. "
                f"You wrote {candidate!r}, which would resolve to {str(resolved)!r} — "
                f"outside your working directory. "
                f"Use a relative path like 'index.html' or 'css/style.css' instead. "
                f"Never use absolute paths starting with '/' and never use '..' to "
                f"escape upwards."
            )
            logger.warning(
                "agent=%s path_guard DENIED tool=%s path=%s resolved=%s",
                agent_name,
                tool_name,
                candidate,
                resolved,
            )
            return PermissionResultDeny(message=message)

        # In-cwd — rewrite to the canonical relative form so downstream
        # tooling sees consistent paths regardless of how the model wrote it.
        canonical = str(relative)
        if canonical != candidate:
            logger.info(
                "agent=%s path_guard rewrote tool=%s from=%s to=%s",
                agent_name,
                tool_name,
                candidate,
                canonical,
            )
            updated = dict(tool_input)
            updated["file_path"] = canonical
            return PermissionResultAllow(updated_input=updated)
        return PermissionResultAllow()

    return hook


class _Heartbeat:
    """Periodic 'still alive, here's what's on disk' log emitter so a long
    silent stage is visibly making progress (or visibly not)."""

    def __init__(
        self,
        *,
        agent_name: str,
        stage: str,
        site_dir: Path | None = None,
        interval_seconds: float = 30.0,
    ) -> None:
        self._agent_name = agent_name
        self._stage = stage
        self._site_dir = site_dir
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._started_at = 0.0

    async def __aenter__(self) -> "_Heartbeat":
        self._started_at = time.monotonic()
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                logger.info(_heartbeat(self._agent_name, self._stage, self._started_at, self._site_dir))
        except asyncio.CancelledError:
            return


class ClaudeAgentRuntime:
    """Claude Agent SDK runtime with Pydantic validation at the boundary."""

    def __init__(
        self,
        *,
        model: str | None = None,
        cwd: str | Path | None = None,
        max_turns: int = 1,
        max_budget_usd: float | None = None,
        run_json_min_turns: int = 10,
        build_site_min_turns: int = 100,
        heartbeat_seconds: float = 30.0,
    ) -> None:
        self.model = model or os.getenv("GENERATOR_CLAUDE_MODEL") or "sonnet"
        self.cwd = Path(cwd) if cwd is not None else None
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.run_json_min_turns = run_json_min_turns
        self.build_site_min_turns = build_site_min_turns
        self.heartbeat_seconds = heartbeat_seconds

    async def run_json(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
        image_paths: list[Path] | None = None,
    ) -> T:
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                TextBlock,
                query,
            )
        except Exception as exc:  # pragma: no cover - exercised only without SDK installed
            raise AgentRuntimeError(
                "claude-agent-sdk is required for ClaudeAgentRuntime. "
                "Install it or run with --dry-run."
            ) from exc

        schema = output_model.model_json_schema()
        options_params = inspect.signature(ClaudeAgentOptions).parameters
        supports_output_format = "output_format" in options_params
        if supports_output_format:
            prompt = (
                f"{user_prompt}\n\nReturn structured data matching the configured JSON schema. "
                "Do not include markdown or commentary."
            )
        else:
            prompt = (
                f"{user_prompt}\n\nReturn exactly one JSON object that validates this JSON "
                "Schema. Do not include markdown, commentary, or extra keys.\n\n"
                f"Schema:\n{json.dumps(schema, indent=2, sort_keys=True)}"
            )

        max_turns = max(self.max_turns, self.run_json_min_turns)
        options = _claude_options(
            ClaudeAgentOptions,
            system_prompt=f"{system_prompt}\n\nAgent name: {agent_name}",
            model=self.model,
            cwd=self.cwd,
            max_turns=max_turns,
            max_budget_usd=self.max_budget_usd,
            permission_mode="bypassPermissions",
            setting_sources=[],
            output_format={"type": "json_schema", "schema": schema} if supports_output_format else None,
        )

        # If image_paths is supplied, we must use the streaming-prompt form so
        # the SDK can deliver a structured user message with image content
        # blocks. The SDK only accepts the streaming form for can_use_tool,
        # but for image attachments we also need the streaming form to mix
        # text + image content.
        usable_images = [p for p in (image_paths or []) if p and p.exists()]
        if usable_images:
            prompt_arg: Any = _prompt_as_stream_with_images(prompt, usable_images)
        else:
            prompt_arg = prompt

        logger.info(
            "agent=%s stage=run_json START model=%s max_turns=%s output_model=%s output_format=%s images=%d",
            agent_name,
            self.model,
            max_turns,
            output_model.__name__,
            supports_output_format,
            len(usable_images),
        )

        chunks: list[str] = []
        structured_payload: Any = None
        last_result_summary: dict[str, Any] = {}
        last_usage: Any = None
        turn_counter = [0]

        async with _Heartbeat(
            agent_name=agent_name, stage="run_json", interval_seconds=self.heartbeat_seconds
        ):
            try:
                async for message in query(prompt=prompt_arg, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                chunks.append(block.text)
                            elif _is_thinking_block(block):
                                _log_thinking(agent_name, block)
                            elif _is_tool_use_block(block):
                                _log_tool_use(agent_name, block, turn_counter)
                            elif hasattr(block, "text"):
                                chunks.append(str(block.text))
                    elif isinstance(message, ResultMessage):
                        last_result_summary = _result_message_summary(message)
                        last_usage = getattr(message, "usage", None)
                        if getattr(message, "structured_output", None) is not None:
                            structured_payload = message.structured_output
                        if getattr(message, "result", None):
                            chunks.append(message.result)
            except Exception as exc:
                raise AgentRuntimeError(
                    f"{agent_name} run_json transport failure: {type(exc).__name__}: {exc}"
                ) from exc

        raw = "\n".join(chunks).strip()
        ACCOUNTING.record(agent_name, last_result_summary)
        logger.info(
            "agent=%s stage=run_json END result=%s text_chars=%d structured=%s tool_uses=%d %s usage=%s",
            agent_name,
            last_result_summary or "<no ResultMessage>",
            len(raw),
            "yes" if structured_payload is not None else "no",
            turn_counter[0],
            f"running_cost=${ACCOUNTING.total_cost_usd:.2f}",
            _truncate(last_usage, 320) if last_usage is not None else "<none>",
        )

        subtype = last_result_summary.get("subtype")
        is_error = last_result_summary.get("is_error")
        if subtype and subtype not in {"success", None}:
            raise AgentRuntimeError(
                f"{agent_name} run_json finished with subtype={subtype!r}; "
                f"result_summary={last_result_summary}; "
                f"raw response (truncated 4kb):\n{raw[:4096]}"
            )
        if is_error:
            raise AgentRuntimeError(
                f"{agent_name} run_json finished with is_error=True; "
                f"result_summary={last_result_summary}; "
                f"raw response (truncated 4kb):\n{raw[:4096]}"
            )

        try:
            if structured_payload is not None:
                logger.info("agent=%s validating structured_payload (SDK schema flow)", agent_name)
                return output_model.model_validate(structured_payload)
            logger.info("agent=%s validating text-fallback JSON (no structured_output)", agent_name)
            return output_model.model_validate_json(extract_json_payload(raw))
        except (ValidationError, ValueError, AgentRuntimeError) as exc:
            raise AgentRuntimeError(
                f"{agent_name} returned invalid {output_model.__name__}: {exc}\n"
                f"result_summary={last_result_summary}\n"
                f"raw response (truncated 8kb):\n{raw[:8192]}"
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
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                TextBlock,
                query,
            )
        except Exception as exc:  # pragma: no cover - exercised only without SDK installed
            raise AgentRuntimeError(
                "claude-agent-sdk is required for ClaudeAgentRuntime. "
                "Install it or run with --dry-run."
            ) from exc

        root = Path(site_dir)
        root.mkdir(parents=True, exist_ok=True)
        prompt = (
            f"{user_prompt}\n\nYou are currently operating inside the site root. "
            "Write files directly here. Do not write outside this directory. "
            "When finished, reply with a concise summary and the list of files you wrote."
        )

        # Fail closed: if the installed SDK doesn't recognize can_use_tool we
        # must NOT silently fall back to running the builder unguarded.
        options_params = inspect.signature(ClaudeAgentOptions).parameters
        if "can_use_tool" not in options_params:
            raise AgentRuntimeError(
                "Installed claude-agent-sdk does not support can_use_tool; "
                "refusing to start builder without path guard. "
                "Upgrade the SDK or wrap the agent in OS-level sandboxing first."
            )

        max_turns = max(self.max_turns, self.build_site_min_turns)
        # Bash is included for recon ergonomics. The path guard only polices
        # Write/Edit/MultiEdit, so technically the model could shell-redirect
        # to write outside cwd (`echo ... > ../foo.html`). We accept that
        # residual risk for v1 because the path guard already catches the
        # observed failure mode (hallucinated absolute paths in Write),
        # and removing Bash forced the model into 9× more tool calls per
        # recon step. For production, layer a Bash command allowlist or the
        # SDK's Bash sandbox on top.
        builder_tools = [
            "Write",
            "Edit",
            "MultiEdit",
            "Read",
            "LS",
            "Glob",
            "Grep",
            "Bash",
        ]
        # NOTE: permission_mode is "default" (not bypassPermissions) so the
        # SDK invokes our can_use_tool callback. With bypassPermissions the
        # callback is skipped and the agent runs unguarded.
        options = _claude_options(
            ClaudeAgentOptions,
            system_prompt=f"{system_prompt}\n\nAgent name: {agent_name}",
            model=self.model,
            cwd=root,
            max_turns=max_turns,
            max_budget_usd=self.max_budget_usd,
            allowed_tools=builder_tools,
            permission_mode="default",
            can_use_tool=_make_cwd_path_guard(root, agent_name),
            setting_sources=[],
        )

        logger.info(
            "agent=%s stage=build_site START model=%s max_turns=%s site_dir=%s",
            agent_name,
            self.model,
            max_turns,
            root,
        )

        chunks: list[str] = []
        last_result_summary: dict[str, Any] = {}
        last_usage: Any = None
        turn_counter = [0]

        async with _Heartbeat(
            agent_name=agent_name,
            stage="build_site",
            site_dir=root,
            interval_seconds=self.heartbeat_seconds,
        ):
            try:
                async for message in query(prompt=_prompt_as_stream(prompt), options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                chunks.append(block.text)
                            elif _is_thinking_block(block):
                                _log_thinking(agent_name, block)
                            elif _is_tool_use_block(block):
                                _log_tool_use(agent_name, block, turn_counter)
                            elif hasattr(block, "text"):
                                chunks.append(str(block.text))
                    elif isinstance(message, ResultMessage):
                        last_result_summary = _result_message_summary(message)
                        last_usage = getattr(message, "usage", None)
                        if getattr(message, "result", None):
                            chunks.append(message.result)
            except Exception as exc:
                raise AgentRuntimeError(
                    f"{agent_name} build_site transport failure: {type(exc).__name__}: {exc}"
                ) from exc

        files = list_site_files(root)
        ACCOUNTING.record(agent_name, last_result_summary)
        logger.info(
            "agent=%s stage=build_site END result=%s tool_uses=%d files_written=%d %s usage=%s",
            agent_name,
            last_result_summary or "<no ResultMessage>",
            turn_counter[0],
            len(files),
            f"running_cost=${ACCOUNTING.total_cost_usd:.2f}",
            _truncate(last_usage, 320) if last_usage is not None else "<none>",
        )

        subtype = last_result_summary.get("subtype")
        is_error = last_result_summary.get("is_error")
        if subtype and subtype not in {"success", None}:
            raise AgentRuntimeError(
                f"{agent_name} build_site finished with subtype={subtype!r}; "
                f"result_summary={last_result_summary}; files_written={files}"
            )
        if is_error:
            raise AgentRuntimeError(
                f"{agent_name} build_site finished with is_error=True; "
                f"result_summary={last_result_summary}; files_written={files}"
            )
        if not files:
            raise AgentRuntimeError(
                f"{agent_name} did not write any files into {root} "
                f"(tool_uses={turn_counter[0]}, num_turns={last_result_summary.get('num_turns')}); "
                f"result_summary={last_result_summary}"
            )
        return BuildReport(
            site_id=site_id,
            site_dir=str(root),
            files_written=files,
            summary="\n".join(chunks).strip(),
        )
