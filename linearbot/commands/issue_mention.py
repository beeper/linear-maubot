import asyncio
import re
from datetime import datetime, timedelta

from mautrix.types.event.message import Format, MessageType, TextMessageEventContent
from linearbot.util.template import TemplateManager
from typing import Dict, Iterable, Optional, Tuple

from mautrix.types import EventType, EventID
from maubot.handlers import event
from maubot import MessageEvent

from ..api import LinearClient
from ..api.types import IssueSummary
from .base import Command


class CommandIssueMention(Command):
    templates: TemplateManager

    def __init__(self, bot: "LinearBot") -> None:
        super().__init__(bot)
        self._issue_cache: Dict[str, Tuple[IssueSummary, datetime]] = {}
        self.templates = TemplateManager(self.bot.loader, "templates/messages")
        self._reply_event_ids: Dict[EventID, EventID] = {}

    issue_mention_re = re.compile(r"[A-Z]{1,5}-\d+")

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
                    (issue.priority_label or "").replace("No priority", ""),
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
            if summary and expiration > datetime.now():
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

    _event_reply_working_set_lock = asyncio.Lock()

    @event.on(EventType.ROOM_MESSAGE)
    async def on_issue_mention(self, evt: MessageEvent) -> None:
        if evt.sender == self.bot.client.mxid:
            return

        client = self.bot.clients.get_by_mxid(evt.sender)
        if not client:
            on_behalf_of = evt.content.get("space.nevarro.standupbot.on_behalf_of")
            if not on_behalf_of:
                return
            if evt.sender not in self.bot.on_behalf_of_whitelist.get(evt.room_id, []):
                return

            self.bot.log.info(f"{evt.sender} sent message on behalf of {on_behalf_of}")
            client = self.bot.clients.get_by_mxid(evt.sender)
            if not client:
                return

        async with self._event_reply_working_set_lock:
            self.bot.log.silly(f"_event_reply_working_set_lock acquired for {evt.event_id}")
            await self.respond_with_issue_details(evt, client)
            self.bot.log.silly(f"_event_reply_working_set_lock released for {evt.event_id}")

    async def respond_with_issue_details(self, evt: MessageEvent, client: LinearClient):
        issue_details_futures = await asyncio.gather(
            *(
                self.get_issue_details(client, issue_identifier)
                for issue_identifier in set(
                    self.issue_mention_re.findall(evt.content.body)
                )
            )
        )
        issue_details = [d for d in issue_details_futures if d]
        if issue_details:
            issue_summaries = await self.format_issue_summaries(issue_details)
            content = TextMessageEventContent(
                msgtype=MessageType.NOTICE,
                format=Format.HTML,
                formatted_body=issue_summaries,
            )
            # Detect edits
            edits = evt.content.get_edit()
            if edits:
                reply_event = self._reply_event_ids.get(edits)
                if reply_event:
                    content.set_edit(reply_event)
                else:
                    content.set_reply(edits)
                await evt.respond(content)
                return

            reply_event_id = await evt.reply(issue_summaries, allow_html=True)
            self._reply_event_ids[evt.event_id] = reply_event_id
        else:
            edits = evt.content.get_edit()
            if edits:
                reply_event = self._reply_event_ids.get(edits)
                if reply_event:
                    await evt.client.redact(evt.room_id, reply_event)
                    del self._reply_event_ids[edits]
