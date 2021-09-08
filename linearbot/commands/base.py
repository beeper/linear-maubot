from typing import Callable, Awaitable, TYPE_CHECKING
import functools

from maubot.handlers import command
from maubot import MessageEvent

if TYPE_CHECKING:
    from ..bot import LinearBot
    from ..api import LinearClient


class Command:
    bot: 'LinearBot'

    def __init__(self, bot: 'LinearBot') -> None:
        self.bot = bot

    @command.new(name="linear", help="Do things on Linear",
                 require_subcommand=True)
    async def linear(self) -> None:
        pass


_CmdHandler = Callable[[Command, MessageEvent, 'LinearClient', ..., 'LinearBot'], Awaitable[None]]


def with_client(fn: _CmdHandler) -> _CmdHandler:
    @functools.wraps(fn)
    async def wrapper(self: Command, evt: MessageEvent, *args, **kwargs) -> None:
        client = self.bot.clients.get_by_mxid(evt.sender)
        if not client:
            await evt.reply("You must log in to use that command.")
            return
        return await fn(self, evt, client, *args, **kwargs)

    return wrapper
