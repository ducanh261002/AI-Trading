import json


class CandleStore:
    def __init__(self, database, limit):
        self.database, self.limit = database, limit

    def initialize(self):
        with self.database.connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL, interval TEXT NOT NULL, open_time INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(symbol,interval,open_time))""")

    def save(self, symbol, interval, rows):
        with self.database.connect() as con:
            con.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?)",
                            [(symbol, interval, r["open_time"], json.dumps(r)) for r in rows])
            con.execute("""DELETE FROM candles WHERE symbol=? AND interval=? AND open_time NOT IN
                (SELECT open_time FROM candles WHERE symbol=? AND interval=?
                 ORDER BY open_time DESC LIMIT ?)""", (symbol, interval, symbol, interval, self.limit))

    def read(self, symbol, interval):
        with self.database.connect() as con:
            rows = con.execute("SELECT payload FROM candles WHERE symbol=? AND interval=? ORDER BY open_time DESC LIMIT ?",
                               (symbol, interval, self.limit)).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]
