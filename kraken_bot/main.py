"""Entry point for the Kraken Trading Bot."""
import asyncio
import logging
import signal
import sys
import os
import threading
from pathlib import Path

import uvicorn

from .config import load_config, save_config, BotConfig
from .bot import TradingBot
from .api.server import create_app


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("kraken_bot.log", encoding="utf-8"),
        ]
    )
    # Reduce noise from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)


def main():
    config_path = os.getenv("BOT_CONFIG", "bot_config.json")
    config = load_config(config_path)
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    logger.info(f"Starting Kraken Trading Bot v1.0.0 in {config.mode} mode")

    # Create bot
    bot = TradingBot(config)

    # Create FastAPI app
    app = create_app(bot)

    # Signal handlers
    def shutdown_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        bot.stop()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Run API server in background thread
    api_thread = threading.Thread(
        target=lambda: uvicorn.run(
            app, host=config.api_host, port=config.api_port,
            log_level="warning"
        ),
        daemon=True
    )
    api_thread.start()
    logger.info(f"Dashboard running at http://{config.api_host}:{config.api_port}")

    # Run bot
    asyncio.run(bot.run())


def generate_config():
    """Generate a default config file."""
    config = BotConfig()
    save_config(config, "bot_config.json")
    print("Generated bot_config.json")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "generate-config":
        generate_config()
    else:
        main()
