from .base import Command
from .issue_mention import CommandIssueMention
from .login import CommandLogin
from .migrate import CommandMigrate
from .reply import CommandReply
from .sync_labels import CommandSyncLabels


class LinearCommands(CommandLogin, CommandIssueMention, CommandMigrate, CommandReply, CommandSyncLabels):
    pass


__all__ = ["LinearCommands", "Command"]
