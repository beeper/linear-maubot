from .base import Command
from .login import CommandLogin
from .migrate import CommandMigrate


class LinearCommands(CommandLogin, CommandMigrate):
    pass


__all__ = ["LinearCommands", "Command"]
