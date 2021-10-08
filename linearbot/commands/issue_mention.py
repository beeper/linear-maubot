import asyncio
import json
import re
from datetime import datetime, timedelta

import attr
from linearbot.util.template import TemplateManager
from typing import Dict, Iterable, List, Optional, NamedTuple, Tuple
from uuid import UUID, uuid4

from mautrix.types import EventType, EventID, RoomID, ReactionEvent, RelationType
from maubot.handlers import event
from maubot import MessageEvent

from ..api import LinearClient
from ..api.types import IssueSummary, LinearEventType
from .base import Command, with_client


class CommandIssueMention(Command):
    templates: TemplateManager

    def __init__(self, bot: "LinearBot") -> None:
        super().__init__(bot)
        self._issue_cache: Dict[str, Tuple[IssueSummary, datetime]] = {}
        self.templates = TemplateManager(self.bot.loader, "templates/messages")

    issue_mention_re = re.compile(r"[A-Z]+-\d+")

    async def format_issue_summaries(self, issues: Iterable[IssueSummary]) -> str:
        template = self.templates["issue_summary"]

        formatted_issues = []
        for issue in issues:
            args = {
                "identifier": issue.identifier,
                "title": issue.title,
                "url": issue.url,
                "description": issue.description or "",
                "details": [
                    issue.priority_label or "",
                    (
                        f"""<span data-mx-color="{issue.state.color}">{issue.state.name}</span>"""
                        if issue.state
                        else ""
                    ),
                    f"👤 {issue.assignee.display_name}" if issue.assignee else "",
                    f"▶️ {issue.cycle.number}" if issue.cycle else "",
                    f"▲ {issue.estimate}" if issue.estimate else "",
                    f"▦ {issue.project.name}" if issue.project else "",
                ],
            }
            formatted_issues.append(await template.render_async(**args))

        return "<br>".join(formatted_issues)

    async def get_issue_details(
        self, client: LinearClient, issue_identifier: str
    ) -> Optional[IssueSummary]:
        cached = self._issue_cache.get(issue_identifier)
        if cached:
            self.bot.log.info(f"Got cached issue summary for {issue_identifier}")
            summary, expiration = cached
            if summary and expiration < datetime.now():
                return summary

        self.bot.log.info(f"Getting summary for {issue_identifier}")
        try:
            summary = await client.get_issue_details(issue_identifier)
            self._issue_cache[issue_identifier] = (
                summary,
                datetime.now() + timedelta(hours=12),
            )
            return summary
        except Exception:
            return None

    @event.on(EventType.ROOM_MESSAGE)
    @with_client(error_message=False)
    async def on_issue_mention(self, evt: MessageEvent, client: LinearClient) -> None:
        if evt.sender == self.bot.client.mxid:
            return

        issue_details = await asyncio.gather(
            *(
                self.get_issue_details(client, issue_identifier)
                for issue_identifier in self.issue_mention_re.findall(evt.content.body)
            )
        )

        await evt.reply(
            await self.format_issue_summaries((i for i in issue_details if i)),
            allow_html=True,
        )
