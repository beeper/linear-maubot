from typing import Callable, Awaitable, TYPE_CHECKING
import functools

from maubot.handlers import command
from maubot import MessageEvent

from ..api import LinearClient

if TYPE_CHECKING:
    from ..bot import LinearBot


class Command:
    bot: 'LinearBot'

    def __init__(self, bot: 'LinearBot') -> None:
        self.bot = bot

    @command.new(name="linear", help="Do things on Linear",
                 require_subcommand=True)
    async def linear(self) -> None:
        pass


_CmdHandler = Callable[[Command, MessageEvent, LinearClient, ...], Awaitable[None]]
_BaseCmdHandler = Callable[[Command, MessageEvent, ...], Awaitable[None]]
_Decorator = Callable[[_CmdHandler], _BaseCmdHandler]


def with_client(error_message: bool = True) -> _Decorator:
    def decorator(fn: _CmdHandler) -> _BaseCmdHandler:
        @functools.wraps(fn)
        async def wrapper(self: Command, evt: MessageEvent, *args, **kwargs) -> None:
            client = self.bot.clients.get_by_mxid(evt.sender)
            if not client:
                if error_message:
                    await evt.reply("You must log in to use that command.")
                return
            return await fn(self, evt, client, *args, **kwargs)

        return wrapper

    return decorator
