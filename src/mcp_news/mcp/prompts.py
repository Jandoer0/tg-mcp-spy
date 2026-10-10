"""MCP-промпты и автодополнение имён подписок (для агентов)."""
from __future__ import annotations

from mcp.server.mcpserver.prompts import base
from mcp.types import (
    Completion,
    CompletionArgument,
    EmbeddedResource,
    PromptReference,
    ResourceTemplateReference,
    TextResourceContents,
)

from ..db import get_source, list_sources

from .resources import channels_resource
from .server import mcp


@mcp.prompt()
def digest(days: int = 7, channels: str | None = None):
    """Составить дайджест постов за последние N дней по подпискам"""
    instruction = (
        f"посмотри в методе query_posts(days={days}) посты "
        f"и составь дайджест по подпискам. "
        f"по каждой 2-3 предложения на главные темы. "
        f"Если подписок нет - сообщи об этом пользователю. "
        f"Если темы пересекаются - покажи один раз."
    )
    if channels is None:
        return [
            base.UserMessage(
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri="tg://channels",
                        text=channels_resource(),
                        mimeType="text/plain",
                    ),
                )
            ),
            base.UserMessage(instruction),
        ]
    return [base.UserMessage(f"Подписки: {channels}\n\n{instruction}")]


@mcp.completion()
async def complete_source_name(ref, argument: CompletionArgument, context) -> Completion | None:
    names = [s["name"] for s in list_sources()]
    if isinstance(ref, (ResourceTemplateReference, PromptReference)):
        return Completion(
            values=[n for n in names if n.lower().startswith(argument.value.lower())]
        )
    return None
