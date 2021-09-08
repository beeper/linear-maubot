from maubot import MessageEvent
from maubot.handlers import command

from .base import Command, with_client
from ..api import LinearClient
from ..util.gitlab import MigrationError, MigrationURLParseError


class CommandMigrate(Command):
    @Command.linear.subcommand(help="Migrate a GitLab issue to Linear", aliases=["m"])
    @command.argument("input_url", label="issue URLs...", pass_raw=True)
    @with_client
    async def migrate(self, evt: MessageEvent, client: LinearClient, input_url: str) -> None:
        urls = [url.strip() for url in input_url.split(" ") if url.strip()]
        if not urls:
            await evt.reply("**Usage:** !linear migrate <issue URLs...>")
            return
        await evt.react("👀")
        for gitlab_url in urls:
            try:
                res = await self.bot.migrator.migrate(client, gitlab_url)
            except MigrationURLParseError as e:
                await evt.reply(f"Failed to migrate {gitlab_url}: {e}")
            except MigrationError as e:
                await evt.reply(f"Failed to migrate {e.gitlab_id}: {e}")
            except Exception:
                self.bot.log.exception(f"Failed to migrate {gitlab_url} to Linear")
                await evt.reply("Unknown error while migrating issue (see logs for more details)")
            else:
                await evt.reply(f"Successfully migrated [{res.gitlab_id}]({gitlab_url}) "
                                f"to [{res.linear_id}]({res.linear_url})")
