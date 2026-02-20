"""
Local JSON-based storage for research runs.
Each run is stored as a JSON file under /data/runs/.
"""
import json
import uuid
import os
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path(__file__).parent.parent / "data" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _run_path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.json"


def create_run(config: dict) -> dict:
    """Create a new run and persist it."""
    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    run = {
        "id": run_id,
        "config": config,
        "status": "idle",
        "results": {
            "scout": {"status": "idle", "content": None, "error": None, "timestamp": None},
            "analyst": {"status": "idle", "content": None, "error": None, "timestamp": None},
            "writer": {"status": "idle", "content": None, "error": None, "timestamp": None},
            "optimizer": {"status": "idle", "content": None, "error": None, "timestamp": None},
        },
        "logs": [],
        "created_at": now,
        "updated_at": now,
    }
    _save(run)
    return run


def get_run(run_id: str) -> dict | None:
    """Load a run by ID."""
    path = _run_path(run_id)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def list_runs(limit: int = 50) -> list[dict]:
    """List recent runs, newest first."""
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    runs = []
    for f in files[:limit]:
        try:
            with open(f) as fp:
                run = json.load(fp)
                runs.append({
                    "id": run["id"],
                    "topic": run["config"].get("topic", ""),
                    "status": run["status"],
                    "created_at": run["created_at"],
                    "updated_at": run["updated_at"],
                })
        except Exception:
            pass
    return runs


def update_agent_result(run_id: str, agent: str, status: str, content=None, error=None) -> dict | None:
    """Update the result for a specific agent in a run."""
    run = get_run(run_id)
    if not run:
        return None
    now = datetime.utcnow().isoformat()
    run["results"][agent] = {
        "status": status,
        "content": content,
        "error": error,
        "timestamp": now,
    }
    run["updated_at"] = now
    # Derive overall status
    statuses = [r["status"] for r in run["results"].values()]
    if any(s == "running" for s in statuses):
        run["status"] = "running"
    elif any(s == "error" for s in statuses):
        run["status"] = "partial"
    elif all(s in ("done", "idle") for s in statuses):
        any_done = any(s == "done" for s in statuses)
        run["status"] = "done" if any_done else "idle"
    _save(run)
    return run


def append_log(run_id: str, message: str, level: str = "info") -> None:
    """Append a log entry to a run."""
    run = get_run(run_id)
    if not run:
        return
    now = datetime.utcnow().isoformat()
    run["logs"].append({"timestamp": now, "level": level, "message": message})
    run["updated_at"] = now
    _save(run)


def delete_run(run_id: str) -> bool:
    """Delete a run."""
    path = _run_path(run_id)
    if path.exists():
        path.unlink()
        return True
    return False


def _save(run: dict) -> None:
    with open(_run_path(run["id"]), "w") as f:
        json.dump(run, f, indent=2, ensure_ascii=False)


def export_run_json(run_id: str) -> dict | None:
    return get_run(run_id)


def export_run_markdown(run_id: str) -> str | None:
    """Convert a run to a Markdown document."""
    run = get_run(run_id)
    if not run:
        return None
    config = run["config"]
    results = run["results"]
    lines = [
        f"# Research Run: {config.get('topic', 'Unknown')}",
        f"**Fecha:** {run['created_at'][:10]}",
        f"**Categoría:** {config.get('category', '—')}",
        f"**Idioma:** {config.get('language', '—')}",
        f"**Objetivo:** {config.get('objective', '—')}",
        f"**Tono:** {config.get('tone', '—')}",
        "",
    ]

    agent_titles = {
        "scout": "## 📡 Scout — Investigación",
        "analyst": "## 🧠 Analyst — Insights",
        "writer": "## ✍️ Writer — Contenido",
        "optimizer": "## 🚀 Optimizer — Versión Final",
    }

    for agent, title in agent_titles.items():
        result = results.get(agent, {})
        lines.append(title)
        if result.get("status") == "done" and result.get("content"):
            content = result["content"]
            if isinstance(content, dict):
                lines.append("```json")
                lines.append(json.dumps(content, indent=2, ensure_ascii=False))
                lines.append("```")
            else:
                lines.append(str(content))
        elif result.get("status") == "error":
            lines.append(f"> ❌ Error: {result.get('error', 'Unknown error')}")
        else:
            lines.append("> _No ejecutado_")
        lines.append("")

    if run.get("logs"):
        lines.append("## 📋 Logs")
        for log in run["logs"]:
            ts = log["timestamp"][:19].replace("T", " ")
            lines.append(f"- `{ts}` [{log['level'].upper()}] {log['message']}")

    return "\n".join(lines)
