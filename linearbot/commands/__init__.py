from .base import Command
from .login import CommandLogin
from .migrate import CommandMigrate
from .reply import CommandReply


class LinearCommands(CommandLogin, CommandMigrate, CommandReply):
    pass


__all__ = ["LinearCommands", "Command"]
