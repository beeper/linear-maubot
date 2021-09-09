from typing import Set, List, Dict, TYPE_CHECKING
from uuid import UUID
import asyncio
import json
import re

from aiohttp.web import Request, Response
import attr

from mautrix.types import (RoomID, EventType, StateEvent, Membership, SerializerError,
                           TextMessageEventContent, MessageType, Format)
from mautrix.util.formatter import parse_html
from maubot.handlers import web, event

from .api.types import LinearEvent, MinimalUser, LINEAR_ENUMS
from .util.template import TemplateManager, TemplateNotFound, TemplateUtil

if TYPE_CHECKING:
    from .bot import LinearBot

spaces = re.compile(" +")
space = " "


class LinearWebhook:
    bot: 'LinearBot'
    secret: str
    task_list: List[asyncio.Task]
    joined_rooms: Set[RoomID]
    handled_webhooks: Set[UUID]
    ignore_uuids: Set[UUID]
    messages: TemplateManager
    # templates: TemplateManager

    def __init__(self, bot: 'LinearBot') -> None:
        self.bot = bot
        self.log = self.bot.log.getChild("webhook")
        self.task_list = []
        self.joined_rooms = set()
        self.handled_webhooks = set()
        self.ignore_uuids = set()

        self.messages = TemplateManager(self.bot.loader, "templates/messages")
        # self.templates = TemplateManager(self.bot.loader, "templates/mixins")

    async def start(self) -> 'LinearWebhook':
        self.joined_rooms = set(await self.bot.client.get_joined_rooms())
        return self

    async def stop(self) -> None:
        if self.task_list:
            await asyncio.wait(self.task_list, timeout=1)

    async def handle_webhook(self, room_id: RoomID, evt: LinearEvent) -> None:
        if evt.data.id in self.ignore_uuids:
            self.log.debug(f"Dropping webhook for {evt.type} {evt.data.id}"
                           " that was marked to be ignored")
            self.ignore_uuids.remove(evt.data.id)
            return

        template_name = f"{evt.type.name.lower()}_{evt.action.name.lower()}"
        try:
            tpl = self.messages[template_name]
        except TemplateNotFound:
            self.log.debug(f"Unhandled {evt.type} {evt.action} from Linear")
            return

        aborted = False

        def abort() -> None:
            nonlocal aborted
            aborted = True

        args = {
            **attr.asdict(evt, recurse=False),
            **LINEAR_ENUMS,
            "abort": abort,
            "util": TemplateUtil,
            "cli": self.bot.linear_bot,
        }
        # args["templates"] = self.templates.proxy(args)

        html = await tpl.render_async(**args)
        if not html or aborted:
            return
        html = spaces.sub(space, html.strip())
        content = TextMessageEventContent(msgtype=MessageType.NOTICE, format=Format.HTML,
                                          formatted_body=html, body=parse_html(html))
        content["com.beeper.linear.webhook"] = {
            "type": evt.type.value,
            "action": evt.action.value,
            "data": await evt.data.get_meta(client=self.bot.linear_bot),
        }
        if evt.url:
            content.external_url = evt.url
        query = {"ts": int(evt.created_at.timestamp() * 1000)}

        await self.bot.client.send_message(room_id, content, query_params=query)

    async def _try_handle_webhook(self, delivery_id: UUID, room_id: RoomID, evt: LinearEvent
                                  ) -> None:
        try:
            await self.handle_webhook(room_id, evt)
        except Exception:
            self.log.exception(f"Error handling webhook {delivery_id}")
        finally:
            try:
                task = asyncio.current_task()
                self.task_list.remove(task)
            except RuntimeError:
                pass

    @web.post("/webhooks")
    async def webhook(self, request: Request) -> Response:
        if request.headers["X-Forwarded-For"] not in ("35.231.147.226", "35.243.134.228"):
            return Response(status=401, text="401: Unauthorized\nUnrecognized source IP\n")
        if request.url.query.get("secret") != self.secret:
            return Response(status=401, text="401: Unauthorized\n"
                                             "Missing or incorrect `secret` query parameter\n")
        try:
            room_id = RoomID(request.url.query["room_id"])
        except KeyError:
            return Response(status=400, text="400: Bad Request\n"
                                             "Missing `room_id` query parameter\n")
        if room_id not in self.joined_rooms:
            return Response(text="403: Forbidden\nThe bot is not in the room. "
                                 f"Please invite {self.bot.client.mxid} to the room.\n",
                            status=403)
        try:
            delivery_id = UUID(request.headers["Linear-Delivery"])
        except (KeyError, ValueError):
            self.log.debug("Ignoring delivery with invalid delivery ID %s",
                           request.headers.getone("Linear-Delivery", "(not specified)"))
            return Response(status=400, text="400: Bad Request\n"
                                             "`Linear-Delivery` header missing or not an UUID\n")
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            self.log.debug(f"Ignoring delivery {delivery_id} with bad JSON: {e}")
            return Response(status=406, text="400: Bad Request\nBody is not valid JSON\n",
                            headers={"Accept": "application/json"})
        if delivery_id in self.handled_webhooks:
            self.log.debug(f"Ignoring duplicate delivery {delivery_id}")
            return Response(status=200, text="200: OK\n"
                                             "Delivery ID was already handled, webhook ignored.\n")
        self.handled_webhooks.add(delivery_id)
        print("Webhook content:", body)
        try:
            evt = LinearEvent.deserialize(body)
        except SerializerError as e:
            self.log.warning(f"Failed to deserialize linear event in {delivery_id}: {e}")
            self.log.debug("Errored data: %s", body)
            return Response(status=200, text="200: OK\n"
                                             "Failed to validate schema, webhook ignored.\n")
        try:
            self.log.debug("Unrecognized data in event %s: %s", delivery_id,
                           evt.data.unrecognized_)
            self.log.debug("Recognized data in %s: %s", delivery_id, evt)
        except AttributeError:
            self.log.trace("Received event %s: %s", delivery_id, evt)
        task = asyncio.create_task(self._try_handle_webhook(delivery_id, room_id, evt))
        self.task_list.append(task)
        return Response(status=202, text="202: Accepted\nWebhook processing started.\n")

    @event.on(EventType.ROOM_MEMBER)
    async def member_handler(self, evt: StateEvent) -> None:
        if evt.state_key != self.bot.client.mxid:
            return

        if evt.content.membership in (Membership.LEAVE, Membership.BAN):
            self.joined_rooms.remove(evt.room_id)
        if evt.content.membership == Membership.JOIN:
            self.joined_rooms.add(evt.room_id)
