from fastapi import FastAPI, HTTPException, Request, Response, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from typing import Optional
import random
import os
import sys
import base64
import httpx
from pathlib import Path

# Ensure all imports resolve relative to this file's directory
BASE_DIR = Path(__file__).parent.resolve()
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

from database import (
    init_db, get_conn, get_setting, set_setting, get_recent_topics,
    is_setup_done, set_admin_password, verify_password,
    create_session, validate_session, delete_session, cleanup_old_sessions,
)
import time
from knowledge_base import TOPIC_TEMPLATES, CONTENT_TYPES, TONES, pick_next_topic
from ai_client import generate_post, get_ollama_models, check_ollama_health
from image_client import (
    generate_images, refine_image_prompt,
    IMAGE_PROVIDERS, ASPECT_RATIOS,
)

from starlette.middleware.gzip import GZipMiddleware

app = FastAPI(title="ConnectNest Marketing Assistant")

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth Middleware ───────────────────────────────────────────────────────────
# Public paths that don't require authentication
PUBLIC_PATHS = {"/api/login", "/api/setup", "/api/auth-status", "/login", "/setup"}
PUBLIC_PREFIXES = ("/static/",)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Check session cookie
        token = request.cookies.get("session")
        if not token or not validate_session(token):
            # For API calls return 401, for pages redirect to login
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Not authenticated"},
                )
            return RedirectResponse(url="/login", status_code=302)

        return await call_next(request)


app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ── Provider status cache (30s TTL) ──────────────────────────────────────────
_provider_cache = {"data": None, "expires": 0}
PROVIDER_CACHE_TTL = 30  # seconds

@app.on_event("startup")
async def startup():
    init_db()
    cleanup_old_sessions(30)


# ── Auth Routes ──────────────────────────────────────────────────────────────

@app.get("/login")
async def login_page():
    return FileResponse(str(BASE_DIR / "static" / "login.html"))


@app.get("/setup")
async def setup_page():
    if is_setup_done():
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse(str(BASE_DIR / "static" / "login.html"))


@app.get("/api/auth-status")
async def auth_status():
    return {"setup_done": is_setup_done()}


class LoginRequest(BaseModel):
    password: str


@app.post("/api/setup")
async def setup(req: LoginRequest):
    if is_setup_done():
        raise HTTPException(status_code=400, detail="Admin password already set")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    set_admin_password(req.password)
    token = create_session()
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        key="session", value=token, httponly=True, samesite="lax", max_age=86400 * 30,
    )
    return response


@app.post("/api/login")
async def login(req: LoginRequest):
    if not is_setup_done():
        raise HTTPException(status_code=400, detail="Admin password not set — use /setup first")
    if not verify_password(req.password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    token = create_session()
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        key="session", value=token, httponly=True, samesite="lax", max_age=86400 * 30,
    )
    return response


@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token:
        delete_session(token)
    response = JSONResponse(content={"ok": True})
    response.delete_cookie("session")
    return response


@app.get("/")
async def root():
    return FileResponse(str(BASE_DIR / "static" / "index.html"))


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    ollama_url = get_setting("ollama_url", "http://localhost:11434")
    ollama_ok = await check_ollama_health(ollama_url)
    return {"status": "ok", "ollama": ollama_ok, "ollama_url": ollama_url}


@app.get("/api/provider-status")
async def provider_status():
    """Check connectivity for all configured text and image providers (cached 30s)."""
    import asyncio

    # Return cached result if fresh
    if _provider_cache["data"] and time.time() < _provider_cache["expires"]:
        return _provider_cache["data"]

    ollama_url = get_setting("ollama_url", "http://localhost:11434")
    gemini_key = get_setting("gemini_api_key", "")
    groq_key = get_setting("groq_api_key", "")
    deepseek_key = get_setting("deepseek_api_key", "")
    qwen_key = get_setting("qwen_api_key", "")
    gemini_paid_key = get_setting("gemini_paid_api_key", "")
    stability_key = get_setting("stability_api_key", "")
    openai_key = get_setting("openai_api_key", "")

    async def check_ollama():
        return await check_ollama_health(ollama_url)

    async def check_api_key_provider(url, headers, timeout=8.0):
        """Quick connectivity check — just verifies the endpoint responds."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers)
                # Any response (even 4xx for bad model) means the service is reachable
                return resp.status_code < 500
        except Exception:
            return False

    async def check_groq():
        if not groq_key or groq_key == "••••••••":
            return None  # not configured
        return await check_api_key_provider(
            "https://api.groq.com/openai/v1/models",
            {"Authorization": f"Bearer {groq_key}"},
        )

    async def check_gemini():
        if not gemini_key or gemini_key == "••••••••":
            return None
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
                )
                return resp.status_code < 500
        except Exception:
            return False

    async def check_deepseek():
        if not deepseek_key or deepseek_key == "••••••••":
            return None
        return await check_api_key_provider(
            "https://api.deepseek.com/models",
            {"Authorization": f"Bearer {deepseek_key}"},
        )

    async def check_qwen():
        if not qwen_key or qwen_key == "••••••••":
            return None
        return await check_api_key_provider(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
            {"Authorization": f"Bearer {qwen_key}"},
        )

    async def check_gemini_paid():
        if not gemini_paid_key or gemini_paid_key == "••••••••":
            return None
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_paid_key}"
                )
                return resp.status_code < 500
        except Exception:
            return False

    async def check_stability():
        if not stability_key or stability_key == "••••••••":
            return None
        return await check_api_key_provider(
            "https://api.stability.ai/v1/engines/list",
            {"Authorization": f"Bearer {stability_key}"},
        )

    async def check_openai():
        if not openai_key or openai_key == "••••••••":
            return None
        return await check_api_key_provider(
            "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {openai_key}"},
        )

    results = await asyncio.gather(
        check_ollama(), check_groq(), check_gemini(),
        check_deepseek(), check_qwen(),
        check_gemini_paid(), check_stability(), check_openai(),
        return_exceptions=True,
    )

    def status_val(r):
        if isinstance(r, Exception):
            return False
        return r  # True, False, or None

    result = {
        "text": {
            "ollama": {"online": status_val(results[0]), "url": ollama_url},
            "groq": {"online": status_val(results[1])},
            "gemini": {"online": status_val(results[2])},
            "deepseek": {"online": status_val(results[3])},
            "qwen": {"online": status_val(results[4])},
        },
        "image": {
            "imagen4": {"online": status_val(results[2]), "label": "Imagen 4"},
            "gemini_native": {"online": status_val(results[2]), "label": "Nano Banana"},
            "gemini_native_paid": {"online": status_val(results[5]), "label": "Nano Banana 2"},
            "stability": {"online": status_val(results[6]), "label": "Stability AI"},
            "dalle": {"online": status_val(results[7]), "label": "DALL-E 3"},
        },
    }
    _provider_cache["data"] = result
    _provider_cache["expires"] = time.time() + PROVIDER_CACHE_TTL
    return result


# ── Models ────────────────────────────────────────────────────────────────────

@app.get("/api/models")
async def list_models():
    ollama_url = get_setting("ollama_url", "http://localhost:11434")
    models = await get_ollama_models(ollama_url)
    return {"models": models}


# ── Suggestions ───────────────────────────────────────────────────────────────

@app.get("/api/suggestions")
async def get_suggestions():
    return {
        "topics": TOPIC_TEMPLATES,
        "content_types": CONTENT_TYPES,
        "tones": TONES,
    }


# ── Generate ──────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    mode: str = "quick"                     # "quick" | "manual"
    platforms: list[str] = ["instagram"]   # list of platforms
    content_type: Optional[str] = None
    topic_id: Optional[str] = None
    custom_topic: Optional[str] = None
    custom_angle: Optional[str] = None
    tone: Optional[str] = None
    ai_provider: Optional[str] = None
    ollama_model: Optional[str] = None


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    # Resolve AI provider and model
    ai_provider = req.ai_provider or get_setting("default_model", "ollama")

    # ── AI Fiesta path: return the prompt for browser-based generation ──────────
    if ai_provider == "aifiesta":
        from knowledge_base import CONNECTNEST_PROFILE, PLATFORM_GUIDELINES
        recent = get_recent_topics(20)
        tmpl = pick_next_topic(recent) if (req.mode == "quick" or not req.topic_id) else \
               next((t for t in TOPIC_TEMPLATES if t["id"] == req.topic_id), TOPIC_TEMPLATES[0])
        topic_name = req.custom_topic or tmpl["topic"]
        angle = req.custom_angle or random.choice(tmpl["angles"])
        content_type = req.content_type or random.choice(CONTENT_TYPES)
        tone = req.tone or random.choice(TONES)
        platforms = req.platforms or ["instagram"]
        platform = platforms[0]
        pg = PLATFORM_GUIDELINES.get(platform, {})
        prompt = (
            f"{CONNECTNEST_PROFILE}\n\n"
            f"Platform: {platform.upper()} | Content type: {content_type} | "
            f"Topic: {topic_name} | Angle: {angle} | Tone: {tone}\n"
            f"Platform notes: {pg.get('format_notes','')}\n\n"
            f"Write ONE {platform} post. "
            f"Output ONLY valid JSON: "
            f'{{\"caption\": \"...\", \"hashtags\": \"#tag1 #tag2 ...\", '
            f'\"hook\": \"opening line\", \"cta\": \"call to action\", '
            f'\"image_suggestion\": \"photo/graphic description\"}}'
        )
        return {
            "aifiesta_mode": True,
            "prompt": prompt,
            "platform": platform,
            "topic": topic_name,
            "content_type": content_type,
            "tone": tone,
            "import_url": "/api/import",
            "message": "Send this prompt to AI Fiesta, then POST the best response to /api/import",
        }
    ollama_model = req.ollama_model or get_setting("default_ollama_model", "llama3.2")
    ollama_url = get_setting("ollama_url", "http://localhost:11434")

    # Collect API keys
    api_keys = {
        "groq": get_setting("groq_api_key", ""),
        "gemini": get_setting("gemini_api_key", ""),
        "deepseek": get_setting("deepseek_api_key", ""),
        "qwen": get_setting("qwen_api_key", ""),
    }

    # Resolve topic
    if req.mode == "quick" or not req.topic_id:
        recent = get_recent_topics(20)
        tmpl = pick_next_topic(recent)
        topic_name = tmpl["topic"]
        angle = random.choice(tmpl["angles"])
    else:
        tmpl = next((t for t in TOPIC_TEMPLATES if t["id"] == req.topic_id), TOPIC_TEMPLATES[0])
        topic_name = req.custom_topic or tmpl["topic"]
        angle = req.custom_angle or random.choice(tmpl["angles"])

    content_type = req.content_type or random.choice(CONTENT_TYPES)
    tone = req.tone or random.choice(TONES)

    results = []
    errors = []

    for platform in req.platforms:
        try:
            post = await generate_post(
                platform=platform,
                content_type=content_type,
                topic=topic_name,
                angle=angle,
                tone=tone,
                ai_provider=ai_provider,
                ollama_url=ollama_url,
                ollama_model=ollama_model,
                api_keys=api_keys,
            )

            # Save to DB
            conn = get_conn()
            cursor = conn.execute(
                """INSERT INTO content
                   (platform, content_type, topic, caption, hashtags,
                    image_suggestion, hook, cta, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')""",
                (
                    platform,
                    content_type,
                    topic_name,
                    post.get("caption", ""),
                    post.get("hashtags", ""),
                    post.get("image_suggestion", ""),
                    post.get("hook", ""),
                    post.get("cta", ""),
                ),
            )
            conn.commit()
            new_id = cursor.lastrowid

            row = conn.execute("SELECT * FROM content WHERE id = ?", (new_id,)).fetchone()
            conn.close()

            results.append(dict(row))
        except Exception as e:
            errors.append({"platform": platform, "error": str(e)})

    return {
        "generated": results,
        "errors": errors,
        "topic": topic_name,
        "angle": angle,
        "content_type": content_type,
        "tone": tone,
    }


# ── Content Library ───────────────────────────────────────────────────────────

@app.get("/api/content")
async def list_content(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    conn = get_conn()
    query = "SELECT * FROM content WHERE 1=1"
    count_query = "SELECT COUNT(*) as cnt FROM content WHERE 1=1"
    params = []
    if platform:
        query += " AND platform = ?"
        count_query += " AND platform = ?"
        params.append(platform)
    if status:
        query += " AND status = ?"
        count_query += " AND status = ?"
        params.append(status)
    if search:
        query += " AND (caption LIKE ? OR topic LIKE ? OR hashtags LIKE ?)"
        count_query += " AND (caption LIKE ? OR topic LIKE ? OR hashtags LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])
    total = conn.execute(count_query, tuple(params)).fetchone()["cnt"]
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return {"content": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@app.post("/api/content/bulk-action")
async def bulk_action(body: dict):
    """Approve or delete multiple content items at once."""
    ids = body.get("ids", [])
    action = body.get("action", "")
    if not ids or action not in ("approve", "delete", "posted"):
        raise HTTPException(status_code=400, detail="Provide ids[] and action (approve|delete|posted)")
    conn = get_conn()
    placeholders = ",".join("?" * len(ids))
    if action == "delete":
        conn.execute(f"DELETE FROM content WHERE id IN ({placeholders})", tuple(ids))
    else:
        new_status = "approved" if action == "approve" else "posted"
        conn.execute(
            f"UPDATE content SET status = ? WHERE id IN ({placeholders})",
            tuple([new_status] + ids),
        )
    conn.commit()
    conn.close()
    return {"ok": True, "affected": len(ids)}


@app.get("/api/content/{item_id}")
async def get_content(item_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM content WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return dict(row)


class ContentUpdate(BaseModel):
    caption: Optional[str] = None
    hashtags: Optional[str] = None
    image_suggestion: Optional[str] = None
    status: Optional[str] = None


@app.put("/api/content/{item_id}")
async def update_content(item_id: int, update: ContentUpdate):
    conn = get_conn()
    row = conn.execute("SELECT * FROM content WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Not found")

    fields = []
    values = []
    if update.caption is not None:
        fields.append("caption = ?")
        values.append(update.caption)
    if update.hashtags is not None:
        fields.append("hashtags = ?")
        values.append(update.hashtags)
    if update.image_suggestion is not None:
        fields.append("image_suggestion = ?")
        values.append(update.image_suggestion)
    if update.status is not None:
        fields.append("status = ?")
        values.append(update.status)
        if update.status == "posted":
            fields.append("posted_at = CURRENT_TIMESTAMP")

    if fields:
        values.append(item_id)
        conn.execute(f"UPDATE content SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    row = conn.execute("SELECT * FROM content WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return dict(row)


@app.delete("/api/content/{item_id}")
async def delete_content(item_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM content WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"deleted": item_id}


# ── Import (pre-generated content, e.g. from AI Fiesta browser) ──────────────

class ImportRequest(BaseModel):
    platform: str
    content_type: Optional[str] = "General"
    topic: Optional[str] = "ConnectNest"
    caption: str
    hashtags: Optional[str] = ""
    image_suggestion: Optional[str] = ""
    hook: Optional[str] = ""
    cta: Optional[str] = ""
    source: Optional[str] = "ai_fiesta"   # e.g. "ai_fiesta", "manual"
    model_used: Optional[str] = ""


@app.post("/api/import")
async def import_content(req: ImportRequest):
    """Save pre-generated content directly to the library (bypasses AI generation)."""
    conn = get_conn()
    cursor = conn.execute(
        """INSERT INTO content
           (platform, content_type, topic, caption, hashtags,
            image_suggestion, hook, cta, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')""",
        (
            req.platform,
            req.content_type,
            req.topic,
            req.caption,
            req.hashtags,
            req.image_suggestion,
            req.hook,
            req.cta,
        ),
    )
    conn.commit()
    new_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM content WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return {"imported": dict(row)}


# ── Image Generation ──────────────────────────────────────────────────────────

@app.get("/api/image-providers")
async def list_image_providers():
    return {"providers": IMAGE_PROVIDERS, "aspect_ratios": ASPECT_RATIOS}


class RefinePromptRequest(BaseModel):
    content_id: int
    custom_prompt: Optional[str] = None


@app.post("/api/refine-image-prompt")
async def refine_prompt(req: RefinePromptRequest):
    """Refine a content item's image_suggestion into a detailed image gen prompt."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM content WHERE id = ?", (req.content_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Content not found")

    if req.custom_prompt:
        return {"prompt": req.custom_prompt}

    gemini_key = get_setting("gemini_api_key", "")
    if not gemini_key:
        # Fall back to the raw image_suggestion if no API key
        return {"prompt": row["image_suggestion"] or "A modern smart home interior with connected devices"}

    try:
        refined = await refine_image_prompt(
            image_suggestion=row["image_suggestion"] or "Smart home interior",
            caption=row["caption"] or "",
            platform=row["platform"] or "instagram",
            api_key=gemini_key,
        )
        return {"prompt": refined}
    except Exception as e:
        # Fall back to raw suggestion on error
        return {"prompt": row["image_suggestion"] or "A modern smart home interior with connected devices"}


class GenerateImageRequest(BaseModel):
    content_id: int
    prompt: str
    provider: str = "imagen4"
    num_images: int = 4
    aspect_ratio: str = "1:1"


@app.post("/api/generate-image")
async def generate_image(req: GenerateImageRequest):
    """Generate images for a content item. Returns base64 images for selection."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM content WHERE id = ?", (req.content_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Content not found")

    # Collect all image gen API keys
    api_keys = {
        "gemini": get_setting("gemini_api_key", ""),
        "gemini_paid": get_setting("gemini_paid_api_key", ""),
        "stability": get_setting("stability_api_key", ""),
        "openai": get_setting("openai_api_key", ""),
    }

    try:
        images = await generate_images(
            prompt=req.prompt,
            provider=req.provider,
            api_keys=api_keys,
            num_images=req.num_images,
            aspect_ratio=req.aspect_ratio,
        )
        return {
            "images": images,
            "count": len(images),
            "provider": req.provider,
            "prompt": req.prompt,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")


class SaveImageRequest(BaseModel):
    content_id: int
    image_base64: str
    image_prompt: str
    mime_type: str = "image/png"


@app.post("/api/save-image")
async def save_image(req: SaveImageRequest):
    """Save a selected image to disk and link it to a content item."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM content WHERE id = ?", (req.content_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Content not found")

    # Ensure images directory exists
    images_dir = BASE_DIR / "static" / "images"
    images_dir.mkdir(exist_ok=True)

    # Determine file extension
    ext = "png" if "png" in req.mime_type else "jpg"
    filename = f"{req.content_id}.{ext}"
    filepath = images_dir / filename

    # Decode and save
    try:
        image_data = base64.b64decode(req.image_base64)
        with open(filepath, "wb") as f:
            f.write(image_data)
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")

    # Update DB
    image_path = f"/static/images/{filename}"
    conn.execute(
        "UPDATE content SET image_path = ?, image_prompt = ? WHERE id = ?",
        (image_path, req.image_prompt, req.content_id),
    )
    conn.commit()

    updated = conn.execute("SELECT * FROM content WHERE id = ?", (req.content_id,)).fetchone()
    conn.close()
    return {"saved": True, "image_path": image_path, "content": dict(updated)}


@app.delete("/api/content/{item_id}/image")
async def delete_image(item_id: int):
    """Remove the image from a content item."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM content WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Content not found")

    if row["image_path"]:
        filepath = BASE_DIR / row["image_path"].lstrip("/")
        if filepath.exists():
            filepath.unlink()

    conn.execute(
        "UPDATE content SET image_path = NULL, image_prompt = NULL WHERE id = ?",
        (item_id,),
    )
    conn.commit()
    conn.close()
    return {"deleted": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def stats():
    conn = get_conn()
    # Single query for all counts (was 4 separate queries)
    counts = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END) as draft,
            SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN status = 'posted' THEN 1 ELSE 0 END) as posted
        FROM content
    """).fetchone()
    by_platform = conn.execute(
        "SELECT platform, COUNT(*) as cnt FROM content GROUP BY platform"
    ).fetchall()
    recent = conn.execute(
        "SELECT * FROM content ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    conn.close()
    return {
        "total": counts["total"] or 0,
        "draft": counts["draft"] or 0,
        "approved": counts["approved"] or 0,
        "posted": counts["posted"] or 0,
        "by_platform": {r["platform"]: r["cnt"] for r in by_platform},
        "recent": [dict(r) for r in recent],
    }


# ── Settings ──────────────────────────────────────────────────────────────────

ENCRYPTED_KEYS = {
    "groq_api_key",
    "gemini_api_key",
    "deepseek_api_key",
    "qwen_api_key",
    "gemini_paid_api_key",
    "stability_api_key",
    "openai_api_key",
    "linkedin_client_id",
    "linkedin_client_secret",
    "linkedin_access_token",
    "facebook_page_id",
    "facebook_access_token",
}

SETTINGS_KEYS = [
    "ollama_url",
    "default_model",
    "default_ollama_model",
    "groq_api_key",
    "gemini_api_key",
    "deepseek_api_key",
    "qwen_api_key",
    "gemini_paid_api_key",
    "stability_api_key",
    "openai_api_key",
    "default_image_provider",
    "linkedin_client_id",
    "linkedin_client_secret",
    "linkedin_access_token",
    "facebook_page_id",
    "facebook_access_token",
]


@app.get("/api/settings")
async def get_settings():
    result = {k: "" for k in SETTINGS_KEYS}
    conn = get_conn()
    # Single query instead of 16 separate ones
    rows = conn.execute(
        "SELECT key, value, is_encrypted FROM settings"
    ).fetchall()
    conn.close()
    for row in rows:
        k = row["key"]
        if k not in result:
            continue
        if row["is_encrypted"] and row["value"]:
            result[k] = "••••••••"
        else:
            result[k] = row["value"] or ""
    return result


class SettingsUpdate(BaseModel):
    settings: dict


@app.post("/api/settings")
async def save_settings(body: SettingsUpdate):
    for key, value in body.settings.items():
        if key not in SETTINGS_KEYS:
            continue
        if not value or value == "••••••••":
            # Skip — don't overwrite with placeholder
            continue
        is_enc = key in ENCRYPTED_KEYS
        set_setting(key, value, is_encrypted=is_enc)
    return {"saved": True}
