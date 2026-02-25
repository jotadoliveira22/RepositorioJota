"""
Agent Research Platform — FastAPI Backend
Orchestrates the Scout → Analyst → Writing → Optimizer pipeline.
"""
import json
import os
import re
import asyncio
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from backend.storage import (
    create_run, get_run, list_runs, update_agent_result,
    append_log, delete_run, export_run_json, export_run_markdown,
)
from backend.sources import validate_urls, RESEARCH_CATEGORIES, ALL_ALLOWED_SOURCES
from backend.agents import scout, analyst, writer, optimizer

load_dotenv()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Agent Research Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RunConfig(BaseModel):
    topic: str
    category: str = "General"
    language: str = "ES+EN"
    objective: str = "Organic"
    formats: list[str] = []
    tone: str = "professional"
    length: str = "medium"
    strict_sources: bool = True
    extra_urls: list[str] = []
    agents_enabled: dict = {}


class CreateRunRequest(BaseModel):
    config: RunConfig


class ValidateUrlsRequest(BaseModel):
    urls: list[str]


# ---------------------------------------------------------------------------
# Helper: Claude streaming call
# ---------------------------------------------------------------------------

# Models tried in order until one responds with HTTP 200
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro",
]

GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:streamGenerateContent?alt=sse&key={key}"
)

# Cache the first working model so we don't probe on every request
_working_model: str | None = None


async def _probe_models(api_key: str) -> str | None:
    """Return the first Gemini model that answers generateContent with HTTP 200."""
    global _working_model
    if _working_model:
        return _working_model
    probe_payload = {
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        for model in GEMINI_MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            try:
                resp = await client.post(url, json=probe_payload)
                print(f"[Gemini probe] {model} → {resp.status_code}", flush=True)
                if resp.status_code == 200:
                    _working_model = model
                    return model
                if resp.status_code == 401:
                    # Key is definitively invalid
                    print("[Gemini probe] 401 — API key invalid, aborting probe", flush=True)
                    return None
                if resp.status_code == 400:
                    # Google returns 400 for invalid API keys
                    try:
                        err_text = resp.text.lower()
                        if "api key not valid" in err_text or "api_key_invalid" in err_text:
                            print("[Gemini probe] 400 — API key not valid, aborting probe", flush=True)
                            return None
                    except Exception:
                        pass
                # 403 = model-specific restriction (not a bad key), 404 = model not found,
                # 429 = rate limited — continue trying the next model
                print(f"[Gemini probe] {model} → {resp.status_code}, trying next model", flush=True)
            except Exception as exc:
                print(f"[Gemini probe] {model} → exception: {exc}", flush=True)
    return None


async def call_claude_stream(system: str, user_msg: str) -> AsyncIterator[tuple[str, str]]:
    """
    Yields (event_type, data) tuples:
      - ("text", "...") for streaming text chunks
      - ("done", json_string) when finished
      - ("error", message) on error
    Auto-detects the best available Gemini model and retries on rate limit (429).
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        yield ("error", "GEMINI_API_KEY not set in environment")
        return

    model = await _probe_models(api_key)
    if not model:
        yield ("error", (
            "No se encontró ningún modelo Gemini disponible para esta API key. "
            "Verifica que la clave sea válida en aistudio.google.com y que tenga "
            "acceso a la API de Gemini."
        ))
        return

    print(f"[Gemini] Usando modelo: {model}", flush=True)
    url = GEMINI_URL_TEMPLATE.format(model=model, key=api_key)
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {"maxOutputTokens": 8000, "temperature": 0.7},
    }

    for attempt in range(4):
        full_text = ""
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code == 400:
                        body = await response.aread()
                        print(f"[Gemini 400] {body[:300]}", flush=True)
                        yield ("error", "Solicitud inválida a la API de Gemini.")
                        return
                    if response.status_code in (401, 403):
                        body = await response.aread()
                        print(f"[Gemini {response.status_code}] {body[:300]}", flush=True)
                        yield ("error", "API key inválida. Revisa GEMINI_API_KEY.")
                        return
                    if response.status_code == 429:
                        body = await response.aread()
                        try:
                            err_json = json.loads(body)
                            err_msg = err_json.get("error", {}).get("message", "")
                        except Exception:
                            err_json = {}
                            err_msg = body.decode(errors="replace") if isinstance(body, bytes) else str(body)
                        print(f"[Gemini 429] intento={attempt} mensaje={err_msg!r}", flush=True)

                        retry_match = re.search(r'retry in ([\d.]+)s', err_msg, re.IGNORECASE)
                        suggested_wait = float(retry_match.group(1)) if retry_match else None

                        err_lower = err_msg.lower()
                        is_quota = any(k in err_lower for k in (
                            "billing", "exceeded your current quota",
                            "quota_exceeded", "resource_exhausted",
                            "per day", "daily",
                        ))
                        is_retryable_rate_limit = suggested_wait is not None and suggested_wait <= 120
                        if is_quota and not is_retryable_rate_limit and attempt == 0:
                            yield ("error", f"Cuota agotada: {err_msg}. Revisa tu plan en aistudio.google.com.")
                            return
                        if attempt < 3:
                            wait_time = suggested_wait if is_retryable_rate_limit else 15
                            print(f"[Gemini 429] esperando {wait_time:.1f}s antes de reintentar...", flush=True)
                            await asyncio.sleep(wait_time)
                            continue
                        yield ("error", f"Rate limit tras 3 intentos: {err_msg}")
                        return
                    if response.status_code != 200:
                        body = await response.aread()
                        print(f"[Gemini {response.status_code}] {body[:300]}", flush=True)
                        yield ("error", f"Error de API Gemini: HTTP {response.status_code}")
                        return

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(raw)
                            for candidate in chunk.get("candidates", []):
                                for part in candidate.get("content", {}).get("parts", []):
                                    text = part.get("text", "")
                                    if text:
                                        full_text += text
                                        yield ("text", text)
                        except json.JSONDecodeError:
                            continue

            yield ("done", full_text)
            return

        except httpx.ConnectError:
            yield ("error", "Error de conexión con la API de Gemini.")
            return
        except httpx.TimeoutException:
            yield ("error", "Timeout al conectar con la API de Gemini.")
            return
        except Exception as exc:
            yield ("error", f"Error inesperado: {str(exc)}")
            return


def parse_json_result(raw: str, agent_name: str) -> dict:
    """Parse JSON from agent output, stripping any markdown fences."""
    text = raw.strip()
    # Remove ```json ... ``` wrappers if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        return {
            "parse_error": f"Could not parse {agent_name} JSON output: {str(e)}",
            "raw": raw[:2000],
        }


# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------

def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_frontend():
    html_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)


@app.get("/api/categories")
async def get_categories():
    return {"categories": RESEARCH_CATEGORIES}


@app.get("/api/sources")
async def get_sources():
    return {"sources": ALL_ALLOWED_SOURCES}


@app.post("/api/validate-sources")
async def validate_sources(req: ValidateUrlsRequest):
    return validate_urls(req.urls)


# ---------------------------------------------------------------------------
# Run management
# ---------------------------------------------------------------------------

@app.post("/api/runs")
async def create_new_run(req: CreateRunRequest):
    config_dict = req.config.model_dump()

    # Validate and split extra URLs
    url_validation = validate_urls(config_dict.get("extra_urls", []))
    config_dict["extra_approved_urls"] = [item["url"] for item in url_validation["approved"]]
    config_dict["extra_rejected_urls"] = [item for item in url_validation["rejected"]]

    run = create_run(config_dict)
    return {
        "run_id": run["id"],
        "rejected_urls": url_validation["rejected"],
        "approved_urls": url_validation["approved"],
    }


@app.get("/api/runs")
async def list_all_runs():
    return {"runs": list_runs()}


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.delete("/api/runs/{run_id}")
async def delete_run_endpoint(run_id: str):
    if delete_run(run_id):
        return {"message": "Run deleted"}
    raise HTTPException(status_code=404, detail="Run not found")


@app.get("/api/runs/{run_id}/export/json")
async def export_json(run_id: str):
    data = export_run_json(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="Run not found")
    return data


@app.get("/api/runs/{run_id}/export/markdown")
async def export_markdown(run_id: str):
    md = export_run_markdown(run_id)
    if md is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return HTMLResponse(content=md, media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------------------
# Agent streaming endpoints
# ---------------------------------------------------------------------------

@app.get("/api/runs/{run_id}/agents/scout/stream")
async def stream_scout(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    config = run["config"]

    async def generate():
        update_agent_result(run_id, "scout", "running")
        append_log(run_id, "Scout Agent iniciado")
        yield sse_event({"type": "status", "agent": "scout", "status": "running"})

        full_text = ""
        async for event_type, data in call_claude_stream(
            scout.SYSTEM_PROMPT, scout.build_user_prompt(config)
        ):
            if event_type == "text":
                full_text += data
                yield sse_event({"type": "text", "agent": "scout", "content": data})
            elif event_type == "done":
                result = parse_json_result(full_text, "scout")
                update_agent_result(run_id, "scout", "done", content=result)
                append_log(run_id, f"Scout Agent completado. Confianza: {result.get('confidence', '?')}")
                yield sse_event({"type": "done", "agent": "scout", "result": result})
            elif event_type == "error":
                update_agent_result(run_id, "scout", "error", error=data)
                append_log(run_id, f"Scout Agent error: {data}", level="error")
                yield sse_event({"type": "error", "agent": "scout", "error": data})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs/{run_id}/agents/analyst/stream")
async def stream_analyst(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    config = run["config"]
    scout_result = run["results"].get("scout", {}).get("content")

    if not scout_result:
        raise HTTPException(status_code=400, detail="Scout must run before Analyst")

    async def generate():
        update_agent_result(run_id, "analyst", "running")
        append_log(run_id, "Analyst Agent iniciado")
        yield sse_event({"type": "status", "agent": "analyst", "status": "running"})

        full_text = ""
        async for event_type, data in call_claude_stream(
            analyst.SYSTEM_PROMPT, analyst.build_user_prompt(config, scout_result)
        ):
            if event_type == "text":
                full_text += data
                yield sse_event({"type": "text", "agent": "analyst", "content": data})
            elif event_type == "done":
                result = parse_json_result(full_text, "analyst")
                update_agent_result(run_id, "analyst", "done", content=result)
                append_log(run_id, "Analyst Agent completado")
                yield sse_event({"type": "done", "agent": "analyst", "result": result})
            elif event_type == "error":
                update_agent_result(run_id, "analyst", "error", error=data)
                append_log(run_id, f"Analyst Agent error: {data}", level="error")
                yield sse_event({"type": "error", "agent": "analyst", "error": data})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs/{run_id}/agents/writer/stream")
async def stream_writer(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    config = run["config"]
    scout_result = run["results"].get("scout", {}).get("content")
    analyst_result = run["results"].get("analyst", {}).get("content")

    if not scout_result or not analyst_result:
        raise HTTPException(status_code=400, detail="Scout and Analyst must run before Writer")

    async def generate():
        update_agent_result(run_id, "writer", "running")
        append_log(run_id, "Writing Agent iniciado")
        yield sse_event({"type": "status", "agent": "writer", "status": "running"})

        full_text = ""
        async for event_type, data in call_claude_stream(
            writer.SYSTEM_PROMPT, writer.build_user_prompt(config, scout_result, analyst_result)
        ):
            if event_type == "text":
                full_text += data
                yield sse_event({"type": "text", "agent": "writer", "content": data})
            elif event_type == "done":
                result = parse_json_result(full_text, "writer")
                update_agent_result(run_id, "writer", "done", content=result)
                append_log(run_id, "Writing Agent completado")
                yield sse_event({"type": "done", "agent": "writer", "result": result})
            elif event_type == "error":
                update_agent_result(run_id, "writer", "error", error=data)
                append_log(run_id, f"Writing Agent error: {data}", level="error")
                yield sse_event({"type": "error", "agent": "writer", "error": data})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs/{run_id}/agents/optimizer/stream")
async def stream_optimizer(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    config = run["config"]
    writer_result = run["results"].get("writer", {}).get("content")

    if not writer_result:
        raise HTTPException(status_code=400, detail="Writer must run before Optimizer")

    async def generate():
        update_agent_result(run_id, "optimizer", "running")
        append_log(run_id, "Optimizer Agent iniciado")
        yield sse_event({"type": "status", "agent": "optimizer", "status": "running"})

        full_text = ""
        async for event_type, data in call_claude_stream(
            optimizer.SYSTEM_PROMPT, optimizer.build_user_prompt(config, writer_result)
        ):
            if event_type == "text":
                full_text += data
                yield sse_event({"type": "text", "agent": "optimizer", "content": data})
            elif event_type == "done":
                result = parse_json_result(full_text, "optimizer")
                update_agent_result(run_id, "optimizer", "done", content=result)
                append_log(run_id, "Optimizer Agent completado")
                yield sse_event({"type": "done", "agent": "optimizer", "result": result})
            elif event_type == "error":
                update_agent_result(run_id, "optimizer", "error", error=data)
                append_log(run_id, f"Optimizer Agent error: {data}", level="error")
                yield sse_event({"type": "error", "agent": "optimizer", "error": data})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Full pipeline streaming (runs all 4 agents sequentially)
# ---------------------------------------------------------------------------

@app.get("/api/runs/{run_id}/pipeline/stream")
async def stream_pipeline(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    config = run["config"]
    agents_enabled = config.get("agents_enabled", {
        "scout": True, "analyst": True, "writer": True, "optimizer": True
    })

    async def generate():
        append_log(run_id, "Pipeline completo iniciado")
        yield sse_event({"type": "pipeline_start"})

        results = {"scout": None, "analyst": None, "writer": None}

        # ── 1. SCOUT ────────────────────────────────────────────────────────
        if agents_enabled.get("scout", True):
            update_agent_result(run_id, "scout", "running")
            yield sse_event({"type": "status", "agent": "scout", "status": "running"})
            append_log(run_id, "Pipeline: Scout iniciado")

            full_text = ""
            async for event_type, data in call_claude_stream(
                scout.SYSTEM_PROMPT, scout.build_user_prompt(config)
            ):
                if event_type == "text":
                    full_text += data
                    yield sse_event({"type": "text", "agent": "scout", "content": data})
                elif event_type == "done":
                    results["scout"] = parse_json_result(full_text, "scout")
                    update_agent_result(run_id, "scout", "done", content=results["scout"])
                    append_log(run_id, "Pipeline: Scout completado")
                    yield sse_event({"type": "done", "agent": "scout", "result": results["scout"]})
                elif event_type == "error":
                    update_agent_result(run_id, "scout", "error", error=data)
                    append_log(run_id, f"Pipeline: Scout error — {data}", level="error")
                    yield sse_event({"type": "error", "agent": "scout", "error": data})
                    yield sse_event({"type": "pipeline_abort", "reason": "Scout failed"})
                    return

        # ── 2. ANALYST ──────────────────────────────────────────────────────
        await asyncio.sleep(5)
        if agents_enabled.get("analyst", True):
            scout_content = results.get("scout") or get_run(run_id)["results"]["scout"].get("content")
            if not scout_content:
                yield sse_event({"type": "error", "agent": "analyst", "error": "No Scout result available"})
                return

            update_agent_result(run_id, "analyst", "running")
            yield sse_event({"type": "status", "agent": "analyst", "status": "running"})
            append_log(run_id, "Pipeline: Analyst iniciado")

            full_text = ""
            async for event_type, data in call_claude_stream(
                analyst.SYSTEM_PROMPT, analyst.build_user_prompt(config, scout_content)
            ):
                if event_type == "text":
                    full_text += data
                    yield sse_event({"type": "text", "agent": "analyst", "content": data})
                elif event_type == "done":
                    results["analyst"] = parse_json_result(full_text, "analyst")
                    update_agent_result(run_id, "analyst", "done", content=results["analyst"])
                    append_log(run_id, "Pipeline: Analyst completado")
                    yield sse_event({"type": "done", "agent": "analyst", "result": results["analyst"]})
                elif event_type == "error":
                    update_agent_result(run_id, "analyst", "error", error=data)
                    append_log(run_id, f"Pipeline: Analyst error — {data}", level="error")
                    yield sse_event({"type": "error", "agent": "analyst", "error": data})
                    yield sse_event({"type": "pipeline_abort", "reason": "Analyst failed"})
                    return

        # ── 3. WRITER ───────────────────────────────────────────────────────
        await asyncio.sleep(5)
        if agents_enabled.get("writer", True):
            scout_content = results.get("scout") or get_run(run_id)["results"]["scout"].get("content")
            analyst_content = results.get("analyst") or get_run(run_id)["results"]["analyst"].get("content")
            if not scout_content or not analyst_content:
                yield sse_event({"type": "error", "agent": "writer", "error": "Missing Scout/Analyst results"})
                return

            update_agent_result(run_id, "writer", "running")
            yield sse_event({"type": "status", "agent": "writer", "status": "running"})
            append_log(run_id, "Pipeline: Writer iniciado")

            full_text = ""
            async for event_type, data in call_claude_stream(
                writer.SYSTEM_PROMPT, writer.build_user_prompt(config, scout_content, analyst_content)
            ):
                if event_type == "text":
                    full_text += data
                    yield sse_event({"type": "text", "agent": "writer", "content": data})
                elif event_type == "done":
                    results["writer"] = parse_json_result(full_text, "writer")
                    update_agent_result(run_id, "writer", "done", content=results["writer"])
                    append_log(run_id, "Pipeline: Writer completado")
                    yield sse_event({"type": "done", "agent": "writer", "result": results["writer"]})
                elif event_type == "error":
                    update_agent_result(run_id, "writer", "error", error=data)
                    append_log(run_id, f"Pipeline: Writer error — {data}", level="error")
                    yield sse_event({"type": "error", "agent": "writer", "error": data})
                    yield sse_event({"type": "pipeline_abort", "reason": "Writer failed"})
                    return

        # ── 4. OPTIMIZER ────────────────────────────────────────────────────
        await asyncio.sleep(5)
        if agents_enabled.get("optimizer", True):
            writer_content = results.get("writer") or get_run(run_id)["results"]["writer"].get("content")
            if not writer_content:
                yield sse_event({"type": "error", "agent": "optimizer", "error": "No Writer result available"})
                return

            update_agent_result(run_id, "optimizer", "running")
            yield sse_event({"type": "status", "agent": "optimizer", "status": "running"})
            append_log(run_id, "Pipeline: Optimizer iniciado")

            full_text = ""
            async for event_type, data in call_claude_stream(
                optimizer.SYSTEM_PROMPT, optimizer.build_user_prompt(config, writer_content)
            ):
                if event_type == "text":
                    full_text += data
                    yield sse_event({"type": "text", "agent": "optimizer", "content": data})
                elif event_type == "done":
                    result = parse_json_result(full_text, "optimizer")
                    update_agent_result(run_id, "optimizer", "done", content=result)
                    append_log(run_id, "Pipeline: Optimizer completado")
                    yield sse_event({"type": "done", "agent": "optimizer", "result": result})
                elif event_type == "error":
                    update_agent_result(run_id, "optimizer", "error", error=data)
                    append_log(run_id, f"Pipeline: Optimizer error — {data}", level="error")
                    yield sse_event({"type": "error", "agent": "optimizer", "error": data})

        append_log(run_id, "Pipeline completo finalizado")
        yield sse_event({"type": "pipeline_done"})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
