from contextlib import contextmanager
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Database:
    def __init__(self, url, min_size=1, max_size=5):
        self.url = url
        self.pool = None
        if url:
            self.pool = ConnectionPool(
                conninfo=url,
                min_size=min_size,
                max_size=max_size,
                kwargs={"row_factory": dict_row},
                open=False,
            )

    def open(self):
        if self.pool:
            self.pool.open(wait=True)

    def close(self):
        if self.pool:
            self.pool.close()

    @contextmanager
    def connection(self):
        if not self.pool:
            raise RuntimeError("DATABASE_URL is not configured")
        with self.pool.connection() as conn:
            yield conn

