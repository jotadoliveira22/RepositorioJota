"""FastAPI server for dashboard and bot control."""
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# These will be set by the orchestrator at startup
_bot_ref = None


class ModeChange(BaseModel):
    mode: str  # dry-run, shadow, live
    confirm: bool = False


def create_app(bot=None) -> FastAPI:
    global _bot_ref
    _bot_ref = bot

    app = FastAPI(title="Kraken Trading Bot", version="1.0.0")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return _get_dashboard_html()

    @app.get("/api/status")
    async def get_status():
        if not _bot_ref:
            return {"status": "not_initialized"}
        return {
            "status": _bot_ref.status,
            "mode": _bot_ref.config.mode,
            "uptime": _bot_ref.uptime,
            "is_paused": _bot_ref.risk.is_paused,
            "kill_reason": _bot_ref.risk.kill_reason,
        }

    @app.get("/api/portfolio")
    async def get_portfolio():
        if not _bot_ref:
            raise HTTPException(404, "Bot not initialized")
        return _bot_ref.portfolio.get_summary()

    @app.get("/api/positions")
    async def get_positions(market_type: Optional[str] = None):
        if not _bot_ref:
            raise HTTPException(404)
        positions = _bot_ref.db.get_open_positions()
        if market_type:
            positions = [p for p in positions if p["market_type"] == market_type]
        return {"positions": positions}

    @app.get("/api/orders")
    async def get_orders(status: Optional[str] = None, limit: int = 50):
        if not _bot_ref:
            raise HTTPException(404)
        if status == "open":
            return {"orders": _bot_ref.db.get_open_orders()}
        return {"orders": _bot_ref.db.get_recent_orders(limit)}

    @app.get("/api/signals")
    async def get_signals(limit: int = 50):
        if not _bot_ref:
            raise HTTPException(404)
        return {"signals": _bot_ref.db.get_recent_signals(limit)}

    @app.get("/api/fills")
    async def get_fills(limit: int = 50):
        if not _bot_ref:
            raise HTTPException(404)
        return {"fills": _bot_ref.db.get_recent_fills(limit)}

    @app.get("/api/equity")
    async def get_equity(limit: int = 500):
        if not _bot_ref:
            raise HTTPException(404)
        return {"history": _bot_ref.db.get_equity_history(limit)}

    @app.get("/api/events")
    async def get_events(severity: Optional[str] = None, limit: int = 100):
        if not _bot_ref:
            raise HTTPException(404)
        return {"events": _bot_ref.db.get_recent_events(limit, severity)}

    @app.get("/api/metrics")
    async def get_metrics():
        if not _bot_ref:
            raise HTTPException(404)
        daily_dd, weekly_dd = _bot_ref.risk.get_drawdown()
        return {
            "equity": _bot_ref.risk.equity,
            "daily_dd_pct": daily_dd,
            "weekly_dd_pct": weekly_dd,
            "trades_today": _bot_ref.db.get_trades_today_count(),
            "open_positions": len(_bot_ref.db.get_open_positions()),
            "mode": _bot_ref.config.mode,
            "is_paused": _bot_ref.risk.is_paused,
        }

    # --- Control endpoints ---

    @app.post("/api/pause")
    async def pause_bot():
        if not _bot_ref:
            raise HTTPException(404)
        _bot_ref.risk.pause("Manual pause via API")
        return {"status": "paused"}

    @app.post("/api/resume")
    async def resume_bot():
        if not _bot_ref:
            raise HTTPException(404)
        _bot_ref.risk.resume()
        return {"status": "resumed"}

    @app.post("/api/kill")
    async def kill_switch():
        if not _bot_ref:
            raise HTTPException(404)
        _bot_ref.risk.pause("Manual kill switch via API")
        await _bot_ref.executor.close_all_positions("manual_kill")
        return {"status": "killed", "message": "All positions closed"}

    @app.post("/api/mode")
    async def change_mode(body: ModeChange):
        if not _bot_ref:
            raise HTTPException(404)
        if body.mode not in ("dry-run", "shadow", "live"):
            raise HTTPException(400, f"Invalid mode: {body.mode}")
        if body.mode == "live" and not body.confirm:
            raise HTTPException(400, "Set confirm=true to switch to live mode")
        old_mode = _bot_ref.config.mode
        _bot_ref.config.mode = body.mode
        _bot_ref.db.log_event("WARNING", "mode_change",
                             f"Mode changed: {old_mode} -> {body.mode}")
        return {"old_mode": old_mode, "new_mode": body.mode}

    return app


def _get_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kraken Trading Bot Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; }
.header { background: #161b22; padding: 16px 24px; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 20px; color: #58a6ff; }
.status-badge { padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.status-running { background: #238636; color: #fff; }
.status-paused { background: #da3633; color: #fff; }
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-bottom: 20px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
.card h3 { color: #58a6ff; font-size: 14px; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.metric { font-size: 28px; font-weight: 700; color: #f0f6fc; }
.metric-label { font-size: 12px; color: #8b949e; margin-top: 4px; }
.metric-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #21262d; }
.positive { color: #3fb950; }
.negative { color: #f85149; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px; color: #8b949e; border-bottom: 1px solid #30363d; }
td { padding: 8px; border-bottom: 1px solid #21262d; }
.btn { padding: 8px 16px; border: 1px solid #30363d; border-radius: 6px; background: #21262d; color: #c9d1d9; cursor: pointer; font-size: 13px; margin: 4px; }
.btn:hover { background: #30363d; }
.btn-danger { border-color: #f85149; color: #f85149; }
.btn-danger:hover { background: #f85149; color: #fff; }
.btn-success { border-color: #3fb950; color: #3fb950; }
.controls { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
#log-container { max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 12px; }
.log-entry { padding: 4px 0; border-bottom: 1px solid #21262d; }
</style>
</head>
<body>
<div class="header">
  <h1>Kraken Trading Bot</h1>
  <div>
    <span id="status-badge" class="status-badge status-running">Loading...</span>
    <span id="mode-badge" class="status-badge" style="background:#1f6feb;">--</span>
  </div>
</div>
<div class="container">
  <div class="controls">
    <button class="btn btn-success" onclick="apiCall('/api/resume','POST')">Resume</button>
    <button class="btn" onclick="apiCall('/api/pause','POST')">Pause</button>
    <button class="btn btn-danger" onclick="if(confirm('Kill switch?'))apiCall('/api/kill','POST')">Kill Switch</button>
  </div>
  <div class="grid">
    <div class="card">
      <h3>Equity</h3>
      <div class="metric" id="equity">$--</div>
      <div class="metric-label">Current Equity</div>
    </div>
    <div class="card">
      <h3>Drawdown</h3>
      <div class="metric-row"><span>Daily DD</span><span id="dd-daily" class="negative">--%</span></div>
      <div class="metric-row"><span>Weekly DD</span><span id="dd-weekly" class="negative">--%</span></div>
    </div>
    <div class="card">
      <h3>Activity</h3>
      <div class="metric-row"><span>Trades Today</span><span id="trades-today">--</span></div>
      <div class="metric-row"><span>Open Positions</span><span id="open-pos">--</span></div>
    </div>
  </div>
  <div class="grid">
    <div class="card" style="grid-column: span 2;">
      <h3>Open Positions</h3>
      <table>
        <thead><tr><th>Symbol</th><th>Dir</th><th>Size</th><th>Entry</th><th>Current</th><th>PnL</th><th>SL</th><th>TP</th></tr></thead>
        <tbody id="positions-body"></tbody>
      </table>
    </div>
    <div class="card">
      <h3>Recent Signals</h3>
      <div id="signals-container" style="max-height:250px;overflow-y:auto;font-size:12px;"></div>
    </div>
  </div>
  <div class="card" style="margin-top:16px;">
    <h3>Recent Events</h3>
    <div id="log-container"></div>
  </div>
</div>
<script>
async function fetchData() {
  try {
    const [metrics, positions, signals, events] = await Promise.all([
      fetch('/api/metrics').then(r=>r.json()),
      fetch('/api/positions').then(r=>r.json()),
      fetch('/api/signals?limit=20').then(r=>r.json()),
      fetch('/api/events?limit=30').then(r=>r.json()),
    ]);
    document.getElementById('equity').textContent = '$' + metrics.equity.toFixed(2);
    document.getElementById('dd-daily').textContent = metrics.daily_dd_pct.toFixed(1) + '%';
    document.getElementById('dd-weekly').textContent = metrics.weekly_dd_pct.toFixed(1) + '%';
    document.getElementById('trades-today').textContent = metrics.trades_today;
    document.getElementById('open-pos').textContent = metrics.open_positions;
    const sb = document.getElementById('status-badge');
    sb.textContent = metrics.is_paused ? 'PAUSED' : 'RUNNING';
    sb.className = 'status-badge ' + (metrics.is_paused ? 'status-paused' : 'status-running');
    document.getElementById('mode-badge').textContent = metrics.mode.toUpperCase();

    const tbody = document.getElementById('positions-body');
    tbody.innerHTML = positions.positions.map(p => `<tr>
      <td>${p.symbol}</td><td>${p.direction}</td><td>${p.size}</td>
      <td>${p.entry_price}</td><td>${p.current_price||'--'}</td>
      <td class="${(p.pnl_unrealized||0)>=0?'positive':'negative'}">${(p.pnl_unrealized||0).toFixed(4)}</td>
      <td>${p.sl_price}</td><td>${p.tp_price}</td>
    </tr>`).join('');

    const sc = document.getElementById('signals-container');
    sc.innerHTML = signals.signals.map(s => `<div class="log-entry">
      <b>${s.direction.toUpperCase()}</b> ${s.symbol} ${s.signal_type} @ ${s.entry_price} - ${s.reason}
    </div>`).join('');

    const lc = document.getElementById('log-container');
    lc.innerHTML = events.events.map(e => `<div class="log-entry">
      <span style="color:${e.severity==='CRITICAL'?'#f85149':e.severity==='ERROR'?'#f0883e':'#8b949e'}">[${e.severity}]</span>
      ${e.timestamp?.substring(11,19)||''} ${e.event_type}: ${e.message}
    </div>`).join('');
  } catch(e) { console.error('Fetch error:', e); }
}
async function apiCall(url, method) {
  try { await fetch(url, {method}); fetchData(); } catch(e) { alert('Error: '+e); }
}
fetchData();
setInterval(fetchData, 5000);
</script>
</body>
</html>"""
