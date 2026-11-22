"""SQLite seguro para várias threads (a voz, os trabalhos em segundo plano e a aprendizagem usam a mesma BD)."""
import sqlite3
import threading


class _Res:
    def __init__(self, rows, rowcount, lastrowid):
        self.rows, self.rowcount, self.lastrowid = rows, rowcount, lastrowid

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class DBSeguro:
    def __init__(self, caminho):
        self._c = sqlite3.connect(caminho, check_same_thread=False)
        self._l = threading.RLock()

    def execute(self, sql, args=()):
        with self._l:
            cur = self._c.execute(sql, args)
            rows = cur.fetchall() if cur.description else []
            return _Res(rows, cur.rowcount, cur.lastrowid)

    def executemany(self, sql, args_list):
        with self._l:
            cur = self._c.executemany(sql, args_list)
            rows = cur.fetchall() if cur.description else []
            return _Res(rows, cur.rowcount, cur.lastrowid)

    def executescript(self, script):
        with self._l:
            self._c.executescript(script)

    def commit(self):
        with self._l:
            self._c.commit()
