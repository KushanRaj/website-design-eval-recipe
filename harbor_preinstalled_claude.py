from __future__ import annotations

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment


class PreinstalledClaudeCode(ClaudeCode):
    """Claude Code Harbor agent for images where Claude is already installed."""

    @staticmethod
    def name() -> str:
        return "preinstalled-claude-code"

    async def install(self, environment: BaseEnvironment) -> None:
        await self.exec_as_agent(
            environment,
            command=(
                'export PATH="$HOME/.local/bin:/root/.local/bin:/usr/local/bin:$PATH"; '
                'command -v claude >/dev/null 2>&1 || '
                '(echo "Claude Code is not installed in this agent image." >&2; exit 127); '
                "claude --version"
            ),
        )
