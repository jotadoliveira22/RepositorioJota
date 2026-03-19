"""Configuration management for the trading bot."""
import os
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path


@dataclass
class WatchlistConfig:
    crypto_spot: List[str] = field(default_factory=lambda: [
        "XBT/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD"
    ])
    xstocks: List[str] = field(default_factory=lambda: [
        "AAPLx", "TSLAx", "MSFTx", "NVDAx", "SPYx"
    ])
    spot_fx: List[str] = field(default_factory=lambda: [
        "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD"
    ])
    futures: List[str] = field(default_factory=lambda: [
        "PF_XBTUSD", "PF_ETHUSD", "PF_SOLUSD"
    ])


@dataclass
class StrategyConfig:
    timeframe: str = "1h"
    lookback_candles: int = 500
    pivot_left: int = 3
    pivot_right: int = 3
    sr_tolerance_pct: float = 0.5
    sr_min_touches: int = 4
    trendline_min_touches: int = 4
    trendline_max_deviation_pct: float = 0.3
    ema_fast: int = 20
    ema_slow: int = 50
    ema_macro: int = 200
    use_macro_filter: bool = False
    entry_proximity_pct: float = 0.3
    min_rr_ratio: float = 1.5


@dataclass
class RiskConfig:
    initial_equity: float = 100.0
    risk_per_trade_pct: float = 5.0
    stop_loss_pct: float = 5.0
    max_trades_per_day: int = 5
    kill_switch_daily_dd_pct: float = 15.0
    kill_switch_weekly_dd_pct: float = 15.0
    max_leverage: float = 2.0
    default_leverage: float = 2.0
    trailing_enabled: bool = True
    trailing_activation_r: float = 1.0
    trailing_atr_multiplier: float = 1.5
    trailing_pct: float = 2.0
    time_stop_candles: int = 18
    position_flip_enabled: bool = True


@dataclass
class ExecutionConfig:
    max_spread_fx_pips: float = 2.0
    max_cost_tp_ratio: float = 0.15
    max_slippage_pct: float = 0.03
    slippage_cancel_pct: float = 0.05
    atr_filter_threshold: float = 0.80
    atr_filter_range: tuple = (0.70, 0.85)
    atr_period: int = 14
    atr_daily_lookback: int = 14
    post_only_enabled: bool = True
    dead_man_switch_timeout_spot: int = 60
    dead_man_switch_timeout_futures: int = 60
    rate_limit_buffer_pct: float = 0.8


@dataclass
class AlertConfig:
    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    email_enabled: bool = False
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_from: str = ""
    email_to: str = ""
    email_password: str = ""


@dataclass
class BotConfig:
    mode: str = "dry-run"  # dry-run, shadow, live
    watchlist: WatchlistConfig = field(default_factory=WatchlistConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    db_path: str = "kraken_bot.db"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    log_level: str = "INFO"
    kraken_spot_api_key: str = ""
    kraken_spot_api_secret: str = ""
    kraken_futures_api_key: str = ""
    kraken_futures_api_secret: str = ""


def load_config(path: Optional[str] = None) -> BotConfig:
    """Load configuration from file and environment variables."""
    config = BotConfig()

    if path and Path(path).exists():
        with open(path) as f:
            data = json.load(f)
        _apply_dict(config, data)

    # Override with env vars
    config.kraken_spot_api_key = os.getenv("KRAKEN_SPOT_API_KEY", config.kraken_spot_api_key)
    config.kraken_spot_api_secret = os.getenv("KRAKEN_SPOT_API_SECRET", config.kraken_spot_api_secret)
    config.kraken_futures_api_key = os.getenv("KRAKEN_FUTURES_API_KEY", config.kraken_futures_api_key)
    config.kraken_futures_api_secret = os.getenv("KRAKEN_FUTURES_API_SECRET", config.kraken_futures_api_secret)
    config.mode = os.getenv("BOT_MODE", config.mode)

    if config.alerts.telegram_enabled:
        config.alerts.telegram_token = os.getenv("TELEGRAM_TOKEN", config.alerts.telegram_token)
        config.alerts.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", config.alerts.telegram_chat_id)

    return config


def _apply_dict(obj, data: dict):
    """Recursively apply dict values to dataclass."""
    for key, value in data.items():
        if hasattr(obj, key):
            attr = getattr(obj, key)
            if hasattr(attr, '__dataclass_fields__') and isinstance(value, dict):
                _apply_dict(attr, value)
            else:
                setattr(obj, key, value)


def save_config(config: BotConfig, path: str):
    """Save configuration to JSON file."""
    import dataclasses
    data = dataclasses.asdict(config)
    # Remove secrets
    for key in ["kraken_spot_api_key", "kraken_spot_api_secret",
                "kraken_futures_api_key", "kraken_futures_api_secret"]:
        data.pop(key, None)
    if "alerts" in data:
        data["alerts"].pop("telegram_token", None)
        data["alerts"].pop("email_password", None)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
