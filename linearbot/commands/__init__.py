from .base import Command
from .login import CommandLogin
from .migrate import CommandMigrate
from .reply import CommandReply
from .sync_labels import CommandSyncLabels


class LinearCommands(CommandLogin, CommandMigrate, CommandReply, CommandSyncLabels):
    pass


__all__ = ["LinearCommands", "Command"]
