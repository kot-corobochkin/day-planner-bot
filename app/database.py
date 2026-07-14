from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row

from app.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        with Connection.connect(self._settings.database_url, row_factory=dict_row) as conn:
            yield conn

