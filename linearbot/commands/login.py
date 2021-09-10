from typing import Dict, Optional, Tuple, TYPE_CHECKING
import asyncio
import secrets
import html

from aiohttp.web import Request, Response
from attr import dataclass
from yarl import URL

from mautrix.types import RoomID, UserID, EventID, EventType, ReactionEvent, RelationType
from maubot import MessageEvent
from maubot.handlers import web, event

from ..api import LinearClient, LogoutError, TokenAlreadyRevokedError
from ..api.types import User
from .base import Command

if TYPE_CHECKING:
    from linearbot.bot import LinearBot


@dataclass
class LoginInProgress:
    user_id: UserID
    room_id: RoomID
    event_id: EventID
    state: str
    lock: asyncio.Lock
    client: Optional[LinearClient] = None
    user: Optional[User] = None


html_wrapper = """
<!DOCTYPE html>
<html lang="en">
<head>
  <title>Linear Bot Login</title>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
  <style>
    body {
      text-align: center;
      font-family: sans-serif;
    }
  </style>
</head>
<body>
  {content}
</body>
</html>
"""

html_content = """
  <h1>{title}</h1>
  <p>{text}</p>
"""

ok_react = "✅"
success_response = ("Successfully authenticated as {name} ({email}).<br>"
                    "Please return to your Matrix client and follow the instructions "
                    "from the bot to complete the login.")
confirmation_message = ("Successfully authenticated as {name} ({email}). "
                        f"Please react to this message with {ok_react} to confirm the login.")
success_message = "Successfully logged in as {name} ({email}) 🎉"
not_allowed_message = "Login failed: {name} is not permitted to use this Linear bot"


def make_response(status: int, title: str, text: str) -> Response:
    content = html_wrapper.replace("{content}", html_content.format(title=title, text=text))
    return Response(status=status, content_type="text/html", text=content)


class CommandLogin(Command):
    bot: 'LinearBot'
    _logins_in_progress: Dict[str, LoginInProgress]
    _logins_waiting_for_confirmation: Dict[Tuple[EventID, UserID], LoginInProgress]
    _oauth_request = URL("https://linear.app/oauth/authorize")

    def __init__(self, bot: 'LinearBot') -> None:
        super().__init__(bot)
        self._logins_in_progress = {}
        self._logins_waiting_for_confirmation = {}

    @property
    def _oauth_redirect_url(self) -> str:
        return str(self.bot.webapp_url / "oauth")

    @Command.linear.subcommand(help="Log into the bot with your Linear account")
    async def login(self, evt: MessageEvent) -> None:
        if self.bot.clients.get_by_mxid(evt.sender):
            await evt.reply("You already have a token stored. "
                            "Log out with `!linear logout` first.")
            return
        state = secrets.token_urlsafe(64)
        login = LoginInProgress(user_id=evt.sender, room_id=evt.room_id, event_id=evt.event_id,
                                state=state, lock=asyncio.Lock())
        self._logins_in_progress[state] = login
        url = str(self._oauth_request.with_query({
            "client_id": self.bot.oauth_client_id,
            "redirect_uri": self._oauth_redirect_url,
            "response_type": "code",
            "state": state,
            "scope": "read,write",
        }))
        login.event_id = await evt.reply(f"[Click here]({url}) to log in")

    @Command.linear.subcommand(help="Check if you're logged in")
    async def ping(self, evt: MessageEvent) -> None:
        client = self.bot.clients.get_by_mxid(evt.sender)
        if not client:
            await evt.reply("You're not logged in")
            return
        own_info = await client.get_self()
        await evt.reply(f"You're logged in as @{own_info.display_name} / {own_info.name} "
                        f"(email: {own_info.email}, ID: {own_info.id})")

    @Command.linear.subcommand(help="Log out of the bot")
    async def logout(self, evt: MessageEvent) -> None:
        client = self.bot.clients.pop(evt.sender)
        if not client:
            await evt.reply("You're not logged in")
            return
        try:
            await client.logout()
            await evt.reply("Successfully logged out")
        except TokenAlreadyRevokedError:
            await evt.reply("Successfully removed token from database (token was already revoked)")
        except LogoutError as e:
            await evt.reply("Failed to revoke token, but removed it from the bot database. "
                            f"Error from server:\n\n> {e}")

    async def _claim_oauth_token(self, login: LoginInProgress, code: str) -> None:
        login.client = LinearClient(self.bot)
        await login.client.login(code, self._oauth_redirect_url)
        login.user = await login.client.get_self()

        if not self.bot.allow_org(login.user.organization):
            message = not_allowed_message.format(name=html.escape(login.user.organization.name))
            await self.bot.client.send_markdown(login.room_id, message, edits=login.event_id)
            return

        self._logins_waiting_for_confirmation[(login.event_id, login.user_id)] = login
        await self.bot.client.react(login.room_id, login.event_id, ok_react)
        message = confirmation_message.format(name=html.escape(login.user.name),
                                              email=html.escape(login.user.email))
        await self.bot.client.send_markdown(login.room_id, message, edits=login.event_id)

    async def _locked_claim_oauth_token(self, login: LoginInProgress, code: str) -> None:
        # Lock the login to prevent handling multiple requests at the same time
        async with login.lock:
            # If the request was already handled, skip re-handling and just return OK
            if not login.user:
                await self._claim_oauth_token(login, code)

    @web.get("/oauth")
    async def _handle_oauth_callback(self, request: Request) -> Response:
        try:
            state = request.url.query["state"]
            code = request.url.query["code"]
        except KeyError as e:
            return make_response(400, "Failed to log in", "Missing query parameter "
                                                          f"<code>{e}</code>")
        try:
            login = self._logins_in_progress[state]
        except KeyError:
            return make_response(400, "Failed to log in", "Invalid <code>state</code> parameter. "
                                                          "Please restart the login.")

        # TODO handle errors
        await asyncio.shield(self._locked_claim_oauth_token(login, code))

        if not self.bot.allow_org(login.user.organization):
            return make_response(401, "Organization not allowed",
                                 not_allowed_message.format(
                                     name=html.escape(login.user.organization.name)))
        return make_response(200, "Successfully logged in",
                             success_response.format(name=html.escape(login.user.name),
                                                     email=html.escape(login.user.email)))

    @event.on(EventType.REACTION)
    async def _handle_login_reaction(self, evt: ReactionEvent) -> None:
        if (evt.content.relates_to.rel_type != RelationType.ANNOTATION
                or evt.content.relates_to.key != ok_react):
            return
        try:
            login = self._logins_waiting_for_confirmation.pop((evt.content.relates_to.event_id,
                                                               evt.sender))
        except KeyError:
            return
        self.bot.clients.put(login.user_id, login.client)
        self._logins_in_progress.pop(login.state, None)
        message = success_message.format(name=html.escape(login.user.name),
                                         email=html.escape(login.user.email))
        await self.bot.client.send_markdown(login.room_id, message, edits=login.event_id)
