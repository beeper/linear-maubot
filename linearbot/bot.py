from typing import Type, Set
from uuid import UUID
import secrets

from yarl import URL
from sqlalchemy import MetaData

from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from mautrix.types import EventType

from maubot import Plugin

from .api import LinearClient
from .webhook import LinearWebhook
from .commands import LinearCommands
from .client_manager import ClientManager
from .label_manager import LabelManager
from .util.gitlab import GitLabMigrator
from .util.prefixless_dm import DMCommandHandler


class Config(BaseProxyConfig):
    def _copy_secret(self, helper: ConfigUpdateHelper, key: str) -> None:
        if not self[key] or self[key] == "put a random password here":
            helper.base[key] = secrets.token_urlsafe(32)
        else:
            helper.copy(key)

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        self._copy_secret(helper, "linear.webhook_secret")
        helper.copy("linear.token")
        helper.copy("linear.client_id")
        helper.copy("linear.client_secret")
        helper.copy("linear.allowed_organizations")

        helper.copy("gitlab.url")
        helper.copy("gitlab.token")
        self._copy_secret(helper, "gitlab.webhook_secret")

        helper.copy_dict("team_mapping")
        helper.copy_dict("user_mapping")
        helper.copy_dict("label_mapping")
        helper.copy_dict("label_name_mapping")


class LinearBot(Plugin):
    oauth_client_id: str
    oauth_client_secret: str
    _allowed_organizations: Set[UUID]
    linear_webhook: LinearWebhook
    clients: ClientManager
    labels: LabelManager
    linear_bot: LinearClient
    commands: LinearCommands
    migrator: GitLabMigrator
    prefixless_dm: DMCommandHandler

    async def start(self):
        db_metadata = MetaData()

        self.linear_bot = LinearClient(self)
        self.linear_webhook = await LinearWebhook(self).start()
        self.commands = LinearCommands(self)
        self.clients = ClientManager(self, db_metadata)
        self.labels = LabelManager(self, db_metadata)
        self.migrator = GitLabMigrator(self)
        self.prefixless_dm = DMCommandHandler(self.commands)

        self.on_external_config_update()
        db_metadata.create_all(self.database)
        self.clients.load_db()
        self.labels.load_db()

        self.register_handler_class(self.linear_webhook)
        self.register_handler_class(self.commands)

        if not self.labels.has_labels():
            await self._resync_labels()

    async def _resync_labels(self) -> None:
        all_labels = await self.linear_bot.get_all_labels()
        for team_labels in all_labels.values():
            for label in team_labels.values():
                self.labels.put(label.team.id, label.name, label.id)

    async def stop(self) -> None:
        self.client.remove_event_handler(EventType.ROOM_MESSAGE, self.prefixless_dm.handle)

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config

    def on_external_config_update(self) -> None:
        self.config.load_and_update()
        self.linear_webhook.secret = self.config["linear.webhook_secret"]
        self.linear_bot.authorization = self.config["linear.token"]
        self.oauth_client_id = self.config["linear.client_id"]
        self.oauth_client_secret = self.config["linear.client_secret"]
        self._allowed_organizations = {UUID(org_id) for org_id
                                       in self.config["linear.allowed_organizations"]}
        self.migrator.gitlab_url = URL(self.config["gitlab.url"])
        self.migrator.gitlab_token = self.config["gitlab.token"]
        self.migrator.label_mapping = self.config["label_mapping"]
        self.migrator.label_name_mapping = self.config["label_name_mapping"]
        self.migrator.team_mapping = self.config["team_mapping"]
        self.migrator.user_mapping = self.config["user_mapping"]
        if self.config["prefixless_dm"]:
            handlers = self.client.event_handlers.setdefault(EventType.ROOM_MESSAGE, [])
            handler_tuple = (self.prefixless_dm.handle, False)
            if handler_tuple not in handlers:
                handlers.append(handler_tuple)
        else:
            try:
                self.client.remove_event_handler(EventType.ROOM_MESSAGE, self.prefixless_dm.handle)
            except KeyError:
                pass

    def allow_org(self, org) -> bool:
        if not self._allowed_organizations:
            return True
        return org.id in self._allowed_organizations
