"""Tests for database persistence."""
import pytest
import tempfile
import os
from kraken_bot.persistence.database import Database


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    database.connect()
    yield database
    database.close()
    os.unlink(path)


class TestRuns:
    def test_start_end_run(self, db):
        run_id = db.start_run("dry-run", "{}", "1.0.0")
        assert run_id > 0
        db.end_run(run_id)


class TestCandles:
    def test_upsert_and_get(self, db):
        candles = [
            {"timestamp": 1000, "open": 100, "high": 110, "low": 95, "close": 105, "volume": 50},
            {"timestamp": 1060, "open": 105, "high": 115, "low": 100, "close": 110, "volume": 60},
        ]
        db.upsert_candles("BTCUSD", "spot", candles)
        result = db.get_candles("BTCUSD", "spot")
        assert len(result) == 2
        assert result[0]["open"] == 100


class TestOrders:
    def test_save_and_update(self, db):
        oid = db.save_order("test_001", "BTCUSD", "spot", "buy", "market", 0.001)
        assert oid > 0
        db.update_order_status("test_001", "filled", "TX123")
        orders = db.get_recent_orders(10)
        assert orders[0]["status"] == "filled"


class TestPositions:
    def test_open_close(self, db):
        pid = db.open_position("BTCUSD", "spot", "long", 50000, 0.002,
                               47500, 55000, 1.0)
        assert pid > 0
        positions = db.get_open_positions()
        assert len(positions) == 1
        db.close_position(pid, 5.0, "take_profit")
        positions = db.get_open_positions()
        assert len(positions) == 0


class TestEquity:
    def test_snapshot(self, db):
        db.save_equity_snapshot(100, 100, 0, 0, 0, 0, "dry-run")
        eq = db.get_latest_equity()
        assert eq["equity"] == 100


class TestEvents:
    def test_log_and_get(self, db):
        db.log_event("INFO", "test_event", "test message", "BTCUSD")
        events = db.get_recent_events(10)
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"

    def test_filter_by_severity(self, db):
        db.log_event("INFO", "info_event", "info")
        db.log_event("ERROR", "error_event", "error")
        errors = db.get_recent_events(10, "ERROR")
        assert len(errors) == 1

    def test_trades_today(self, db):
        count = db.get_trades_today_count()
        assert count == 0
