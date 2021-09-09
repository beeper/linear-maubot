import asyncio
from typing import Dict, Optional, NamedTuple
from uuid import UUID, uuid4

from mautrix.types import EventType, EventID, RoomID, ReactionEvent, RelationType
from maubot.handlers import event
from maubot import MessageEvent

from ..api import LinearClient
from ..api.types import LinearEventType
from .base import Command, with_client


class EventMeta(NamedTuple):
    type: Optional[LinearEventType]
    id: Optional[UUID]
    issue_id: Optional[UUID]


processing_done = "✅"
processing = "👀"


class CommandReply(Command):
    _event_meta_cache: Dict[EventID, EventMeta]

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._event_meta_cache = {}

    async def _get_event_meta(self, room_id: RoomID, event_id: EventID) -> EventMeta:
        try:
            meta = self._event_meta_cache[event_id]
        except KeyError:
            evt = await self.bot.client.get_event(room_id, event_id)
            try:
                webhook_meta = evt.content["com.beeper.linear.webhook"]
                evt_type = LinearEventType.deserialize(webhook_meta["type"])
                main_id = UUID(webhook_meta["data"]["id"])
                if evt_type == LinearEventType.COMMENT:
                    issue_id = UUID(webhook_meta["data"]["issue_id"])
                elif evt_type == LinearEventType.ISSUE:
                    issue_id = main_id
                else:
                    issue_id = None
                meta = EventMeta(evt_type, main_id, issue_id)
            except (KeyError, ValueError):
                meta = None, None
            self._event_meta_cache[event_id] = meta
        return meta

    @event.on(EventType.ROOM_MESSAGE)
    @with_client(error_message=False)
    async def on_reply(self, evt: MessageEvent, client: LinearClient) -> None:
        if not evt.content.get_reply_to() or evt.sender == evt.client.mxid:
            return
        meta = await self._get_event_meta(evt.room_id, evt.content.get_reply_to())
        if meta.issue_id:
            reaction_event_id = await evt.react(processing)
            new_comment_id = uuid4()
            self.bot.linear_webhook.ignore_uuids.add(new_comment_id)
            await client.create_comment(meta.issue_id, evt.content.body, new_comment_id)
            await asyncio.gather(
                evt.client.redact(evt.room_id, reaction_event_id),
                evt.react(processing_done),
            )

    @event.on(EventType.REACTION)
    @with_client(error_message=False)
    async def on_react(self, evt: ReactionEvent, client: LinearClient) -> None:
        if (evt.content.relates_to.rel_type != RelationType.ANNOTATION
                or evt.sender == self.bot.client.mxid):
            return
        meta = await self._get_event_meta(evt.room_id, evt.content.relates_to.event_id)
        if meta.type == LinearEventType.COMMENT and meta.id:
            new_reaction_id = uuid4()
            self.bot.linear_webhook.ignore_uuids.add(new_reaction_id)
            await client.create_reaction(meta.id, evt.content.relates_to.key, new_reaction_id)
