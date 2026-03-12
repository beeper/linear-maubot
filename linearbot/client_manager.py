from typing import Dict, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import MetaData, Table, Column, Text
from sqlalchemy.engine.base import Engine

from mautrix.types import UserID

from .api import LinearClient

if TYPE_CHECKING:
    from .bot import LinearBot


class ClientManager:
    bot: 'LinearBot'
    _clients_by_mxid: Dict[UserID, LinearClient]
    _clients_by_uuid: Dict[UUID, LinearClient]
    _table: Table
    _db: Engine

    def __init__(self, bot: 'LinearBot', metadata: MetaData) -> None:
        self.bot = bot
        self._db = bot.database
        self._table = Table("client", metadata,
                            Column("user_id", Text, primary_key=True),
                            Column("linear_uuid", Text, nullable=False),
                            Column("authorization", Text, nullable=False))
        self._clients_by_uuid = {}
        self._clients_by_mxid = {}

    def load_db(self) -> None:
        self._clients_by_mxid = {user_id: LinearClient(self.bot, user_id, UUID(linear_uuid), stored_token)
                                 for user_id, linear_uuid, stored_token
                                 in self._db.execute(self._table.select())}
        self._clients_by_uuid = {client.own_id: client
                                 for client in self._clients_by_mxid.values()}

    def put(self, user_id: UserID, client: LinearClient) -> None:
        # For new-style clients, store the refresh token. For legacy clients (no refresh token),
        # store the long-lived access token so it continues to work.
        stored_token = client.refresh_token or client.authorization
        with self._db.begin() as conn:
            self._clients_by_mxid[user_id] = client
            self._clients_by_uuid[client.own_id] = client
            conn.execute(self._table.delete().where(self._table.c.user_id == user_id))
            conn.execute(self._table.insert().values(user_id=user_id,
                                                     linear_uuid=str(client.own_id),
                                                     authorization=stored_token))

    def get_by_mxid(self, user_id: UserID) -> Optional[LinearClient]:
        return self._clients_by_mxid.get(user_id)

    def get_by_uuid(self, user_id: UUID) -> Optional[LinearClient]:
        return self._clients_by_uuid.get(user_id)

    def pop(self, user_id: UserID) -> Optional[LinearClient]:
        with self._db.begin() as conn:
            conn.execute(self._table.delete().where(self._table.c.user_id == user_id))
        client = self._clients_by_mxid.pop(user_id, None)
        if client:
            self._clients_by_uuid.pop(client.own_id, None)
        return client
