"""Kraken Futures/Derivatives REST + WebSocket connector."""
import asyncio
import hashlib
import hmac
import base64
import time
import logging
from typing import Any, Callable, Dict, List, Optional

import httpx
import websockets
import json

logger = logging.getLogger(__name__)

FUTURES_REST_URL = "https://futures.kraken.com/derivatives/api/v3"
FUTURES_WS_URL = "wss://futures.kraken.com/ws/v1"


class KrakenFuturesConnector:
    """Connector for Kraken Futures/Derivatives."""

    def __init__(self, api_key: str = "", api_secret: str = "", dry_run: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.dry_run = dry_run
        self._client = httpx.AsyncClient(timeout=30.0)
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._callbacks: Dict[str, List[Callable]] = {}
        self._running = False
        self._rate_limiter = FuturesRateLimiter()
        self._instruments: Dict[str, Dict] = {}
        self._order_counter = 0
        self._dead_man_active = False

    # --- Auth ---

    def _sign(self, endpoint: str, postdata: str = "", nonce: str = "") -> dict:
        """Sign a Futures API request."""
        if postdata:
            sha256_hash = hashlib.sha256((postdata + nonce).encode()).digest()
        else:
            sha256_hash = hashlib.sha256(nonce.encode()).digest()
        concat = endpoint.encode() + sha256_hash
        mac = hmac.new(base64.b64decode(self.api_secret), concat, hashlib.sha512)
        return {
            "APIKey": self.api_key,
            "Authent": base64.b64encode(mac.digest()).decode(),
            "Nonce": nonce,
        }

    def _generate_client_order_id(self) -> str:
        self._order_counter += 1
        return f"fbot_{int(time.time())}_{self._order_counter}"

    # --- REST Public ---

    async def get_instruments(self) -> List[Dict]:
        """Get available futures instruments."""
        await self._rate_limiter.wait()
        resp = await self._client.get(f"{FUTURES_REST_URL}/instruments")
        data = resp.json()
        instruments = data.get("instruments", [])
        self._instruments = {i["symbol"]: i for i in instruments}
        return instruments

    async def get_tickers(self) -> List[Dict]:
        await self._rate_limiter.wait()
        resp = await self._client.get(f"{FUTURES_REST_URL}/tickers")
        return resp.json().get("tickers", [])

    async def get_orderbook(self, symbol: str) -> Dict:
        await self._rate_limiter.wait()
        resp = await self._client.get(f"{FUTURES_REST_URL}/orderbook", params={"symbol": symbol})
        return resp.json().get("orderBook", {})

    async def get_candles(self, symbol: str, interval: str = "1h",
                          from_ts: Optional[int] = None, to_ts: Optional[int] = None) -> List:
        """Get OHLC candles for futures."""
        await self._rate_limiter.wait()
        # Kraken Futures uses the charts endpoint
        tick_type = "trade"
        params = {"tick_type": tick_type, "symbol": symbol, "resolution": interval}
        if from_ts:
            params["from"] = from_ts
        if to_ts:
            params["to"] = to_ts
        resp = await self._client.get(f"{FUTURES_REST_URL}/charts", params=params)
        data = resp.json()
        return data.get("candles", [])

    async def get_spread(self, symbol: str) -> float:
        """Get current spread as percentage."""
        book = await self.get_orderbook(symbol)
        if not book or "asks" not in book or "bids" not in book:
            return float('inf')
        if not book["asks"] or not book["bids"]:
            return float('inf')
        best_ask = float(book["asks"][0]["price"])
        best_bid = float(book["bids"][0]["price"])
        if best_bid == 0:
            return float('inf')
        mid = (best_ask + best_bid) / 2
        return (best_ask - best_bid) / mid * 100

    # --- REST Private ---

    async def _private_get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        nonce = str(int(time.time() * 1000))
        full_endpoint = f"/api/v3/{endpoint}"
        headers = self._sign(full_endpoint, nonce=nonce)
        await self._rate_limiter.wait()
        resp = await self._client.get(
            f"{FUTURES_REST_URL}/{endpoint}", params=params, headers=headers
        )
        return resp.json()

    async def _private_post(self, endpoint: str, data: Optional[dict] = None) -> dict:
        if not data:
            data = {}
        nonce = str(int(time.time() * 1000))
        postdata = "&".join(f"{k}={v}" for k, v in sorted(data.items()))
        full_endpoint = f"/api/v3/{endpoint}"
        headers = self._sign(full_endpoint, postdata=postdata, nonce=nonce)
        await self._rate_limiter.wait()
        resp = await self._client.post(
            f"{FUTURES_REST_URL}/{endpoint}", data=data, headers=headers
        )
        return resp.json()

    async def get_accounts(self) -> Dict:
        return await self._private_get("accounts")

    async def get_open_positions(self) -> List:
        result = await self._private_get("openpositions")
        return result.get("openPositions", [])

    async def get_open_orders(self) -> List:
        result = await self._private_get("openorders")
        return result.get("openOrders", [])

    async def get_fills(self, last_fill_time: Optional[str] = None) -> List:
        params = {}
        if last_fill_time:
            params["lastFillTime"] = last_fill_time
        result = await self._private_get("fills", params)
        return result.get("fills", [])

    async def send_order(
        self,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "lmt",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
    ) -> Dict:
        """Send a futures order."""
        if self.dry_run:
            cid = client_order_id or self._generate_client_order_id()
            return {
                "simulated": True,
                "client_order_id": cid,
                "symbol": symbol,
                "side": side,
                "size": size,
                "order_type": order_type,
            }

        cid = client_order_id or self._generate_client_order_id()
        data = {
            "orderType": order_type,  # lmt, mkt, stp, take_profit
            "symbol": symbol,
            "side": side,  # buy/sell
            "size": str(size),
            "cliOrdId": cid,
        }
        if limit_price is not None:
            data["limitPrice"] = str(limit_price)
        if stop_price is not None:
            data["stopPrice"] = str(stop_price)
        if reduce_only:
            data["reduceOnly"] = "true"

        result = await self._private_post("sendorder", data)
        if result.get("result") != "success":
            logger.error(f"Futures sendorder error: {result}")
            return {"error": result.get("error", "unknown"), "client_order_id": cid}
        result["client_order_id"] = cid
        return result

    async def cancel_order(self, order_id: Optional[str] = None,
                           cli_ord_id: Optional[str] = None) -> Dict:
        if self.dry_run:
            return {"simulated": True}
        data = {}
        if order_id:
            data["order_id"] = order_id
        if cli_ord_id:
            data["cliOrdId"] = cli_ord_id
        return await self._private_post("cancelorder", data)

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict:
        if self.dry_run:
            return {"simulated": True}
        data = {}
        if symbol:
            data["symbol"] = symbol
        return await self._private_post("cancelallorders", data)

    async def dead_man_switch(self, timeout: int = 60) -> Dict:
        """Dead man switch for futures. timeout in seconds. 0 to disable."""
        if self.dry_run:
            self._dead_man_active = timeout > 0
            return {"simulated": True, "timeout": timeout}
        data = {"timeout": str(timeout)}
        result = await self._private_post("cancelallordersafter", data)
        if result.get("result") == "success":
            self._dead_man_active = timeout > 0
        else:
            logger.error(f"Futures dead man switch error: {result}")
        return result

    async def edit_order(self, cli_ord_id: str, size: Optional[float] = None,
                         limit_price: Optional[float] = None,
                         stop_price: Optional[float] = None) -> Dict:
        if self.dry_run:
            return {"simulated": True}
        data = {"cliOrdId": cli_ord_id}
        if size is not None:
            data["size"] = str(size)
        if limit_price is not None:
            data["limitPrice"] = str(limit_price)
        if stop_price is not None:
            data["stopPrice"] = str(stop_price)
        return await self._private_post("editorder", data)

    # --- Discovery ---

    async def discover_instruments(self, watchlist: List[str]) -> Dict[str, str]:
        """Map watchlist to real instrument symbols."""
        if not self._instruments:
            await self.get_instruments()
        mapping = {}
        for wanted in watchlist:
            w_upper = wanted.upper()
            for sym, info in self._instruments.items():
                if w_upper == sym.upper() or w_upper in sym.upper():
                    if info.get("tradeable", False):
                        mapping[wanted] = sym
                        break
            if wanted not in mapping:
                logger.warning(f"Futures instrument {wanted} not found/tradeable")
        return mapping

    # --- WebSocket ---

    async def ws_connect(self, feeds: List[str], symbols: List[str]):
        """Connect to Kraken Futures WebSocket."""
        self._running = True
        while self._running:
            try:
                async with websockets.connect(FUTURES_WS_URL) as ws:
                    self._ws = ws
                    for feed in feeds:
                        sub = {
                            "event": "subscribe",
                            "feed": feed,
                            "product_ids": symbols
                        }
                        await ws.send(json.dumps(sub))
                    async for msg in ws:
                        data = json.loads(msg)
                        await self._handle_ws_message(data)
            except websockets.ConnectionClosed:
                logger.warning("Futures WS disconnected, reconnecting...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Futures WS error: {e}")
                await asyncio.sleep(10)

    async def _handle_ws_message(self, data: dict):
        feed = data.get("feed", "")
        if feed in self._callbacks:
            for cb in self._callbacks[feed]:
                try:
                    await cb(data)
                except Exception as e:
                    logger.error(f"Futures WS callback error [{feed}]: {e}")

    def on(self, feed: str, callback: Callable):
        if feed not in self._callbacks:
            self._callbacks[feed] = []
        self._callbacks[feed].append(callback)

    async def disconnect(self):
        self._running = False
        if self._ws:
            await self._ws.close()

    async def renew_dead_man_switch(self, timeout: int = 60):
        return await self.dead_man_switch(timeout)

    async def close(self):
        await self.disconnect()
        await self._client.aclose()


class FuturesRateLimiter:
    """Rate limiter for Kraken Futures API."""

    def __init__(self):
        self._tokens = 50
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill = int(elapsed * 10)  # 10 tokens/sec
            if refill > 0:
                self._tokens = min(50, self._tokens + refill)
                self._last_refill = now
            while self._tokens <= 1:
                await asyncio.sleep(0.1)
                self._tokens += 1
            self._tokens -= 1
