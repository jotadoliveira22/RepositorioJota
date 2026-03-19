"""Kraken Spot REST + WebSocket connector."""
import asyncio
import hashlib
import hmac
import base64
import time
import urllib.parse
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
from decimal import Decimal

import httpx
import websockets
import json

logger = logging.getLogger(__name__)

SPOT_REST_URL = "https://api.kraken.com"
SPOT_WS_URL = "wss://ws.kraken.com/v2"
SPOT_WS_AUTH_URL = "wss://ws-auth.kraken.com/v2"


class KrakenSpotConnector:
    """Connector for Kraken Spot REST API and WebSocket v2."""

    def __init__(self, api_key: str = "", api_secret: str = "", dry_run: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.dry_run = dry_run
        self._client = httpx.AsyncClient(timeout=30.0)
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_auth: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_token: Optional[str] = None
        self._callbacks: Dict[str, List[Callable]] = {}
        self._running = False
        self._rate_limiter = SpotRateLimiter()
        self._dead_man_timeout: int = 60
        self._dead_man_active: bool = False
        self._asset_pairs: Dict[str, Dict] = {}
        self._order_counter = 0

    # --- Authentication ---

    def _sign(self, urlpath: str, data: dict) -> dict:
        """Generate Kraken API signature."""
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data['nonce']) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        mac = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest())
        return {
            'API-Key': self.api_key,
            'API-Sign': sigdigest.decode()
        }

    def _nonce(self) -> int:
        return int(time.time() * 1000)

    def _generate_client_order_id(self) -> str:
        self._order_counter += 1
        return f"bot_{int(time.time())}_{self._order_counter}"

    # --- REST Public ---

    async def get_server_time(self) -> dict:
        await self._rate_limiter.wait("public")
        resp = await self._client.get(f"{SPOT_REST_URL}/0/public/Time")
        return resp.json()

    async def get_asset_pairs(self, pairs: Optional[List[str]] = None,
                              aclass_base: Optional[str] = None) -> Dict[str, Dict]:
        """Fetch tradable asset pairs."""
        await self._rate_limiter.wait("public")
        params = {}
        if pairs:
            params["pair"] = ",".join(pairs)
        if aclass_base:
            params["aclass_base"] = aclass_base
        resp = await self._client.get(f"{SPOT_REST_URL}/0/public/AssetPairs", params=params)
        data = resp.json()
        if data.get("error"):
            logger.error(f"AssetPairs error: {data['error']}")
            return {}
        self._asset_pairs.update(data.get("result", {}))
        return data.get("result", {})

    async def get_ticker(self, pair: str) -> Dict:
        await self._rate_limiter.wait("public")
        resp = await self._client.get(f"{SPOT_REST_URL}/0/public/Ticker", params={"pair": pair})
        data = resp.json()
        if data.get("error"):
            logger.error(f"Ticker error for {pair}: {data['error']}")
            return {}
        return data.get("result", {})

    async def get_ohlc(self, pair: str, interval: int = 60, since: Optional[int] = None) -> List:
        """Get OHLC data. interval in minutes (60=1H)."""
        await self._rate_limiter.wait("public")
        params = {"pair": pair, "interval": interval}
        if since:
            params["since"] = since
        resp = await self._client.get(f"{SPOT_REST_URL}/0/public/OHLC", params=params)
        data = resp.json()
        if data.get("error"):
            logger.warning(f"OHLC not available for {pair}: {data['error']}")
            return []
        result = data.get("result", {})
        for key in result:
            if key != "last":
                return result[key]
        return []

    async def get_order_book(self, pair: str, count: int = 10) -> Dict:
        await self._rate_limiter.wait("public")
        resp = await self._client.get(
            f"{SPOT_REST_URL}/0/public/Depth",
            params={"pair": pair, "count": count}
        )
        data = resp.json()
        if data.get("error"):
            return {}
        result = data.get("result", {})
        for key in result:
            return result[key]
        return {}

    async def get_spread(self, pair: str) -> float:
        """Get current bid-ask spread as percentage."""
        book = await self.get_order_book(pair, count=1)
        if not book or "asks" not in book or "bids" not in book:
            return float('inf')
        best_ask = float(book["asks"][0][0])
        best_bid = float(book["bids"][0][0])
        if best_bid == 0:
            return float('inf')
        mid = (best_ask + best_bid) / 2
        return (best_ask - best_bid) / mid * 100

    # --- REST Private ---

    async def _private_request(self, endpoint: str, data: Optional[dict] = None) -> dict:
        if not data:
            data = {}
        data["nonce"] = self._nonce()
        urlpath = f"/0/private/{endpoint}"
        headers = self._sign(urlpath, data)
        await self._rate_limiter.wait("private")
        resp = await self._client.post(
            f"{SPOT_REST_URL}{urlpath}", data=data, headers=headers
        )
        return resp.json()

    async def get_balance(self) -> Dict[str, float]:
        result = await self._private_request("Balance")
        if result.get("error"):
            logger.error(f"Balance error: {result['error']}")
            return {}
        return {k: float(v) for k, v in result.get("result", {}).items()}

    async def get_trade_balance(self, asset: str = "ZUSD") -> Dict:
        result = await self._private_request("TradeBalance", {"asset": asset})
        if result.get("error"):
            logger.error(f"TradeBalance error: {result['error']}")
            return {}
        return result.get("result", {})

    async def get_open_orders(self) -> Dict:
        result = await self._private_request("OpenOrders")
        if result.get("error"):
            return {}
        return result.get("result", {}).get("open", {})

    async def get_closed_orders(self) -> Dict:
        result = await self._private_request("ClosedOrders")
        if result.get("error"):
            return {}
        return result.get("result", {}).get("closed", {})

    async def query_orders(self, txids: List[str]) -> Dict:
        result = await self._private_request("QueryOrders", {"txid": ",".join(txids)})
        if result.get("error"):
            return {}
        return result.get("result", {})

    async def add_order(
        self,
        pair: str,
        direction: str,
        order_type: str,
        volume: float,
        price: Optional[float] = None,
        price2: Optional[float] = None,
        leverage: Optional[str] = None,
        close_order_type: Optional[str] = None,
        close_price: Optional[float] = None,
        post_only: bool = False,
        client_order_id: Optional[str] = None,
        validate: bool = False,
    ) -> Dict:
        """Place an order on Kraken Spot."""
        if self.dry_run and not validate:
            validate = True

        cid = client_order_id or self._generate_client_order_id()
        data = {
            "pair": pair,
            "type": direction,  # buy/sell
            "ordertype": order_type,  # market/limit/stop-loss/take-profit/stop-loss-limit/take-profit-limit
            "volume": str(volume),
            "cl_ord_id": cid,
        }
        if price is not None:
            data["price"] = str(price)
        if price2 is not None:
            data["price2"] = str(price2)
        if leverage:
            data["leverage"] = leverage
        if close_order_type:
            data["close[ordertype]"] = close_order_type
            if close_price:
                data["close[price]"] = str(close_price)
        if post_only:
            data["oflags"] = "post"
        if validate:
            data["validate"] = "true"

        result = await self._private_request("AddOrder", data)
        if result.get("error"):
            logger.error(f"AddOrder error: {result['error']}")
            return {"error": result["error"], "client_order_id": cid}

        order_result = result.get("result", {})
        order_result["client_order_id"] = cid
        return order_result

    async def cancel_order(self, txid: str) -> Dict:
        """Cancel a single order."""
        if self.dry_run:
            return {"count": 1, "simulated": True}
        result = await self._private_request("CancelOrder", {"txid": txid})
        if result.get("error"):
            logger.error(f"CancelOrder error: {result['error']}")
            return {"error": result["error"]}
        return result.get("result", {})

    async def cancel_all(self) -> Dict:
        """Cancel all open orders."""
        if self.dry_run:
            return {"count": 0, "simulated": True}
        result = await self._private_request("CancelAll")
        return result.get("result", {})

    async def cancel_all_after(self, timeout: int = 60) -> Dict:
        """Dead man switch - cancel all orders after timeout seconds. 0 to disable."""
        if self.dry_run:
            self._dead_man_active = timeout > 0
            return {"simulated": True, "timeout": timeout}
        result = await self._private_request("CancelAllOrdersAfter", {"timeout": timeout})
        if result.get("error"):
            logger.error(f"CancelAllOrdersAfter error: {result['error']}")
            return {"error": result["error"]}
        self._dead_man_active = timeout > 0
        return result.get("result", {})

    async def edit_order(self, txid: str, pair: str, volume: Optional[float] = None,
                         price: Optional[float] = None, price2: Optional[float] = None) -> Dict:
        """Edit/replace an existing order."""
        if self.dry_run:
            return {"simulated": True}
        data = {"txid": txid, "pair": pair}
        if volume is not None:
            data["volume"] = str(volume)
        if price is not None:
            data["price"] = str(price)
        if price2 is not None:
            data["price2"] = str(price2)
        result = await self._private_request("EditOrder", data)
        if result.get("error"):
            logger.error(f"EditOrder error: {result['error']}")
            return {"error": result["error"]}
        return result.get("result", {})

    # --- WebSocket Token ---

    async def get_ws_token(self) -> str:
        result = await self._private_request("GetWebSocketsToken")
        if result.get("error"):
            raise ConnectionError(f"WS token error: {result['error']}")
        self._ws_token = result["result"]["token"]
        return self._ws_token

    # --- WebSocket ---

    async def ws_connect(self, channels: List[str], pairs: List[str]):
        """Connect to Kraken WS v2 public feed."""
        self._running = True
        while self._running:
            try:
                async with websockets.connect(SPOT_WS_URL) as ws:
                    self._ws = ws
                    # Subscribe
                    for channel in channels:
                        sub_msg = {
                            "method": "subscribe",
                            "params": {"channel": channel, "symbol": pairs}
                        }
                        if channel == "ohlc":
                            sub_msg["params"]["interval"] = 60
                        await ws.send(json.dumps(sub_msg))

                    async for msg in ws:
                        data = json.loads(msg)
                        await self._handle_ws_message(data)
            except websockets.ConnectionClosed:
                logger.warning("Spot WS disconnected, reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Spot WS error: {e}, reconnecting in 10s...")
                await asyncio.sleep(10)

    async def ws_connect_private(self, channels: List[str]):
        """Connect to Kraken WS v2 private (auth) feed."""
        if not self._ws_token:
            await self.get_ws_token()
        self._running = True
        while self._running:
            try:
                async with websockets.connect(SPOT_WS_AUTH_URL) as ws:
                    self._ws_auth = ws
                    for channel in channels:
                        sub_msg = {
                            "method": "subscribe",
                            "params": {"channel": channel, "token": self._ws_token}
                        }
                        await ws.send(json.dumps(sub_msg))
                    async for msg in ws:
                        data = json.loads(msg)
                        await self._handle_ws_message(data)
            except websockets.ConnectionClosed:
                logger.warning("Spot private WS disconnected, reconnecting...")
                await asyncio.sleep(5)
                try:
                    await self.get_ws_token()
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Spot private WS error: {e}")
                await asyncio.sleep(10)

    async def _handle_ws_message(self, data: dict):
        channel = data.get("channel", "")
        msg_type = data.get("type", "")
        if channel in self._callbacks:
            for cb in self._callbacks[channel]:
                try:
                    await cb(data)
                except Exception as e:
                    logger.error(f"WS callback error [{channel}]: {e}")

    def on(self, channel: str, callback: Callable):
        """Register a callback for a WS channel."""
        if channel not in self._callbacks:
            self._callbacks[channel] = []
        self._callbacks[channel].append(callback)

    async def disconnect(self):
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._ws_auth:
            await self._ws_auth.close()

    # --- Dead Man Switch maintenance ---

    async def renew_dead_man_switch(self, timeout: int = 60):
        """Renew the dead man switch timer."""
        return await self.cancel_all_after(timeout)

    # --- Discovery ---

    async def discover_pairs(self, watchlist: List[str]) -> Dict[str, str]:
        """Map human-readable pair names to Kraken pair IDs."""
        all_pairs = await self.get_asset_pairs()
        # Also fetch tokenized stock pairs (xStocks)
        xstock_pairs = await self.get_asset_pairs(aclass_base="tokenized_asset")
        all_pairs.update(xstock_pairs)
        mapping = {}
        for wanted in watchlist:
            clean = wanted.replace("/", "")
            for pid, info in all_pairs.items():
                altname = info.get("altname", "")
                wsname = info.get("wsname", "")
                if clean.upper() in [pid.upper(), altname.upper(), wsname.replace("/", "").upper()]:
                    mapping[wanted] = pid
                    break
            if wanted not in mapping:
                logger.warning(f"Pair {wanted} not found on Kraken Spot")
        return mapping

    async def close(self):
        await self.disconnect()
        await self._client.aclose()


class SpotRateLimiter:
    """Simple rate limiter for Kraken Spot API."""

    def __init__(self):
        self._public_tokens = 15
        self._private_tokens = 15
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def wait(self, endpoint_type: str = "public"):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill = int(elapsed / 3)  # 1 token per 3 seconds
            if refill > 0:
                self._public_tokens = min(15, self._public_tokens + refill)
                self._private_tokens = min(15, self._private_tokens + refill)
                self._last_refill = now

            if endpoint_type == "public":
                while self._public_tokens <= 1:
                    await asyncio.sleep(1)
                    self._public_tokens += 1
                self._public_tokens -= 1
            else:
                while self._private_tokens <= 1:
                    await asyncio.sleep(1)
                    self._private_tokens += 1
                self._private_tokens -= 1
