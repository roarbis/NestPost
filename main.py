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
    is_setup_done, set_admin_password,
    create_session, validate_session, delete_session, cleanup_old_sessions,
    authenticate_user, change_user_password, get_session_user,
    list_users, create_user, delete_user, admin_reset_password, update_user,
)
import time
from knowledge_base import TOPIC_TEMPLATES, CONTENT_TYPES, TONES, pick_next_topic
from ai_client import generate_post, get_ollama_models, check_ollama_health
from image_client import (
    generate_images, refine_image_prompt, overlay_logo,
    IMAGE_PROVIDERS, ASPECT_RATIOS,
)
from video_client import (
    generate_video, generate_video_prompts, search_stock_footage,
    VIDEO_PROVIDERS, VIDEO_ASPECT_RATIOS, ATLASCLOUD_MODELS, ATLASCLOUD_MODELS_SORTED,
    upload_video_to_r2, delete_video_from_r2, is_r2_configured,
    concat_cta_video, overlay_logo_on_video,
)
from contextlib import asynccontextmanager
from starlette.middleware.gzip import GZipMiddleware


def _get_r2_config() -> dict:
    """Collect R2 settings from the database."""
    return {
        "account_id": get_setting("r2_account_id", ""),
        "access_key_id": get_setting("r2_access_key_id", ""),
        "secret_access_key": get_setting("r2_secret_access_key", ""),
        "bucket_name": get_setting("r2_bucket_name", ""),
        "public_url": get_setting("r2_public_url", ""),
    }


def run_video_cleanup():
    """Delete videos older than video_retention_days from R2 and/or DB."""
    try:
        retention_days = int(get_setting("video_retention_days", "60") or 60)
        conn = get_conn()
        old_videos = conn.execute(
            "SELECT id, video_path, video_data FROM content "
            "WHERE (video_path IS NOT NULL OR video_data IS NOT NULL) "
            "AND created_at < datetime('now', ?)",
            (f"-{retention_days} days",),
        ).fetchall()

        if not old_videos:
            conn.close()
            return 0

        r2_config = _get_r2_config()
        r2_ready = is_r2_configured(r2_config)
        deleted = 0

        for row in old_videos:
            video_path = row["video_path"] or ""
            # Delete from R2 if it's an R2 URL
            if r2_ready and video_path.startswith("http"):
                delete_video_from_r2(
                    video_url=video_path,
                    public_url=r2_config["public_url"],
                    account_id=r2_config["account_id"],
                    access_key_id=r2_config["access_key_id"],
                    secret_access_key=r2_config["secret_access_key"],
                    bucket_name=r2_config["bucket_name"],
                )
            # Clear video columns from DB
            conn.execute(
                "UPDATE content SET video_path = NULL, video_prompt = NULL, "
                "video_data = NULL, video_mime = NULL WHERE id = ?",
                (row["id"],),
            )
            deleted += 1

        conn.commit()
        conn.close()
        return deleted
    except Exception as e:
        print(f"[video cleanup] Error: {e}")
        return 0


@asynccontextmanager
async def lifespan(app):
    # Initialise DB and clean up old sessions
    init_db()
    cleanup_old_sessions(30)
    # Run video cleanup on startup
    deleted = run_video_cleanup()
    if deleted:
        print(f"[startup] Video cleanup: removed {deleted} expired video(s)")
    yield


app = FastAPI(title="ConnectNest Marketing Assistant", lifespan=lifespan)

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
PROVIDER_CACHE_TTL = 300  # seconds (5 min — provider keys rarely change)

# ── Request deduplication (prevents double-click double-charge) ───────────────
# Maps idempotency_key → (timestamp, cached_response). Expires after 30s.
_idem_cache: dict[str, tuple[float, dict]] = {}
_IDEM_TTL = 30  # seconds

def _check_idempotency(key: str | None) -> dict | None:
    """Return cached response if key was seen within TTL, else None."""
    if not key:
        return None
    entry = _idem_cache.get(key)
    if entry and time.time() - entry[0] < _IDEM_TTL:
        return entry[1]
    return None

def _store_idempotency(key: str | None, response: dict) -> None:
    """Cache response against idempotency key. Prune old entries."""
    if not key:
        return
    now = time.time()
    _idem_cache[key] = (now, response)
    # Prune expired entries to keep memory tidy
    for k in list(_idem_cache):
        if now - _idem_cache[k][0] >= _IDEM_TTL:
            del _idem_cache[k]

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
    username: str = ""
    password: str


@app.post("/api/setup")
async def setup(req: LoginRequest):
    if is_setup_done():
        raise HTTPException(status_code=400, detail="Users already exist — use /login")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    # init_db seeds default users; this path is rarely hit
    set_admin_password(req.password)
    token = create_session("masteradmin")
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        key="session", value=token, httponly=True, samesite="lax", max_age=86400 * 30,
    )
    return response


@app.post("/api/login")
async def login(req: LoginRequest):
    if not is_setup_done():
        raise HTTPException(status_code=400, detail="No users configured — use /setup first")
    if not req.username:
        raise HTTPException(status_code=400, detail="Username is required")
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_session(user["username"])
    response = JSONResponse(content={"ok": True, "user": user})
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


@app.get("/api/me")
async def current_user(request: Request):
    """Return the currently logged-in user's info plus deployment environment."""
    token = request.cookies.get("session")
    user = get_session_user(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # APP_ENV is set per-Render-service: 'staging' on nestpost-staging, unset (→production) on prod
    try:
        version = open(os.path.join(os.path.dirname(__file__), "VERSION")).read().strip()
    except Exception:
        version = "unknown"
    return {**user, "app_env": os.environ.get("APP_ENV", "production").lower(), "app_version": version}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/change-password")
async def change_password(req: ChangePasswordRequest, request: Request):
    token = request.cookies.get("session")
    user = get_session_user(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    ok = change_user_password(user["username"], req.current_password, req.new_password)
    if not ok:
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    return {"ok": True, "message": "Password changed successfully"}


# ── User Management (masteradmin only) ────────────────────────────────────

def _require_masteradmin(request: Request):
    """Helper: return user if masteradmin, else raise 403."""
    token = request.cookies.get("session")
    user = get_session_user(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user["role"] != "masteradmin":
        raise HTTPException(status_code=403, detail="Master admin access required")
    return user


@app.get("/api/users")
async def api_list_users(request: Request):
    _require_masteradmin(request)
    return {"users": list_users()}


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "admin"
    display_name: str = ""


@app.post("/api/users")
async def api_create_user(req: CreateUserRequest, request: Request):
    _require_masteradmin(request)
    if not req.username or len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if req.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be admin or viewer")
    ok = create_user(req.username, req.password, req.role, req.display_name or req.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"ok": True, "message": f"User '{req.username}' created"}


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None


@app.put("/api/users/{user_id}")
async def api_update_user(user_id: int, req: UpdateUserRequest, request: Request):
    _require_masteradmin(request)
    if req.role and req.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Role must be admin or viewer")
    ok = update_user(user_id, display_name=req.display_name, role=req.role)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


class ResetPasswordRequest(BaseModel):
    new_password: str


@app.post("/api/users/{user_id}/reset-password")
async def api_reset_password(user_id: int, req: ResetPasswordRequest, request: Request):
    _require_masteradmin(request)
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    ok = admin_reset_password(user_id, req.new_password)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "message": "Password reset successfully"}


@app.delete("/api/users/{user_id}")
async def api_delete_user(user_id: int, request: Request):
    _require_masteradmin(request)
    ok = delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot delete this user (masteradmin is protected)")
    return {"ok": True, "message": "User deleted"}


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
    atlascloud_key = get_setting("atlascloud_api_key", "")
    gemini_paid_key = get_setting("gemini_paid_api_key", "")
    stability_key = get_setting("stability_api_key", "")
    openai_key = get_setting("openai_api_key", "")

    async def check_ollama():
        return await check_ollama_health(ollama_url)

    async def check_api_key_provider(url, headers, timeout=15.0):
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
            async with httpx.AsyncClient(timeout=15.0) as client:
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

    async def check_atlascloud():
        if not atlascloud_key or atlascloud_key == "••••••••":
            return None
        return await check_api_key_provider(
            "https://api.atlascloud.ai/v1/models",
            {"Authorization": f"Bearer {atlascloud_key}"},
        )

    async def check_gemini_paid():
        if not gemini_paid_key or gemini_paid_key == "••••••••":
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
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
        check_deepseek(), check_qwen(), check_atlascloud(),
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
            "atlascloud": {"online": status_val(results[5])},
        },
        "image": {
            "imagen4": {"online": status_val(results[2]), "label": "Imagen 4"},
            "gemini_native": {"online": status_val(results[2]), "label": "Nano Banana"},
            "gemini_native_paid": {"online": status_val(results[6]), "label": "Nano Banana 2"},
            "stability": {"online": status_val(results[7]), "label": "Stability AI"},
            "dalle": {"online": status_val(results[8]), "label": "DALL-E 3"},
        },
        "video": {
            "veo3":   {"online": False,                                                                                    "paid": True,  "label": "Veo 3.1 (Google)"},
            "kling":  {"online": bool(get_setting("kling_api_key","")) and bool(get_setting("kling_secret_key","")),                    "label": "Kling AI"},
            "fal":    {"online": bool(get_setting("fal_api_key","")),                                                                   "label": "fal.ai (WAN 2.1)"},
            "atlascloud_video": {"online": bool(get_setting("atlascloud_api_key","")),          "paid": True,                          "label": "Atlas Cloud Video"},
            "runway": {"online": bool(get_setting("runway_api_key","")),                                                   "paid": True,  "label": "Runway Gen-4"},
            "luma":   {"online": bool(get_setting("luma_api_key","")),                                                     "paid": True,  "label": "Luma Dream Machine"},
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
    # Post variety controls
    variant_mode: str = "auto"              # "auto" | "pick" | "multi"
    post_format: Optional[str] = None       # used when variant_mode == "pick"
    emoji_density: str = "balanced"         # "heavy" | "balanced" | "light" | "none"


def _next_auto_format() -> str:
    """Shuffled-queue round-robin across all POST_FORMATS, with 0-1 swap guard
    to prevent back-to-back repeats across cycle boundaries."""
    from knowledge_base import POST_FORMATS
    all_formats = list(POST_FORMATS.keys())
    queue_raw = get_setting("auto_format_queue", "")
    last_used = get_setting("auto_format_last", "")
    queue = [f for f in queue_raw.split(",") if f in POST_FORMATS] if queue_raw else []
    if not queue:
        queue = all_formats.copy()
        random.shuffle(queue)
        # Guard: if the first of the fresh queue matches the last-used format, swap with index 1
        if last_used and queue and queue[0] == last_used and len(queue) > 1:
            queue[0], queue[1] = queue[1], queue[0]
    chosen = queue.pop(0)
    set_setting("auto_format_queue", ",".join(queue))
    set_setting("auto_format_last", chosen)
    return chosen


def _pick_contrast_formats() -> list[str]:
    """Pick 3 deliberately contrasting formats from 3/3/2 buckets
    (long_form, list_structured, short_punchy)."""
    from knowledge_base import FORMAT_BUCKETS
    return [
        random.choice(FORMAT_BUCKETS["long_form"]),
        random.choice(FORMAT_BUCKETS["list_structured"]),
        random.choice(FORMAT_BUCKETS["short_punchy"]),
    ]


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
        "atlascloud": get_setting("atlascloud_api_key", ""),
        "atlascloud_model": get_setting("atlascloud_model", "deepseek-v3"),
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

    # ── Resolve format(s) based on variant_mode ─────────────────────────────
    from knowledge_base import POST_FORMATS
    emoji_density = req.emoji_density if req.emoji_density in ("heavy", "balanced", "light", "none") else "balanced"

    if req.variant_mode == "multi":
        formats_to_generate = _pick_contrast_formats()
        platforms_to_use = [req.platforms[0] if req.platforms else "instagram"]
    elif req.variant_mode == "pick" and req.post_format and req.post_format in POST_FORMATS:
        formats_to_generate = [req.post_format]
        platforms_to_use = req.platforms
    else:
        # auto
        formats_to_generate = [_next_auto_format()]
        platforms_to_use = req.platforms

    results = []
    errors = []

    for platform in platforms_to_use:
        for post_format in formats_to_generate:
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
                    post_format=post_format,
                    emoji_density=emoji_density,
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

                row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (new_id,)).fetchone()
                conn.close()

                item = dict(row)
                item["post_format"] = post_format
                item["post_format_label"] = POST_FORMATS[post_format]["label"]
                results.append(item)
            except Exception as e:
                errors.append({"platform": platform, "format": post_format, "error": str(e)})

    return {
        "generated": results,
        "errors": errors,
        "topic": topic_name,
        "angle": angle,
        "content_type": content_type,
        "tone": tone,
        "variant_mode": req.variant_mode,
        "formats_used": formats_to_generate,
    }


# ── Content Library ───────────────────────────────────────────────────────────
# Exclude image_data from queries to avoid sending huge blobs in API responses
CONTENT_COLS = "id, platform, content_type, topic, caption, hashtags, image_suggestion, hook, cta, status, created_at, posted_at, image_path, image_prompt, video_path, video_prompt"

@app.get("/api/content")
async def list_content(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    conn = get_conn()
    query = f"SELECT {CONTENT_COLS} FROM content WHERE 1=1"
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
    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (item_id,)).fetchone()
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
    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (item_id,)).fetchone()
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

    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (item_id,)).fetchone()
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
    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (new_id,)).fetchone()
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
    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (req.content_id,)).fetchone()
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
    num_images: int = 2  # default 2 to save API credits; user can request up to 4
    aspect_ratio: str = "1:1"
    idempotency_key: Optional[str] = None


@app.post("/api/generate-image")
async def generate_image(req: GenerateImageRequest):
    """Generate images for a content item. Returns base64 images for selection."""
    # Dedup: return cached result if same idempotency_key seen within 30s
    cached = _check_idempotency(req.idempotency_key)
    if cached:
        return cached

    conn = get_conn()
    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (req.content_id,)).fetchone()
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
        result = {
            "images": images,
            "count": len(images),
            "provider": req.provider,
            "prompt": req.prompt,
        }
        _store_idempotency(req.idempotency_key, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")


class SaveImageRequest(BaseModel):
    content_id: int
    image_base64: str
    image_prompt: str
    mime_type: str = "image/png"


@app.post("/api/save-image")
async def save_image(req: SaveImageRequest):
    """Save a selected image to the database and link it to a content item.
    Automatically overlays the brand logo if one is configured."""
    conn = get_conn()
    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (req.content_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Content not found")

    final_b64 = req.image_base64
    final_mime = req.mime_type

    # Apply brand logo overlay if available
    logo_b64 = get_setting("brand_logo_b64", "")
    if logo_b64:
        logo_mime = get_setting("brand_logo_mime", "image/png")
        try:
            final_b64, final_mime = overlay_logo(
                image_b64=req.image_base64,
                logo_b64=logo_b64,
                image_mime=req.mime_type,
                logo_mime=logo_mime,
            )
        except Exception as e:
            # If overlay fails, save without logo rather than failing entirely
            print(f"Logo overlay failed (saving without): {e}")

    # Store image as base64 in DB (survives Render redeploys)
    image_path = f"/api/content/{req.content_id}/image-file"
    conn.execute(
        "UPDATE content SET image_path = ?, image_prompt = ?, image_data = ?, image_mime = ? WHERE id = ?",
        (image_path, req.image_prompt, final_b64, final_mime, req.content_id),
    )
    conn.commit()

    updated = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (req.content_id,)).fetchone()
    conn.close()
    return {"saved": True, "image_path": image_path, "content": dict(updated)}


@app.get("/api/content/{item_id}/image-file")
async def serve_content_image(item_id: int):
    """Serve a content image from the database."""
    conn = get_conn()
    row = conn.execute("SELECT image_data, image_mime FROM content WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if not row or not row["image_data"]:
        raise HTTPException(status_code=404, detail="No image found")
    image_bytes = base64.b64decode(row["image_data"])
    mime = row["image_mime"] or "image/png"
    return Response(content=image_bytes, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})


@app.delete("/api/content/{item_id}/image")
async def delete_image(item_id: int):
    """Remove the image from a content item."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM content WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Content not found")

    conn.execute(
        "UPDATE content SET image_path = NULL, image_prompt = NULL, image_data = NULL, image_mime = NULL WHERE id = ?",
        (item_id,),
    )
    conn.commit()
    conn.close()
    return {"deleted": True}


# ── Brand Logo ────────────────────────────────────────────────────────────────

@app.get("/api/brand-logo")
async def get_brand_logo():
    """Get the brand logo status (whether one is configured)."""
    logo_b64 = get_setting("brand_logo_b64", "")
    return {"has_logo": bool(logo_b64), "mime": get_setting("brand_logo_mime", "image/png") if logo_b64 else None}


@app.get("/api/brand-logo/image")
async def serve_brand_logo():
    """Serve the brand logo image."""
    logo_b64 = get_setting("brand_logo_b64", "")
    if not logo_b64:
        raise HTTPException(status_code=404, detail="No brand logo configured")
    mime = get_setting("brand_logo_mime", "image/png")
    return Response(
        content=base64.b64decode(logo_b64),
        media_type=mime,
        headers={"Cache-Control": "public, max-age=3600"},
    )


class UploadLogoRequest(BaseModel):
    image_base64: str
    mime_type: str = "image/png"


@app.post("/api/brand-logo")
async def upload_brand_logo(req: UploadLogoRequest):
    """Upload a new brand logo (masteradmin only)."""
    set_setting("brand_logo_b64", req.image_base64)
    set_setting("brand_logo_mime", req.mime_type)
    return {"saved": True}


@app.delete("/api/brand-logo")
async def delete_brand_logo():
    """Remove the brand logo (disables overlay)."""
    set_setting("brand_logo_b64", "")
    set_setting("brand_logo_mime", "")
    return {"deleted": True}


# ── Video Generation ───────────────────────────────────────────────────────────

@app.get("/api/video-providers")
async def list_video_providers():
    return {"providers": VIDEO_PROVIDERS, "aspect_ratios": VIDEO_ASPECT_RATIOS}


@app.get("/api/video/atlascloud-models")
async def list_atlascloud_models():
    """Return Atlas Cloud model configs sorted by cost for frontend model picker."""
    return {"models": [
        {"id": model_id, **cfg}
        for model_id, cfg in ATLASCLOUD_MODELS_SORTED
    ]}


class VideoPromptRequest(BaseModel):
    content_id: int
    model_id: str = ""


@app.post("/api/video/suggest-prompts")
async def suggest_video_prompts(req: VideoPromptRequest):
    """Generate 3 video prompt variants (cinematic, dynamic, minimal) for a content item."""
    conn = get_conn()
    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (req.content_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Content not found")

    gemini_key = get_setting("gemini_api_key", "")
    if not gemini_key:
        raise HTTPException(status_code=400, detail="Gemini API key required for video prompt generation")

    try:
        prompts = await generate_video_prompts(
            caption=row["caption"] or "",
            platform=row["platform"] or "instagram",
            image_suggestion=row["image_suggestion"] or "",
            hook=row["hook"] or "",
            api_key=gemini_key,
            model_id=req.model_id,
        )
        return {"prompts": prompts, "content_id": req.content_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Video prompt generation failed: {str(e)}")


class GenerateVideoRequest(BaseModel):
    content_id: int
    prompt: str
    provider: str = "veo3_free"
    aspect_ratio: str = "9:16"
    duration: int = 8
    use_paid: bool = False
    append_cta: bool = True
    negative_prompt: str = ""
    resolution: str = ""
    generate_audio: bool = False
    model_id: str = ""  # Atlas Cloud specific model ID
    idempotency_key: Optional[str] = None


@app.post("/api/video/generate")
async def generate_video_endpoint(req: GenerateVideoRequest):
    """Generate a video from a prompt using the selected provider.
    Returns {status, video_base64, mime_type} on success."""
    # Dedup: video generation is expensive — block duplicate clicks within 30s
    cached = _check_idempotency(req.idempotency_key)
    if cached:
        return cached

    conn = get_conn()
    row = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (req.content_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Content not found")

    # Collect video gen API keys
    api_keys = {
        "gemini": get_setting("gemini_api_key", ""),
        "kling_access": get_setting("kling_api_key", ""),    # Access Key (AK)
        "kling_secret": get_setting("kling_secret_key", ""), # Secret Key (SK)
        "runway": get_setting("runway_api_key", ""),
        "luma": get_setting("luma_api_key", ""),
        "fal": get_setting("fal_api_key", ""),
        "atlascloud": get_setting("atlascloud_api_key", ""),
        "atlascloud_video_model": req.model_id or get_setting("atlascloud_video_model", "kwaivgi/kling-v3.0-pro/text-to-video"),
    }

    try:
        result = await generate_video(
            prompt=req.prompt,
            provider=req.provider,
            api_keys=api_keys,
            aspect_ratio=req.aspect_ratio,
            duration=req.duration,
            negative_prompt=req.negative_prompt,
            resolution=req.resolution,
            generate_audio=req.generate_audio,
        )

        if result.get("status") == "rate_limited":
            return JSONResponse(status_code=429, content=result)

        if result.get("status") != "complete":
            raise HTTPException(status_code=500, detail=result.get("error", "Video generation failed"))

        video_b64 = result["video_base64"]
        mime_type = result.get("mime_type", "video/mp4")

        # Append CTA clip if configured and requested
        cta_url = get_setting("cta_video_url", "") if req.append_cta else ""
        cta_b64 = get_setting("cta_video_b64", "") if req.append_cta else ""
        if cta_url and not cta_b64:
            # Fetch CTA from R2
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=30.0) as _cl:
                    _r = await _cl.get(cta_url)
                    _r.raise_for_status()
                    import base64 as _b64
                    cta_b64 = _b64.b64encode(_r.content).decode()
            except Exception as e:
                print(f"[CTA fetch failed, skipping concat] {e}")
                cta_b64 = ""

        if cta_b64:
            try:
                video_b64 = concat_cta_video(video_b64, cta_b64, mime_type)
            except Exception as e:
                print(f"[CTA concat failed, returning raw video] {e}")

        video_result = {
            "status": "complete",
            "video_base64": video_b64,
            "mime_type": mime_type,
            "provider": req.provider,
            "prompt": req.prompt,
        }
        _store_idempotency(req.idempotency_key, video_result)
        return video_result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Video generation failed: {str(e)}")


class SaveVideoRequest(BaseModel):
    content_id: int
    video_base64: str
    video_prompt: str
    mime_type: str = "video/mp4"


@app.post("/api/video/save")
async def save_video(req: SaveVideoRequest):
    """Save a generated video.
    If R2 is configured: upload to Cloudflare R2, store public URL (no blob in DB).
    Otherwise: fall back to storing the base64 blob in the database."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM content WHERE id = ?", (req.content_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Content not found")

    # Apply brand logo overlay if one is configured (same logo used for images)
    video_b64 = req.video_base64
    logo_b64 = get_setting("brand_logo_b64", "")
    if logo_b64:
        try:
            video_b64 = overlay_logo_on_video(video_b64, logo_b64, position="top_left")
        except Exception as e:
            print(f"[Logo overlay on video failed, saving without logo] {e}")

    r2_config = _get_r2_config()
    storage_mode = "r2" if is_r2_configured(r2_config) else "blob"

    if storage_mode == "r2":
        try:
            video_url = upload_video_to_r2(
                video_base64=video_b64,
                content_id=req.content_id,
                mime_type=req.mime_type,
                account_id=r2_config["account_id"],
                access_key_id=r2_config["access_key_id"],
                secret_access_key=r2_config["secret_access_key"],
                bucket_name=r2_config["bucket_name"],
                public_url=r2_config["public_url"],
            )
            # Store URL only — no blob in DB
            conn.execute(
                "UPDATE content SET video_path = ?, video_prompt = ?, "
                "video_data = NULL, video_mime = ? WHERE id = ?",
                (video_url, req.video_prompt, req.mime_type, req.content_id),
            )
            conn.commit()
            updated = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (req.content_id,)).fetchone()
            conn.close()
            return {"saved": True, "video_path": video_url, "storage": "r2", "content": dict(updated)}
        except Exception as e:
            # R2 upload failed — fall back to blob so the user doesn't lose their video
            print(f"[R2 upload failed, falling back to blob] {e}")
            storage_mode = "blob"

    # Blob fallback (local/web server, or if R2 fails)
    video_path = f"/api/content/{req.content_id}/video-file"
    conn.execute(
        "UPDATE content SET video_path = ?, video_prompt = ?, video_data = ?, video_mime = ? WHERE id = ?",
        (video_path, req.video_prompt, video_b64, req.mime_type, req.content_id),
    )
    conn.commit()
    updated = conn.execute(f"SELECT {CONTENT_COLS} FROM content WHERE id = ?", (req.content_id,)).fetchone()
    conn.close()
    return {"saved": True, "video_path": video_path, "storage": "blob", "content": dict(updated)}


@app.get("/api/content/{item_id}/video-file")
async def serve_content_video(item_id: int):
    """Serve a content video from the database."""
    conn = get_conn()
    row = conn.execute("SELECT video_data, video_mime FROM content WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if not row or not row["video_data"]:
        raise HTTPException(status_code=404, detail="No video found")
    video_bytes = base64.b64decode(row["video_data"])
    mime = row["video_mime"] or "video/mp4"
    return Response(content=video_bytes, media_type=mime, headers={
        "Cache-Control": "public, max-age=86400",
        "Content-Disposition": f"inline; filename=video_{item_id}.mp4",
    })


@app.delete("/api/content/{item_id}/video")
async def delete_video(item_id: int):
    """Remove the video from a content item."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM content WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Content not found")

    conn.execute(
        "UPDATE content SET video_path = NULL, video_prompt = NULL, video_data = NULL, video_mime = NULL WHERE id = ?",
        (item_id,),
    )
    conn.commit()
    conn.close()
    return {"deleted": True}


class CtaUploadRequest(BaseModel):
    video_base64: str
    mime_type: str = "video/mp4"


@app.post("/api/video/cta/upload")
async def upload_cta_video(req: CtaUploadRequest):
    """Upload a CTA video clip to be appended to every generated video.
    Stored in R2 if configured, otherwise as base64 in settings."""
    import base64 as _b64
    r2_config = _get_r2_config()
    if is_r2_configured(r2_config):
        url = upload_video_to_r2(
            video_base64=req.video_base64,
            content_id=0,  # 0 = CTA asset, not a content row
            mime_type=req.mime_type,
            account_id=r2_config["account_id"],
            access_key_id=r2_config["access_key_id"],
            secret_access_key=r2_config["secret_access_key"],
            bucket_name=r2_config["bucket_name"],
            public_url=r2_config["public_url"],
            filename_override="cta_video.mp4",
        )
        set_setting("cta_video_url", url)
        set_setting("cta_video_b64", "")  # clear any local fallback
        return {"saved": True, "storage": "r2", "url": url}
    else:
        # Store as base64 in settings (small clips only)
        set_setting("cta_video_b64", req.video_base64)
        set_setting("cta_video_url", "")
        return {"saved": True, "storage": "local"}


@app.get("/api/video/cta/status")
async def cta_status():
    """Check whether a CTA video is configured."""
    url = get_setting("cta_video_url", "")
    has_local = bool(get_setting("cta_video_b64", ""))
    return {"configured": bool(url or has_local), "url": url, "storage": "r2" if url else ("local" if has_local else None)}


@app.delete("/api/video/cta")
async def delete_cta_video():
    """Remove the configured CTA video."""
    set_setting("cta_video_url", "")
    set_setting("cta_video_b64", "")
    return {"deleted": True}


class StockFootageRequest(BaseModel):
    query: str
    orientation: str = "portrait"
    per_page: int = 5


@app.post("/api/video/stock-footage")
async def stock_footage_search(req: StockFootageRequest):
    """Search Pexels for stock video footage (free alternative to AI generation)."""
    pexels_key = get_setting("pexels_api_key", "")
    if not pexels_key:
        raise HTTPException(status_code=400, detail="Pexels API key required for stock footage search")

    try:
        results = await search_stock_footage(
            query=req.query,
            api_key=pexels_key,
            orientation=req.orientation,
            per_page=req.per_page,
        )
        return {"videos": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stock footage search failed: {str(e)}")


# ── Video Storage Management ──────────────────────────────────────────────────

@app.get("/api/video/storage-status")
async def video_storage_status():
    """Return R2 config status and how many videos are stored (and their age)."""
    r2_config = _get_r2_config()
    r2_ready = is_r2_configured(r2_config)
    retention_days = int(get_setting("video_retention_days", "60") or 60)

    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM content WHERE video_path IS NOT NULL OR video_data IS NOT NULL"
    ).fetchone()["cnt"]
    r2_stored = conn.execute(
        "SELECT COUNT(*) as cnt FROM content WHERE video_path LIKE 'http%'"
    ).fetchone()["cnt"]
    blob_stored = conn.execute(
        "SELECT COUNT(*) as cnt FROM content WHERE video_data IS NOT NULL"
    ).fetchone()["cnt"]
    due_cleanup = conn.execute(
        "SELECT COUNT(*) as cnt FROM content "
        "WHERE (video_path IS NOT NULL OR video_data IS NOT NULL) "
        "AND created_at < datetime('now', ?)",
        (f"-{retention_days} days",),
    ).fetchone()["cnt"]
    conn.close()

    return {
        "r2_configured": r2_ready,
        "r2_bucket": r2_config["bucket_name"] if r2_ready else None,
        "retention_days": retention_days,
        "total_videos": total,
        "r2_stored": r2_stored,
        "blob_stored": blob_stored,
        "due_for_cleanup": due_cleanup,
    }


@app.post("/api/video/cleanup")
async def trigger_video_cleanup():
    """Manually trigger video cleanup — deletes videos older than retention_days."""
    deleted = run_video_cleanup()
    return {"deleted": deleted, "message": f"Cleaned up {deleted} expired video(s)"}


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
        f"SELECT {CONTENT_COLS} FROM content ORDER BY created_at DESC LIMIT 5"
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
    "atlascloud_api_key",
    "gemini_paid_api_key",
    "stability_api_key",
    "openai_api_key",
    "linkedin_client_id",
    "linkedin_client_secret",
    "linkedin_access_token",
    "facebook_page_id",
    "facebook_access_token",
    "kling_api_key",
    "kling_secret_key",
    "runway_api_key",
    "luma_api_key",
    "fal_api_key",
    "pexels_api_key",
    "r2_access_key_id",
    "r2_secret_access_key",
}

SETTINGS_KEYS = [
    "ollama_url",
    "default_model",
    "default_ollama_model",
    "groq_api_key",
    "gemini_api_key",
    "deepseek_api_key",
    "qwen_api_key",
    "atlascloud_api_key",
    "atlascloud_model",
    "atlascloud_video_model",
    "gemini_paid_api_key",
    "stability_api_key",
    "openai_api_key",
    "default_image_provider",
    "linkedin_client_id",
    "linkedin_client_secret",
    "linkedin_access_token",
    "facebook_page_id",
    "facebook_access_token",
    "kling_api_key",
    "kling_secret_key",
    "runway_api_key",
    "luma_api_key",
    "fal_api_key",
    "pexels_api_key",
    "default_video_provider",
    # Cloudflare R2 storage
    "r2_account_id",
    "r2_access_key_id",
    "r2_secret_access_key",
    "r2_bucket_name",
    "r2_public_url",
    # Video retention
    "video_retention_days",
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
