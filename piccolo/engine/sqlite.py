from dataclasses import dataclass
import os
import sqlite3
import typing as t

import aiosqlite
from aiosqlite import Cursor, Connection

from piccolo.engine.base import Batch, Engine
from piccolo.query.base import Query
from piccolo.querystring import QueryString


@dataclass
class AsyncBatch(Batch):

    connection: Connection
    query: Query
    batch_size: int

    # Set internally
    _cursor: t.Optional[Cursor] = None

    @property
    def cursor(self) -> Cursor:
        if not self._cursor:
            raise ValueError("_cursor not set")
        return self._cursor

    async def next(self) -> t.List[t.Dict]:
        data = await self.cursor.fetchmany(self.batch_size)
        return await self.query._process_results(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        response = await self.next()
        if response == []:
            raise StopAsyncIteration()
        return response

    async def __aenter__(self):
        querystring = self.query.querystring[0]
        template, template_args = querystring.compile_string()

        self._cursor = await self.connection.execute(template, *template_args)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        print("waiting to exit")
        await self._cursor.close()
        await self.connection.close()


###############################################################################


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


class SQLiteEngine(Engine):

    __slots__ = ("path",)

    engine_type = "sqlite"
    min_version_number = 3.25

    def __init__(self, path: str = "piccolo.sqlite") -> None:
        self.path = path
        super().__init__()

    def get_version(self) -> float:
        """
        Warn if the version of SQLite isn't supported.
        """
        major, minor, _ = sqlite3.sqlite_version_info
        return float(f"{major}.{minor}")

    ###########################################################################

    def remove_db_file(self):
        """
        Use with caution - removes the sqlite file. Useful for testing
        purposes.
        """
        if os.path.exists(self.path):
            os.unlink(self.path)

    def create_db(self, migrate=False):
        """
        Create the database file, with the option to run migrations. Useful
        for testing purposes.
        """
        if not os.path.exists(self.path):
            with open(self.path, "w") as _:
                pass
        else:
            raise Exception(f"Database at {self.path} already exists")
        if migrate:
            from piccolo.commands.migration.forwards import (
                ForwardsMigrationManager,
            )

            ForwardsMigrationManager().run()

    ###########################################################################

    async def batch(self, query: Query, batch_size=100) -> AsyncBatch:
        connection = await self.get_connection()
        return AsyncBatch(
            connection=connection, query=query, batch_size=batch_size
        )

    ###########################################################################

    async def get_connection(self) -> Connection:
        connection = await aiosqlite.connect(
            self.path, detect_types=sqlite3.PARSE_DECLTYPES
        )
        connection.row_factory = dict_factory
        return connection

    ###########################################################################

    async def run(
        self, query: str, args: t.List[t.Any] = [], query_type: str = "generic"
    ):
        async with aiosqlite.connect(
            self.path, detect_types=sqlite3.PARSE_DECLTYPES
        ) as connection:

            connection.row_factory = dict_factory
            async with connection.execute(query, args) as cursor:
                cursor.row_factory = dict_factory
                await connection.commit()
                response = await cursor.fetchall()

                if query_type == "insert":
                    return [{"id": cursor.lastrowid}]
                else:
                    return response

    async def run_querystring(
        self, querystring: QueryString, in_pool: bool = False
    ):
        return await self.run(
            *querystring.compile_string(engine_type=self.engine_type),
            query_type=querystring.query_type,
        )

    def transaction(self):
        raise NotImplementedError
