from typing import Set

from mautrix.types import MessageType, RoomID
from maubot import MessageEvent

from ..commands import LinearCommands


class DMCommandHandler:
    dm_rooms: Set[RoomID]
    not_dm_rooms: Set[RoomID]
    commands: LinearCommands

    def __init__(self, commands: LinearCommands) -> None:
        self.dm_rooms = set()
        self.not_dm_rooms = set()
        self.commands = commands

    async def handle(self, evt: MessageEvent) -> None:
        if (evt.room_id in self.not_dm_rooms
                or evt.sender == evt.client.mxid
                or evt.content.msgtype != MessageType.TEXT
                or evt.content.body.startswith("!")):
            return
        if evt.room_id not in self.dm_rooms:
            members = await evt.client.get_joined_members(evt.room_id)
            if len(members) == 2:
                self.dm_rooms.add(evt.room_id)
            else:
                self.not_dm_rooms.add(evt.room_id)
                return
        await self.commands.linear(evt, remaining_val=evt.content.body)
