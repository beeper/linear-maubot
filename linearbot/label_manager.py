from typing import Tuple, Dict, Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import MetaData, Table, Column, Text
from sqlalchemy.engine.base import Engine

from mautrix.util.logging import TraceLogger

if TYPE_CHECKING:
    from .bot import LinearBot


class LabelManager:
    _labels_by_team_and_name: Dict[Tuple[UUID, str], Optional[UUID]]
    _table: Table
    _db: Engine
    _log: TraceLogger

    def __init__(self, bot: 'LinearBot', metadata: MetaData) -> None:
        self._db = bot.database
        self._log = bot.log.getChild("labels")
        self._table = Table("label", metadata,
                            Column("team_id", Text, primary_key=True),
                            Column("label_name", Text, primary_key=True),
                            Column("label_id", Text, nullable=False))
        self._labels_by_team_and_name = {}

    def has_labels(self) -> bool:
        return len(self._labels_by_team_and_name) > 0

    def load_db(self) -> None:
        self._labels_by_team_and_name = {(UUID(team_id), label_name): label_id
                                         for team_id, label_name, label_id
                                         in self._db.execute(self._table.select())}

    def put(self, team_id: UUID, label_name: str, label_id: UUID) -> None:
        self._log.debug(f"Storing new label {label_name} -> {label_id} in {team_id}")
        with self._db.begin() as conn:
            self._labels_by_team_and_name[(team_id, label_name)] = label_id
            conn.execute(self._table.delete().where((self._table.c.team_id == str(team_id)) &
                                                    (self._table.c.label_name == str(label_name))))
            conn.execute(self._table.insert().values(team_id=str(team_id),
                                                     label_name=label_name,
                                                     label_id=str(label_id)))

    def get(self, team_id: UUID, label_name: str) -> Optional[UUID]:
        return self._labels_by_team_and_name.get((team_id, label_name))
