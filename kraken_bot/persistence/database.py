"""SQLite database for persistence and audit trail."""
import sqlite3
import json
import time
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    config_json TEXT,
    version TEXT
);

CREATE TABLE IF NOT EXISTS candles_1h (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    UNIQUE(symbol, market_type, timestamp)
);

CREATE TABLE IF NOT EXISTS levels_sr (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    price REAL NOT NULL,
    level_type TEXT NOT NULL,
    touches INTEGER NOT NULL,
    last_touch_ts INTEGER,
    score REAL,
    invalidated INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trendlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    slope REAL NOT NULL,
    intercept REAL NOT NULL,
    touches INTEGER NOT NULL,
    points_json TEXT,
    score REAL,
    max_deviation REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    entry_price REAL,
    sl_price REAL,
    tp_price REAL,
    reason TEXT,
    filters_passed TEXT,
    filters_blocked TEXT,
    created_at TEXT NOT NULL,
    acted_on INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_order_id TEXT UNIQUE NOT NULL,
    exchange_order_id TEXT,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    order_type TEXT NOT NULL,
    volume REAL NOT NULL,
    price REAL,
    price2 REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    post_only INTEGER DEFAULT 0,
    reduce_only INTEGER DEFAULT 0,
    leverage TEXT,
    signal_id INTEGER,
    error_msg TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    exchange_fill_id TEXT,
    price REAL NOT NULL,
    volume REAL NOT NULL,
    fee REAL DEFAULT 0,
    fee_currency TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    current_price REAL,
    size REAL NOT NULL,
    sl_price REAL,
    tp_price REAL,
    sl_order_id TEXT,
    tp_order_id TEXT,
    trailing_active INTEGER DEFAULT 0,
    trailing_price REAL,
    entry_time TEXT NOT NULL,
    candles_elapsed INTEGER DEFAULT 0,
    pnl_unrealized REAL DEFAULT 0,
    pnl_realized REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    close_reason TEXT,
    closed_at TEXT,
    leverage REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    equity REAL NOT NULL,
    equity_high REAL NOT NULL,
    dd_daily_pct REAL DEFAULT 0,
    dd_weekly_pct REAL DEFAULT 0,
    open_positions INTEGER DEFAULT 0,
    trades_today INTEGER DEFAULT 0,
    mode TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    severity TEXT NOT NULL,
    event_type TEXT NOT NULL,
    symbol TEXT,
    payload TEXT,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts ON candles_1h(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_orders_client_id ON orders(client_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_snapshots(timestamp);
"""


class Database:
    """SQLite database manager with full audit trail."""

    def __init__(self, db_path: str = "kraken_bot.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # --- Runs ---

    def start_run(self, mode: str, config_json: str = "", version: str = "1.0.0") -> int:
        cur = self._conn.execute(
            "INSERT INTO runs (mode, started_at, config_json, version) VALUES (?, ?, ?, ?)",
            (mode, self._now(), config_json, version)
        )
        self._conn.commit()
        return cur.lastrowid

    def end_run(self, run_id: int):
        self._conn.execute("UPDATE runs SET ended_at = ? WHERE id = ?", (self._now(), run_id))
        self._conn.commit()

    # --- Candles ---

    def upsert_candles(self, symbol: str, market_type: str, candles: List[Dict]):
        for c in candles:
            self._conn.execute(
                """INSERT OR REPLACE INTO candles_1h
                   (symbol, market_type, timestamp, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, market_type, c["timestamp"], c["open"], c["high"],
                 c["low"], c["close"], c["volume"])
            )
        self._conn.commit()

    def get_candles(self, symbol: str, market_type: str, limit: int = 500) -> List[Dict]:
        rows = self._conn.execute(
            """SELECT timestamp, open, high, low, close, volume FROM candles_1h
               WHERE symbol = ? AND market_type = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (symbol, market_type, limit)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # --- S/R Levels ---

    def save_level(self, symbol: str, market_type: str, price: float, level_type: str,
                   touches: int, last_touch_ts: int, score: float) -> int:
        now = self._now()
        cur = self._conn.execute(
            """INSERT INTO levels_sr (symbol, market_type, price, level_type, touches,
               last_touch_ts, score, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, market_type, price, level_type, touches, last_touch_ts, score, now, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_levels(self, symbol: str, market_type: str, min_touches: int = 4) -> List[Dict]:
        rows = self._conn.execute(
            """SELECT * FROM levels_sr WHERE symbol = ? AND market_type = ?
               AND touches >= ? AND invalidated = 0 ORDER BY score DESC""",
            (symbol, market_type, min_touches)
        ).fetchall()
        return [dict(r) for r in rows]

    def invalidate_level(self, level_id: int):
        self._conn.execute(
            "UPDATE levels_sr SET invalidated = 1, updated_at = ? WHERE id = ?",
            (self._now(), level_id)
        )
        self._conn.commit()

    # --- Trendlines ---

    def save_trendline(self, symbol: str, market_type: str, direction: str,
                       slope: float, intercept: float, touches: int,
                       points: List, score: float, max_deviation: float) -> int:
        now = self._now()
        cur = self._conn.execute(
            """INSERT INTO trendlines (symbol, market_type, direction, slope, intercept,
               touches, points_json, score, max_deviation, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, market_type, direction, slope, intercept, touches,
             json.dumps(points), score, max_deviation, now, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_trendlines(self, symbol: str, market_type: str, min_touches: int = 4) -> List[Dict]:
        rows = self._conn.execute(
            """SELECT * FROM trendlines WHERE symbol = ? AND market_type = ?
               AND touches >= ? ORDER BY score DESC""",
            (symbol, market_type, min_touches)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["points"] = json.loads(d.get("points_json", "[]"))
            result.append(d)
        return result

    # --- Signals ---

    def save_signal(self, symbol: str, market_type: str, direction: str,
                    signal_type: str, entry_price: float, sl_price: float,
                    tp_price: float, reason: str,
                    filters_passed: List[str], filters_blocked: List[str]) -> int:
        cur = self._conn.execute(
            """INSERT INTO signals (symbol, market_type, direction, signal_type,
               entry_price, sl_price, tp_price, reason, filters_passed,
               filters_blocked, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, market_type, direction, signal_type, entry_price, sl_price,
             tp_price, reason, json.dumps(filters_passed),
             json.dumps(filters_blocked), self._now())
        )
        self._conn.commit()
        return cur.lastrowid

    def mark_signal_acted(self, signal_id: int):
        self._conn.execute("UPDATE signals SET acted_on = 1 WHERE id = ?", (signal_id,))
        self._conn.commit()

    def get_recent_signals(self, limit: int = 50) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Orders ---

    def save_order(self, client_order_id: str, symbol: str, market_type: str,
                   direction: str, order_type: str, volume: float,
                   price: Optional[float] = None, price2: Optional[float] = None,
                   post_only: bool = False, reduce_only: bool = False,
                   leverage: str = "", signal_id: Optional[int] = None) -> int:
        now = self._now()
        cur = self._conn.execute(
            """INSERT INTO orders (client_order_id, symbol, market_type, direction,
               order_type, volume, price, price2, post_only, reduce_only,
               leverage, signal_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (client_order_id, symbol, market_type, direction, order_type, volume,
             price, price2, int(post_only), int(reduce_only), leverage,
             signal_id, now, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def update_order_status(self, client_order_id: str, status: str,
                            exchange_order_id: Optional[str] = None,
                            error_msg: Optional[str] = None):
        updates = ["status = ?", "updated_at = ?"]
        params: list = [status, self._now()]
        if exchange_order_id:
            updates.append("exchange_order_id = ?")
            params.append(exchange_order_id)
        if error_msg:
            updates.append("error_msg = ?")
            params.append(error_msg)
        params.append(client_order_id)
        self._conn.execute(
            f"UPDATE orders SET {', '.join(updates)} WHERE client_order_id = ?",
            params
        )
        self._conn.commit()

    def get_open_orders(self) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE status IN ('pending', 'open', 'partially_filled')"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_orders(self, limit: int = 50) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Fills ---

    def save_fill(self, order_id: int, price: float, volume: float,
                  fee: float = 0, fee_currency: str = "", exchange_fill_id: str = "") -> int:
        cur = self._conn.execute(
            """INSERT INTO fills (order_id, exchange_fill_id, price, volume, fee,
               fee_currency, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (order_id, exchange_fill_id, price, volume, fee, fee_currency, self._now())
        )
        self._conn.commit()
        return cur.lastrowid

    def get_recent_fills(self, limit: int = 50) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM fills ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Positions ---

    def open_position(self, symbol: str, market_type: str, direction: str,
                      entry_price: float, size: float, sl_price: float,
                      tp_price: float, leverage: float = 1.0,
                      sl_order_id: str = "", tp_order_id: str = "") -> int:
        cur = self._conn.execute(
            """INSERT INTO positions (symbol, market_type, direction, entry_price,
               size, sl_price, tp_price, sl_order_id, tp_order_id, entry_time,
               status, leverage) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (symbol, market_type, direction, entry_price, size, sl_price,
             tp_price, sl_order_id, tp_order_id, self._now(), leverage)
        )
        self._conn.commit()
        return cur.lastrowid

    def update_position(self, pos_id: int, **kwargs):
        if not kwargs:
            return
        updates = []
        params = []
        for k, v in kwargs.items():
            updates.append(f"{k} = ?")
            params.append(v)
        params.append(pos_id)
        self._conn.execute(
            f"UPDATE positions SET {', '.join(updates)} WHERE id = ?", params
        )
        self._conn.commit()

    def close_position(self, pos_id: int, pnl_realized: float, close_reason: str):
        self._conn.execute(
            """UPDATE positions SET status = 'closed', pnl_realized = ?,
               close_reason = ?, closed_at = ? WHERE id = ?""",
            (pnl_realized, close_reason, self._now(), pos_id)
        )
        self._conn.commit()

    def get_open_positions(self) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM positions WHERE status = 'open'"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_positions(self, limit: int = 100) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM positions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Equity ---

    def save_equity_snapshot(self, equity: float, equity_high: float,
                             dd_daily_pct: float, dd_weekly_pct: float,
                             open_positions: int, trades_today: int, mode: str):
        self._conn.execute(
            """INSERT INTO equity_snapshots (timestamp, equity, equity_high,
               dd_daily_pct, dd_weekly_pct, open_positions, trades_today, mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (self._now(), equity, equity_high, dd_daily_pct, dd_weekly_pct,
             open_positions, trades_today, mode)
        )
        self._conn.commit()

    def get_latest_equity(self) -> Optional[Dict]:
        row = self._conn.execute(
            "SELECT * FROM equity_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_equity_history(self, limit: int = 500) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM equity_snapshots ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_trades_today_count(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._conn.execute(
            """SELECT COUNT(*) as cnt FROM positions
               WHERE entry_time LIKE ? AND status IN ('open', 'closed')""",
            (f"{today}%",)
        ).fetchone()
        return row["cnt"] if row else 0

    # --- Events ---

    def log_event(self, severity: str, event_type: str, message: str,
                  symbol: str = "", payload: str = ""):
        self._conn.execute(
            """INSERT INTO events (timestamp, severity, event_type, symbol,
               payload, message) VALUES (?, ?, ?, ?, ?, ?)""",
            (self._now(), severity, event_type, symbol, payload, message)
        )
        self._conn.commit()

    def get_recent_events(self, limit: int = 100, severity: Optional[str] = None) -> List[Dict]:
        if severity:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE severity = ? ORDER BY id DESC LIMIT ?",
                (severity, limit)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
