import httpx
import asyncio
import json
import re
import os
import time
import hmac
import hashlib
import base64
import logging
from pathlib import Path

logger = logging.getLogger("nestpost")

# ── Pexels search cache (saves repeated identical queries) ────────────────────
_PEXELS_CACHE: dict[str, tuple[float, list]] = {}  # key → (timestamp, results)
_PEXELS_CACHE_TTL = 86400  # 24 hours

FFMPEG_PATH = os.environ.get(
    "FFMPEG_PATH", str(Path(__file__).parent.parent / "ffmpeg" / "ffmpeg.exe")
)

# ── Video Provider Registry ───────────────────────────────────────────────────

VIDEO_PROVIDERS = {
    # ── Free tier ──
    "veo3_free": {
        "name": "Veo 3.1 (Paid)",
        "description": "Google Veo 3.1 via Gemini API — paid tier only, ~$0.50/sec",
        "paid": True,
        "needs_key": "gemini_api_key",
        "max_length": 8,
        "quality": 5,
    },
    "kling_free": {
        "name": "Kling AI (Free)",
        "description": "Kling AI v1 — good motion coherence, uses free starter credits",
        "paid": False,
        "needs_key": "kling_api_key",
        "max_length": 10,
        "quality": 4,
    },
    # ── Paid tier ──
    "veo3_paid": {
        "name": "Veo 3 (Paid)",
        "description": "Google Veo 3 — full quality, $0.50/sec",
        "paid": True,
        "needs_key": "gemini_api_key",
        "max_length": 60,
        "quality": 5,
    },
    "kling_pro": {
        "name": "Kling AI Pro (v2)",
        "description": "Kling AI v2-master — cinematic quality, 1080p, no watermark (paid credits)",
        "paid": True,
        "needs_key": "kling_api_key",
        "max_length": 10,
        "quality": 5,
    },
    "runway": {
        "name": "Runway Gen-4",
        "description": "Runway Gen-4 — consistent, strong character coherence",
        "paid": True,
        "needs_key": "runway_api_key",
        "max_length": 16,
        "quality": 4,
    },
    "luma": {
        "name": "Luma Dream Machine",
        "description": "Luma Dream Machine — good for product reveal shots",
        "paid": True,
        "needs_key": "luma_api_key",
        "max_length": 5,
        "quality": 3,
    },
    "fal_wan": {
        "name": "WAN 2.1 (fal.ai)",
        "description": "WAN 2.1 via fal.ai — ~$0.20/gen at 480p, purchase credits at fal.ai/dashboard/billing",
        "paid": False,
        "needs_key": "fal_api_key",
        "max_length": 5,
        "quality": 3,
    },
    "fal_kling": {
        "name": "Kling 2.6 (fal.ai)",
        "description": "Kling 2.6 via fal.ai — excellent motion quality",
        "paid": False,
        "needs_key": "fal_api_key",
        "max_length": 10,
        "quality": 4,
    },
    "fal_hailuo": {
        "name": "Hailuo (fal.ai)",
        "description": "MiniMax Hailuo via fal.ai — cinematic quality",
        "paid": False,
        "needs_key": "fal_api_key",
        "max_length": 6,
        "quality": 4,
    },
    "atlascloud_video": {
        "name": "Atlas Cloud Video",
        "description": "300+ video models via Atlas Cloud — model configurable in Settings (default: Kling 3.0 Pro)",
        "paid": True,
        "needs_key": "atlascloud_api_key",
        "max_length": 10,
        "quality": 5,
    },
}

# Aspect ratio options for video
VIDEO_ASPECT_RATIOS = {
    "9:16": "Vertical — Reels / TikTok / Stories",
    "16:9": "Landscape — LinkedIn / YouTube",
    "1:1": "Square — Instagram / Facebook Feed",
}


# ── Atlas Cloud Model Registry ───────────────────────────────────────────────

ATLASCLOUD_MODELS = {
    "google/veo3.1-lite/text-to-video": {
        "label": "Veo 3.1 Lite",
        "cost_per_sec": 0.05,
        "duration_options": [4, 6, 8],
        "duration_default": 8,
        "aspect_field": "aspect_ratio",
        "aspect_options": {"16:9": "Landscape", "9:16": "Portrait (Reels)"},
        "resolution_options": ["720p", "1080p"],
        "resolution_default": "720p",
        "supports_negative_prompt": False,
        "supports_audio": False,
        "extra_defaults": {"seed": -1},
        "prompt_style": "visual_only",
        "description": "Budget-friendly Google model — fast, clean output",
    },
    "kwaivgi/kling-v3.0-pro/text-to-video": {
        "label": "Kling 3.0 Pro",
        "cost_per_sec": 0.095,
        "duration_options": [3, 5, 8, 10, 15],
        "duration_default": 5,
        "aspect_field": "aspect_ratio",
        "aspect_options": {"16:9": "Landscape", "9:16": "Portrait (Reels)", "1:1": "Square"},
        "resolution_options": None,
        "resolution_default": None,
        "supports_negative_prompt": True,
        "supports_audio": False,
        "extra_defaults": {"cfg_scale": 0.5, "sound": False},
        "prompt_style": "cinematic_detailed",
        "description": "Best for cinematic smart home — supports negative prompts",
    },
    "openai/sora-2/text-to-video": {
        "label": "Sora 2",
        "cost_per_sec": 0.10,
        "duration_options": [4, 8, 12],
        "duration_default": 8,
        "aspect_field": "size",
        "aspect_options": {"1280x720": "Landscape (1280x720)", "720x1280": "Portrait (720x1280)"},
        "resolution_options": None,
        "resolution_default": None,
        "supports_negative_prompt": False,
        "supports_audio": False,
        "extra_defaults": {},
        "prompt_style": "narrative_rich",
        "description": "Excels at complex scenes with human motion & narrative",
    },
    "google/veo3.1/text-to-video": {
        "label": "Veo 3.1",
        "cost_per_sec": 0.20,
        "duration_options": [4, 6, 8],
        "duration_default": 8,
        "aspect_field": "aspect_ratio",
        "aspect_options": {"16:9": "Landscape", "9:16": "Portrait (Reels)"},
        "resolution_options": ["720p", "1080p"],
        "resolution_default": "1080p",
        "supports_negative_prompt": True,
        "supports_audio": True,
        "extra_defaults": {"seed": 1},
        "prompt_style": "cinematic_audio",
        "description": "Premium — supports audio generation & negative prompts",
    },
}

# Sorted by cost for UI display
ATLASCLOUD_MODELS_SORTED = sorted(ATLASCLOUD_MODELS.items(), key=lambda x: x[1]["cost_per_sec"])


# ── Video prompt generation — multi-provider with auto-fallback ───────────────
# Provider try-order. The caller passes a preferred_provider; the remaining
# configured providers are tried in this order if the first one fails.
_VIDEO_PROMPT_PROVIDER_ORDER = ["gemini", "groq", "deepseek", "qwen"]


async def _call_text_provider_for_video(
    provider: str, system: str, user: str, api_keys: dict
) -> str:
    """Route a text-generation call to the named provider.
    Raises ValueError if key is missing; re-raises any HTTP/parse errors."""
    from ai_client import call_gemini, call_groq, call_deepseek, call_qwen
    if provider == "gemini":
        return await call_gemini(system, user, api_keys.get("gemini", ""))
    if provider == "groq":
        return await call_groq(system, user, api_keys.get("groq", ""))
    if provider == "deepseek":
        return await call_deepseek(system, user, api_keys.get("deepseek", ""))
    if provider == "qwen":
        return await call_qwen(system, user, api_keys.get("qwen", ""))
    raise ValueError(f"Unknown AI provider: {provider}")


async def generate_video_prompts(
    caption: str,
    platform: str,
    image_suggestion: str,
    hook: str,
    api_keys: dict,
    model_id: str = "",
    preferred_provider: str = "gemini",
) -> list[dict]:
    """Generate 3 video prompt variants (cinematic, dynamic, minimal) from post content.
    When model_id is provided, tailors prompts to that model's capabilities.
    Returns list of {style, prompt, negative_prompt, suggested_length, suggested_aspect_ratio}."""

    # Model-specific context for prompt tailoring
    model_cfg = ATLASCLOUD_MODELS.get(model_id, {})
    model_context = ""
    if model_cfg:
        dur_opts = model_cfg.get("duration_options", [])
        asp_opts = list(model_cfg.get("aspect_options", {}).keys())
        model_context = f"\n═══ TARGET MODEL: {model_cfg['label']} ═══\n"
        model_context += f"Valid durations: {dur_opts}\n"
        model_context += f"Valid aspect ratios/sizes: {asp_opts}\n"
        if model_cfg.get("supports_audio"):
            model_context += (
                "This model supports AUDIO GENERATION. Include ambient sound descriptions "
                "in each brief (e.g. 'soft hum of HVAC, click of a smart lock, "
                "gentle chime of a doorbell notification, quiet mechanical whir of motorised blinds'). "
                "Write sound in a separate sentence starting with 'Ambient sound:'\n"
            )
        if not model_cfg.get("supports_negative_prompt"):
            model_context += (
                "This model does NOT support negative prompts. "
                "Still generate a negative_prompt field for reference, but the user should know "
                "it won't be sent to the API. Fold key exclusions INTO the main prompt as "
                "positive instructions (e.g. 'smooth steady camera' instead of relying on "
                "'no shaky camera' in negative prompt).\n"
            )
        if model_cfg.get("prompt_style") == "narrative_rich":
            model_context += (
                "This model excels at complex narrative scenes with human motion. "
                "Write prompts as rich descriptive narratives — describe character actions, "
                "emotional beats, and scene progression in flowing prose.\n"
            )
        if model_cfg.get("prompt_style") == "visual_only":
            model_context += (
                "This is a budget model. Keep prompts focused on clean visual scenes. "
                "Avoid overly complex multi-subject scenes.\n"
            )
        model_context += (
            f"IMPORTANT: suggested_length MUST be one of {dur_opts}. "
            f"suggested_aspect_ratio MUST be one of {asp_opts}.\n\n"
        )

    system = (
        "You are a senior video director and AI video prompt engineer specialising in smart home "
        "and PropTech content for Australian social media (Instagram Reels, TikTok, LinkedIn).\n\n"
        "Given a social media post, generate THREE distinct cinematography briefs optimised for "
        "AI video generation. Each brief must be detailed enough that the AI model can "
        "produce a publish-ready Reel with no ambiguity.\n\n"
        + model_context
        + "═══ SMART HOME TECHNICAL VOCABULARY ═══\n"
        "Use these terms naturally where relevant to the post:\n"
        "Devices/hardware: smart hub, automation panel, touchscreen keypad, motion sensor, "
        "door/window sensor, smart lock, video doorbell, IP camera, NVR, PoE switch, "
        "smart thermostat, HVAC controller, smart blinds/shutters, smart meter, solar inverter, "
        "EV charger, smart garage controller, intercom panel, in-wall tablet, smart lighting "
        "(downlights, strip LEDs, RGB, RGBW, tunable white), occupancy sensor, presence sensor, "
        "zigbee/z-wave/matter device, smart speaker, mesh WiFi node, patch panel.\n"
        "Experiences/actions: scene activation, automation trigger, geofencing arrival/departure, "
        "voice command response, app notification, energy dashboard, live camera feed, "
        "two-way intercom, remote access, scheduled automation, presence detection, "
        "multi-room audio, goodnight routine, morning wake scene, away mode, "
        "integration handshake (e.g. 'the thermostat and blinds synchronising at sunset').\n\n"

        "═══ THE THREE STYLES ═══\n"
        "1. CINEMATIC — aspirational, premium feel. Shallow depth of field, anamorphic lens "
        "compression, film-grade colour grade (teal-orange or warm desaturated), slow deliberate "
        "camera movement, architectural framing. Mood: calm luxury. Pacing: slow burn.\n\n"
        "2. DYNAMIC — energetic, scroll-stopping. Fast editorial cuts (every 1.5–2s), "
        "whip pans, snap zooms, Dutch angles for drama, tracking shots following hand gestures "
        "or device activations. Mood: exciting, modern, tech-forward. Pacing: punchy rhythm.\n\n"
        "3. MINIMAL — clean, zen, product-hero. Near-static camera or imperceptibly slow push, "
        "enormous negative space, single hero device or UI element in sharp focus, "
        "everything else softly blurred. Mood: simplicity, confidence. Pacing: meditative.\n\n"

        "═══ REQUIRED FIELDS PER BRIEF ═══\n"
        "Write each brief as a single flowing paragraph (150–220 words) covering ALL of:\n"
        "• OPENING FRAME: exact first shot — what the viewer sees in frame 1\n"
        "• CAMERA: movement type (dolly in/out, pan L/R, tilt up/down, tracking, crane, "
        "handheld drift, locked off, aerial descent, rack focus), speed (imperceptible / slow / "
        "medium / fast), and any transitions (cut / match cut / whip pan / dissolve / J-cut)\n"
        "• SHOT SEQUENCE: 3–5 distinct shots with rough timestamp (e.g. 0–2s, 2–5s, 5–8s) "
        "describing exactly what is visible and moving in each\n"
        "• LIGHTING: natural vs artificial, direction (backlit / side-lit / front-lit / "
        "motivated practical), quality (hard / soft / diffused / golden hour / blue hour / "
        "cool office / warm residential), any practical light sources visible (LED strip, "
        "downlight glow, screen glow, daylight through window)\n"
        "• COLOUR GRADE: specific grade description (e.g. lifted blacks with warm highlights, "
        "cool desaturated with teal shadows, high-contrast monochrome, naturalistic with "
        "slightly boosted greens, warm cinematic with crushed blacks)\n"
        "• MOOD & ATMOSPHERE: one sentence on the emotional tone\n"
        "• TECHNICAL DETAIL: any smart home devices, UI elements, or tech actions visible "
        "(use vocabulary above — be specific, e.g. 'a Lutron Caseta keypad dims the "
        "kitchen downlights from 100% to 30%' not just 'smart lighting')\n\n"

        "═══ NEGATIVE PROMPT ═══\n"
        "For EACH brief, also write a negative_prompt (40–60 words) listing what to EXCLUDE. "
        "Always include: shaky handheld camera, motion blur, watermark, subtitles, text overlay, "
        "stock footage watermark, jump cut jitter, overexposed highlights, blown-out windows, "
        "distorted hands, uncanny faces, low resolution, compression artefacts, flickering. "
        "Add style-specific exclusions (e.g. for Minimal: busy backgrounds, multiple subjects, "
        "fast cuts; for Dynamic: static locked-off shots, slow dissolves).\n\n"

        "═══ LOCATION / SETTING ═══\n"
        "All scenes are set in Australia (NOT just Melbourne). Use broad Australian residential "
        "contexts: suburban homes, coastal properties, modern apartments in any capital city "
        "(Sydney, Melbourne, Brisbane, Perth, Adelaide, etc.). Favour generic Australian "
        "architectural cues (open-plan living, alfresco areas, timber decking, eucalyptus views, "
        "bright natural light) rather than state-specific landmarks. Never name a specific city "
        "unless the post caption requires it.\n\n"

        "═══ OUTPUT RULES ═══\n"
        "- Do NOT include brand names, logos, recognisable faces, or text overlays in prompts\n"
        "- Prompts are for AI video generation — describe only what the camera sees\n"
        "- Use present tense, active voice ('the camera pushes in', not 'camera pushed')\n"
        "- CRITICAL: suggested_aspect_ratio MUST be an exact value from the TARGET MODEL's "
        "'Valid aspect ratios/sizes' list above (e.g. Sora uses '1280x720' / '720x1280', "
        "Veo/Kling use '9:16' / '16:9'). Never invent new formats.\n"
        "- CRITICAL: suggested_length MUST be an exact value from the TARGET MODEL's "
        "'Valid durations' list above (not a range, not a guess — one of the allowed integers).\n\n"

        "Return ONLY valid JSON — no markdown fences, no commentary:\n"
        "[\n"
        "  {\n"
        '    "style": "Cinematic",\n'
        '    "prompt": "150-220 word cinematography brief...",\n'
        '    "negative_prompt": "40-60 word exclusion list...",\n'
        '    "suggested_length": 8,\n'
        '    "suggested_aspect_ratio": "9:16"\n'
        "  },\n"
        "  { same structure for Dynamic },\n"
        "  { same structure for Minimal }\n"
        "]"
    )

    user_prompt = (
        f"Platform: {platform}\n"
        f"Post caption: {caption[:800]}\n"
        f"Visual suggestion from post: {image_suggestion or 'N/A'}\n"
        f"Post hook line: {hook or 'N/A'}\n\n"
        "Write three detailed cinematography briefs for this post:"
    )

    # Build provider chain: preferred first, then remaining configured providers
    chain = [preferred_provider] + [
        p for p in _VIDEO_PROMPT_PROVIDER_ORDER
        if p != preferred_provider and api_keys.get(p)
    ]

    last_error: Exception = RuntimeError("No AI provider available — add at least one API key in Settings")
    for provider in chain:
        if not api_keys.get(provider):
            continue  # key not configured, skip silently
        try:
            print(f"[video-prompts] trying provider={provider}")
            raw = await _call_text_provider_for_video(provider, system, user_prompt, api_keys)

            # Strip markdown fences if model wrapped response in ```json ... ```
            text = raw.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"```$", "", text).strip()

            prompts = json.loads(text)
            print(f"[video-prompts] success via {provider} ({len(prompts)} prompts)")
            return prompts

        except Exception as e:
            print(f"[video-prompts] {provider} failed: {e} — trying next in chain")
            last_error = e
            continue

    raise last_error


# ── Stock Footage Search (Pexels API — free) ─────────────────────────────────

async def search_stock_footage(
    query: str,
    api_key: str,
    orientation: str = "portrait",
    per_page: int = 5,
) -> list[dict]:
    """Search Pexels for stock video footage. Returns list of {id, url, preview, duration, width, height}."""
    # Check cache first — Pexels results don't change hour-to-hour
    cache_key = f"{query}|{orientation}|{per_page}"
    cached = _PEXELS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _PEXELS_CACHE_TTL:
        logger.info(f"Pexels cache hit for '{query}'")
        return cached[1]

    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": api_key}
    params = {"query": query, "orientation": orientation, "per_page": per_page, "size": "medium"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for video in data.get("videos", []):
        # Pick the best-quality file under 1080p
        best_file = None
        for vf in video.get("video_files", []):
            if vf.get("height", 0) <= 1080 and vf.get("quality") in ("hd", "sd"):
                if best_file is None or vf.get("height", 0) > best_file.get("height", 0):
                    best_file = vf

        if best_file:
            results.append({
                "id": video["id"],
                "url": best_file["link"],
                "preview": video.get("image", ""),
                "duration": video.get("duration", 0),
                "width": best_file.get("width", 0),
                "height": best_file.get("height", 0),
            })

    _PEXELS_CACHE[cache_key] = (time.time(), results)
    return results


# ── Google Veo 3 (via Gemini API) ────────────────────────────────────────────

async def generate_video_veo3(
    prompt: str,
    api_key: str,
    aspect_ratio: str = "9:16",
    duration: int = 8,
) -> dict:
    """Generate video using Google Veo 3 via Gemini API.
    Returns {status, video_base64, mime_type} or {status, error}."""

    # Veo 3 uses the generateVideos endpoint
    url = "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-generate:generateVideos"

    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "aspectRatio": aspect_ratio,
            "durationSeconds": min(duration, 8),  # Veo 3 free: max 8s
            "personGeneration": "dont_allow",
        },
    }
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        # Submit generation request
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            return {"status": "rate_limited", "error": "Veo 3 daily free limit reached. Try a paid model or wait."}
        if resp.status_code == 404:
            return {"status": "error", "error": "Veo 3.1 requires a paid Gemini API key. Enable billing at aistudio.google.com, or use Kling AI instead."}
        resp.raise_for_status()
        data = resp.json()

    # Veo returns an operation — may need polling
    operation_name = data.get("name")
    if operation_name:
        return await _poll_veo_operation(operation_name, api_key)

    # Direct response (unlikely for video but handle it)
    for vid in data.get("generatedVideos", []):
        video_data = vid.get("video", {})
        if "bytesBase64Encoded" in video_data:
            return {
                "status": "complete",
                "video_base64": video_data["bytesBase64Encoded"],
                "mime_type": video_data.get("mimeType", "video/mp4"),
            }

    return {"status": "error", "error": "No video returned from Veo 3"}


async def _poll_veo_operation(operation_name: str, api_key: str, max_wait: int = 300) -> dict:
    """Poll a Veo long-running operation until complete."""
    url = f"https://generativelanguage.googleapis.com/v1beta/{operation_name}"
    headers = {"x-goog-api-key": api_key}

    start = time.time()
    interval = 5.0  # exponential backoff: 5 → 7.5 → 11.25 → … max 30s
    while time.time() - start < max_wait:
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 30.0)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if data.get("done"):
            result = data.get("response", {})
            for vid in result.get("generatedVideos", []):
                video_data = vid.get("video", {})
                if "bytesBase64Encoded" in video_data:
                    return {
                        "status": "complete",
                        "video_base64": video_data["bytesBase64Encoded"],
                        "mime_type": video_data.get("mimeType", "video/mp4"),
                    }
            error = data.get("error", {})
            return {"status": "error", "error": error.get("message", "Veo generation failed")}

    return {"status": "error", "error": "Veo generation timed out (5 min)"}


# ── Kling AI ──────────────────────────────────────────────────────────────────

def _kling_jwt(access_key: str, secret_key: str) -> str:
    """Generate a short-lived HS256 JWT for Kling AI API authentication.
    Kling requires: iss=accessKey, exp=now+30min, nbf=now-5s, signed with secretKey."""
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(',', ':')).encode()
    ).rstrip(b"=").decode()
    now = int(time.time())
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": access_key, "exp": now + 1800, "nbf": now - 5}, separators=(',', ':')).encode()
    ).rstrip(b"=").decode()
    signing_input = f"{header}.{payload}"
    sig = base64.urlsafe_b64encode(
        hmac.new(secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{signing_input}.{sig}"


async def generate_video_kling(
    prompt: str,
    access_key: str,
    secret_key: str,
    aspect_ratio: str = "9:16",
    duration: int = 5,
    mode: str = "std",
    negative_prompt: str = "",
) -> dict:
    """Generate video using Kling AI API.
    mode: 'std' for standard (free-tier OK), 'pro' for higher quality.
    Returns {status, video_url, video_base64, mime_type} or {status, error}."""

    token = _kling_jwt(access_key, secret_key)
    url = "https://api.klingai.com/v1/videos/text2video"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    # Kling only accepts "5" or "10" — round to nearest valid value
    kling_duration = "5" if duration <= 5 else "10"

    # kling-v2-master = paid (best quality); kling-v1 = free/standard
    model_name = "kling-v2-master" if mode == "pro" else "kling-v1"
    payload = {
        "model_name": model_name,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": kling_duration,
        "mode": mode,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            # Include raw body — helps distinguish daily-limit vs account-credits-exhausted
            try:
                detail = resp.json().get("message") or resp.json().get("error") or resp.text[:300]
            except Exception:
                detail = resp.text[:300]
            return {"status": "rate_limited", "error": f"Kling 429 — {detail}. Free credits reset at 00:00 Beijing time (UTC+8)."}
        if resp.status_code == 400:
            return {"status": "error", "error": f"Kling API error: {resp.text}"}
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("data", {}).get("task_id")
    if not task_id:
        return {"status": "error", "error": "No task_id returned from Kling"}

    return await _poll_kling_task(task_id, access_key, secret_key)


async def _poll_kling_task(task_id: str, access_key: str, secret_key: str, max_wait: int = 300) -> dict:
    """Poll Kling task until video is ready."""
    url = f"https://api.klingai.com/v1/videos/text2video/{task_id}"

    start = time.time()
    interval = 5.0
    while time.time() - start < max_wait:
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 30.0)
        # Regenerate JWT each poll (30-min TTL, polling can run up to 5 min)
        token = _kling_jwt(access_key, secret_key)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        task_data = data.get("data", {})
        status = task_data.get("task_status", "")

        if status == "succeed":
            videos = task_data.get("task_result", {}).get("videos", [])
            if videos:
                video_url = videos[0].get("url", "")
                # Download the video
                async with httpx.AsyncClient(timeout=60.0) as dl_client:
                    dl_resp = await dl_client.get(video_url)
                    dl_resp.raise_for_status()
                    video_b64 = base64.b64encode(dl_resp.content).decode("utf-8")
                return {
                    "status": "complete",
                    "video_base64": video_b64,
                    "video_url": video_url,
                    "mime_type": "video/mp4",
                }
            return {"status": "error", "error": "Kling returned no video files"}

        if status == "failed":
            return {"status": "error", "error": task_data.get("task_status_msg", "Kling generation failed")}

    return {"status": "error", "error": "Kling generation timed out (5 min)"}


# ── Runway Gen-4 ──────────────────────────────────────────────────────────────

async def generate_video_runway(
    prompt: str,
    api_key: str,
    aspect_ratio: str = "9:16",
    duration: int = 10,
) -> dict:
    """Generate video using Runway Gen-4 API.
    Returns {status, video_base64, mime_type} or {status, error}."""

    # Map aspect ratios to Runway's dimension format
    ratio_map = {
        "9:16": "768:1344",
        "16:9": "1344:768",
        "1:1": "1024:1024",
    }

    url = "https://api.dev.runwayml.com/v1/text_to_video"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }
    payload = {
        "model": "gen4_turbo",
        "promptText": prompt,
        "ratio": ratio_map.get(aspect_ratio, "768:1344"),
        "duration": min(duration, 10),
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            return {"status": "rate_limited", "error": "Runway credit limit reached."}
        resp.raise_for_status()
        data = resp.json()

    task_id = data.get("id")
    if not task_id:
        return {"status": "error", "error": "No task ID from Runway"}

    return await _poll_runway_task(task_id, api_key)


async def _poll_runway_task(task_id: str, api_key: str, max_wait: int = 300) -> dict:
    """Poll Runway task until complete."""
    url = f"https://api.dev.runwayml.com/v1/tasks/{task_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": "2024-11-06",
    }

    start = time.time()
    interval = 5.0
    while time.time() - start < max_wait:
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 30.0)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status", "")

        if status == "SUCCEEDED":
            output_url = data.get("output", [None])[0]
            if output_url:
                async with httpx.AsyncClient(timeout=60.0) as dl_client:
                    dl_resp = await dl_client.get(output_url)
                    dl_resp.raise_for_status()
                    import base64
                    video_b64 = base64.b64encode(dl_resp.content).decode("utf-8")
                return {
                    "status": "complete",
                    "video_base64": video_b64,
                    "mime_type": "video/mp4",
                }
            return {"status": "error", "error": "Runway returned no output URL"}

        if status == "FAILED":
            return {"status": "error", "error": data.get("failure", "Runway generation failed")}

    return {"status": "error", "error": "Runway generation timed out (5 min)"}


# ── Luma Dream Machine ────────────────────────────────────────────────────────

async def generate_video_luma(
    prompt: str,
    api_key: str,
    aspect_ratio: str = "9:16",
    duration: int = 5,
) -> dict:
    """Generate video using Luma Dream Machine API.
    Returns {status, video_base64, mime_type} or {status, error}."""

    url = "https://api.lumalabs.ai/dream-machine/v1/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            return {"status": "rate_limited", "error": "Luma generation limit reached."}
        resp.raise_for_status()
        data = resp.json()

    gen_id = data.get("id")
    if not gen_id:
        return {"status": "error", "error": "No generation ID from Luma"}

    return await _poll_luma_generation(gen_id, api_key)


async def _poll_luma_generation(gen_id: str, api_key: str, max_wait: int = 300) -> dict:
    """Poll Luma generation until complete."""
    url = f"https://api.lumalabs.ai/dream-machine/v1/generations/{gen_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    start = time.time()
    interval = 5.0
    while time.time() - start < max_wait:
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 30.0)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        state = data.get("state", "")

        if state == "completed":
            video_url = data.get("assets", {}).get("video")
            if video_url:
                async with httpx.AsyncClient(timeout=60.0) as dl_client:
                    dl_resp = await dl_client.get(video_url)
                    dl_resp.raise_for_status()
                    import base64
                    video_b64 = base64.b64encode(dl_resp.content).decode("utf-8")
                return {
                    "status": "complete",
                    "video_base64": video_b64,
                    "mime_type": "video/mp4",
                }
            return {"status": "error", "error": "Luma returned no video URL"}

        if state == "failed":
            return {"status": "error", "error": data.get("failure_reason", "Luma generation failed")}

    return {"status": "error", "error": "Luma generation timed out (5 min)"}


# ── fal.ai (WAN 2.1 / Kling 2.6 / Hailuo) ───────────────────────────────────

# fal.ai model IDs  (keep aligned with fal.ai /models catalogue)
_FAL_MODELS = {
    "fal_wan":    "fal-ai/wan-t2v",                                   # WAN 2.1 standard T2V
    "fal_kling":  "fal-ai/kling-video/v2.1/standard/text-to-video",  # Kling via fal
    "fal_hailuo": "fal-ai/minimax/video-01-live",                     # MiniMax Hailuo via fal
}

# fal.ai aspect ratio aliases (WAN 2.1 uses strings)
_FAL_ASPECT = {
    "9:16": "9:16",
    "16:9": "16:9",
    "1:1":  "1:1",
}


async def generate_video_fal(
    prompt: str,
    api_key: str,
    provider: str = "fal_wan",
    aspect_ratio: str = "9:16",
    duration: int = 5,
) -> dict:
    """Generate video via fal.ai queue API (WAN 2.1, Kling 2.6, or Hailuo).
    Returns {status, video_base64, mime_type} or {status, error}."""

    model = _FAL_MODELS.get(provider, _FAL_MODELS["fal_wan"])
    base_url = f"https://queue.fal.run/{model}"
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }

    # Build payload — duration must be integer for fal.ai models
    payload: dict = {
        "prompt": prompt,
        "aspect_ratio": _FAL_ASPECT.get(aspect_ratio, "9:16"),
    }
    if provider == "fal_wan":
        payload["duration"] = min(duration, 5)    # WAN 2.1 max 5s — integer required
    elif provider == "fal_kling":
        payload["duration"] = min(duration, 10)   # Kling via fal max 10s — integer required
    # Hailuo / MiniMax doesn't accept a duration param

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(base_url, json=payload, headers=headers)
        if resp.status_code == 401:
            return {"status": "error", "error": "fal.ai: invalid API key — check Settings"}
        if resp.status_code == 403:
            return {"status": "error", "error": "fal.ai: account credit balance is zero or locked — go to fal.ai/dashboard/billing and purchase credits (from $0.20/generation). Adding a payment method alone does not top up your balance."}
        if resp.status_code == 422:
            return {"status": "error", "error": f"fal.ai: bad request — {resp.text[:200]}"}
        if resp.status_code == 429:
            return {"status": "rate_limited", "error": "fal.ai credits exhausted — top up at fal.ai/dashboard"}
        resp.raise_for_status()
        data = resp.json()

    request_id  = data.get("request_id")
    status_url   = data.get("status_url",   f"{base_url}/requests/{request_id}/status")
    response_url = data.get("response_url", f"{base_url}/requests/{request_id}")

    if not request_id:
        return {"status": "error", "error": "fal.ai returned no request_id"}

    return await _poll_fal_request(request_id, status_url, response_url, headers)


async def _poll_fal_request(
    request_id: str,
    status_url: str,
    response_url: str,
    headers: dict,
    max_wait: int = 300,
) -> dict:
    """Poll fal.ai queue until complete, then download the video."""
    start = time.time()
    interval = 5.0
    while time.time() - start < max_wait:
        await asyncio.sleep(interval)
        interval = min(interval * 1.5, 30.0)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(status_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        fal_status = data.get("status", "")

        if fal_status == "COMPLETED":
            # Fetch the result
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.get(response_url, headers=headers)
                res.raise_for_status()
                result = res.json()

            video_url = (
                result.get("video", {}).get("url")
                or (result.get("videos") or [{}])[0].get("url")
            )
            if not video_url:
                return {"status": "error", "error": "fal.ai: no video URL in result"}

            # Download the video
            async with httpx.AsyncClient(timeout=120.0) as dl_client:
                dl_resp = await dl_client.get(video_url)
                dl_resp.raise_for_status()
                video_b64 = base64.b64encode(dl_resp.content).decode("utf-8")

            return {
                "status": "complete",
                "video_base64": video_b64,
                "video_url": video_url,
                "mime_type": "video/mp4",
            }

        if fal_status in ("FAILED", "CANCELLED"):
            detail = data.get("error") or data.get("detail") or "fal.ai generation failed"
            return {"status": "error", "error": str(detail)}

        # IN_QUEUE or IN_PROGRESS — keep polling

    return {"status": "error", "error": f"fal.ai generation timed out after {max_wait}s"}


# ── Router ────────────────────────────────────────────────────────────────────

async def generate_video(
    prompt: str,
    provider: str,
    api_keys: dict,
    aspect_ratio: str = "9:16",
    duration: int = 8,
    negative_prompt: str = "",
    resolution: str = "",
    generate_audio: bool = False,
    out_path: str = "",
) -> dict:
    """Route video generation to the appropriate provider.
    Returns {status, video_base64, mime_type} or {status, error}."""

    if provider in ("veo3_free", "veo3_paid"):
        key = api_keys.get("gemini", "")
        if not key:
            raise ValueError("Gemini API key required for Veo 3")
        return await generate_video_veo3(prompt, key, aspect_ratio, duration)

    elif provider in ("kling_free", "kling_pro"):
        access_key = api_keys.get("kling_access", "")
        secret_key = api_keys.get("kling_secret", "")
        if not access_key or not secret_key:
            raise ValueError("Kling Access Key and Secret Key are both required")
        mode = "pro" if provider == "kling_pro" else "std"
        return await generate_video_kling(prompt, access_key, secret_key, aspect_ratio, duration, mode, negative_prompt)

    elif provider == "runway":
        key = api_keys.get("runway", "")
        if not key:
            raise ValueError("Runway API key required")
        return await generate_video_runway(prompt, key, aspect_ratio, duration)

    elif provider == "luma":
        key = api_keys.get("luma", "")
        if not key:
            raise ValueError("Luma API key required")
        return await generate_video_luma(prompt, key, aspect_ratio, duration)

    elif provider in ("fal_wan", "fal_kling", "fal_hailuo"):
        key = api_keys.get("fal", "")
        if not key:
            raise ValueError("fal.ai API key required — add it in Settings")
        return await generate_video_fal(prompt, key, provider, aspect_ratio, duration)

    elif provider == "atlascloud_video":
        key = api_keys.get("atlascloud", "")
        model = api_keys.get("atlascloud_video_model", "kwaivgi/kling-v3.0-pro/text-to-video")
        if not key:
            raise ValueError("Atlas Cloud API key required — add it in Settings")
        return await generate_video_atlascloud(
            prompt, key, model, aspect_ratio, duration,
            negative_prompt, resolution, generate_audio,
            out_path=out_path,
        )

    else:
        raise ValueError(f"Unknown video provider: {provider}")


async def generate_video_atlascloud(
    prompt: str,
    api_key: str,
    model: str = "kwaivgi/kling-v3.0-pro/text-to-video",
    aspect_ratio: str = "9:16",
    duration: int = 5,
    negative_prompt: str = "",
    resolution: str = "",
    generate_audio: bool = False,
    out_path: str = "",
) -> dict:
    """Generate video via Atlas Cloud aggregator API (queue-based).
    Builds payload dynamically from ATLASCLOUD_MODELS config.
    POST /api/v1/model/generateVideo → returns prediction_id → poll /api/v1/model/prediction/{id}"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    model_cfg = ATLASCLOUD_MODELS.get(model, {})

    # Build payload dynamically based on model config
    payload = {"model": model, "prompt": prompt, "duration": duration}

    # Aspect ratio / size — Sora uses "size", others use "aspect_ratio"
    aspect_field = model_cfg.get("aspect_field", "aspect_ratio")
    payload[aspect_field] = aspect_ratio

    # Negative prompt — only for models that support it
    if negative_prompt and model_cfg.get("supports_negative_prompt", False):
        payload["negative_prompt"] = negative_prompt

    # Resolution — Veo models
    if resolution and model_cfg.get("resolution_options"):
        payload["resolution"] = resolution

    # Audio — Veo 3.1 full
    if model_cfg.get("supports_audio") and generate_audio:
        payload["generate_audio"] = True

    # Extra model defaults (cfg_scale, sound, seed, etc.)
    for k, v in model_cfg.get("extra_defaults", {}).items():
        if k not in payload:
            payload[k] = v

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.atlascloud.ai/api/v1/model/generateVideo",
            json=payload,
            headers=headers,
        )
        if resp.status_code == 402:
            return {"status": "error", "error": "Atlas Cloud: insufficient credits — top up at atlascloud.ai/console/billing"}
        if resp.status_code == 401:
            return {"status": "error", "error": "Atlas Cloud: invalid API key — check Settings"}
        resp.raise_for_status()
        data = resp.json()

    prediction_id = data.get("data", {}).get("id") or data.get("id")
    if not prediction_id:
        return {"status": "error", "error": f"Atlas Cloud: no prediction ID returned — {data}"}

    return await _poll_atlascloud(prediction_id, api_key, out_path=out_path)


async def _poll_atlascloud(prediction_id: str, api_key: str, max_wait: int = 600, out_path: str = "") -> dict:
    """Poll Atlas Cloud prediction endpoint every 10 seconds until complete.
    Kling 3.0 Pro can take 8-10 minutes — max_wait set to 600s."""
    url = f"https://api.atlascloud.ai/api/v1/model/prediction/{prediction_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    elapsed = 0

    async with httpx.AsyncClient(timeout=15.0) as client:
        while elapsed < max_wait:
            await asyncio.sleep(10)
            elapsed += 10
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                continue

            status = (data.get("data", {}).get("status") or data.get("status", "")).lower()

            if status in ("succeeded", "completed", "success"):
                # Try every known field shape Atlas Cloud might return the video URL in
                inner = data.get("data") or {}
                # Atlas Cloud returns data.outputs (array) or data.output
                output = inner.get("outputs") or inner.get("output") or data.get("outputs") or data.get("output")

                video_url = None
                if isinstance(output, list) and output:
                    video_url = output[0] if isinstance(output[0], str) else None
                elif isinstance(output, str) and output.startswith("http"):
                    video_url = output
                elif isinstance(output, dict):
                    video_url = (output.get("video_url") or output.get("url") or
                                 output.get("video") or output.get("mp4"))
                if not video_url:
                    video_url = (inner.get("video_url") or inner.get("url") or
                                 inner.get("video") or data.get("video_url") or
                                 data.get("url") or data.get("video"))

                if video_url:
                    # Memory-efficient: stream chunks directly to disk if caller
                    # provided out_path. Avoids holding the full video + base64
                    # in RAM simultaneously (was OOM'ing on Render 512MB tier).
                    if out_path:
                        import os as _os
                        total = 0
                        async with httpx.AsyncClient(timeout=120.0) as dl:
                            async with dl.stream("GET", video_url) as vresp:
                                vresp.raise_for_status()
                                with open(out_path, "wb") as _f:
                                    async for chunk in vresp.aiter_bytes(chunk_size=65536):
                                        _f.write(chunk)
                                        total += len(chunk)
                        print(f"[atlascloud] streamed {total}B to {out_path} from {video_url[:80]}")
                        return {
                            "status": "complete",
                            "video_path": out_path,
                            "mime_type": "video/mp4",
                        }

                    # Legacy path: full buffer + base64 (still used by callers
                    # that don't pass out_path — kept for backward compat).
                    import base64, gc
                    async with httpx.AsyncClient(timeout=120.0) as dl:
                        vresp = await dl.get(video_url)
                        vresp.raise_for_status()
                        raw_bytes = vresp.content
                    print(f"[atlascloud] downloaded {len(raw_bytes)}B from {video_url[:80]}")
                    encoded = base64.b64encode(raw_bytes).decode()
                    del raw_bytes
                    gc.collect()
                    return {
                        "status": "complete",
                        "video_base64": encoded,
                        "mime_type": "video/mp4",
                    }
                # Include truncated raw response to help diagnose field name
                import json as _json
                raw_snippet = _json.dumps(data)[:400]
                return {"status": "error", "error": f"Atlas Cloud: no video URL found in response — {raw_snippet}"}

            if status in ("failed", "error", "cancelled"):
                msg = data.get("data", {}).get("error") or data.get("error") or "Unknown error"
                return {"status": "error", "error": f"Atlas Cloud generation failed: {msg}"}

    return {"status": "error", "error": f"Atlas Cloud: timed out after {max_wait}s — try a lighter model or shorter duration"}


# ── Video Post-Processing ────────────────────────────────────────────────────
#
# Memory-efficient pipeline for CTA concat + brand logo overlay.
#
# Design: operate on file paths, never on base64 strings. The generation
# endpoint writes the Atlas Cloud video to a temp file, then calls
# postprocess_video() which does CTA concat + logo overlay in a SINGLE
# ffmpeg invocation. Output is also a file on disk. Only the very final
# step base64-encodes the bytes for the HTTP response.
#
# Why: Render's 512MB instance was OOM'ing because the old pipeline held
# up to 4× the video size in memory (b64 input + decoded bytes + b64 output
# + duplicated string before GC). Keeping video on disk and doing both
# operations in one ffmpeg pass cuts peak memory to roughly 1× video size.


def _probe_duration(path: str, fallback: float = 10.0) -> float:
    """Return video duration in seconds via ffprobe. Fallback on error."""
    import subprocess
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True, timeout=15,
        )
        if probe.returncode == 0:
            return float(probe.stdout.decode().strip() or fallback)
    except Exception:
        pass
    return fallback


def _probe_dimensions(path: str, fallback: tuple[int, int] = (720, 1280)) -> tuple[int, int]:
    """Return (width, height) of the first video stream via ffprobe."""
    import subprocess
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                path,
            ],
            capture_output=True, timeout=15,
        )
        if probe.returncode == 0:
            out = probe.stdout.decode().strip()
            if "x" in out:
                w, h = out.split("x")
                return int(w), int(h)
    except Exception:
        pass
    return fallback


def _logo_overlay_pos(position: str, padding: int) -> str:
    return {
        "top_left":     f"{padding}:{padding}",
        "top_right":    f"main_w-overlay_w-{padding}:{padding}",
        "bottom_left":  f"{padding}:main_h-overlay_h-{padding}",
        "bottom_right": f"main_w-overlay_w-{padding}:main_h-overlay_h-{padding}",
    }.get(position, f"{padding}:{padding}")


def postprocess_video(
    main_path: str,
    out_path: str,
    cta_path: str | None = None,
    logo_path: str | None = None,
    logo_position: str = "top_left",
    logo_padding: int = 18,
    logo_height: int = 104,
) -> None:
    """Run CTA concat + logo overlay in a SINGLE ffmpeg invocation.

    Writes the final mp4 to ``out_path``. All inputs are file paths — the
    caller is responsible for writing the main/cta/logo bytes to disk and
    reading back the result. This keeps peak memory to roughly 1× video size
    instead of the 4× blowup the old b64-string pipeline had.

    Parameters:
        main_path: required — the generated video (silent or not)
        out_path:  required — target for the final mp4
        cta_path:  optional — if provided, concatenated to the end
        logo_path: optional — if provided, overlaid on the main video only
                   (NOT the CTA, which has its own branding)
    """
    import subprocess
    import os

    have_cta  = bool(cta_path and os.path.exists(cta_path))
    have_logo = bool(logo_path and os.path.exists(logo_path))

    if not have_cta and not have_logo:
        # Nothing to do — just copy the main file through. Stream copy is cheap.
        print(f"[postprocess] no CTA, no logo — stream-copying main → out")
        cmd = ["ffmpeg", "-y", "-i", main_path, "-c", "copy", out_path]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            # fall back to re-encode
            cmd = ["ffmpeg", "-y", "-i", main_path, "-c:v", "libx264", "-preset", "fast", "-crf", "23", out_path]
            result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode != 0:
            raise RuntimeError(f"postprocess passthrough failed: {result.stderr.decode(errors='replace')[-400:]}")
        return

    main_size = os.path.getsize(main_path)
    cta_size  = os.path.getsize(cta_path)  if have_cta  else 0
    logo_size = os.path.getsize(logo_path) if have_logo else 0
    print(f"[postprocess] main={main_size}B cta={cta_size}B logo={logo_size}B have_cta={have_cta} have_logo={have_logo}")

    # ── Build ffmpeg inputs + filter_complex dynamically ──
    inputs: list[str] = ["-i", main_path]
    next_input = 1  # input 0 is main
    cta_idx = logo_idx = silent_idx = None

    # Probe main video dimensions up front — needed to normalize CTA to match
    main_w, main_h = _probe_dimensions(main_path, fallback=(720, 1280))
    print(f"[postprocess] main dimensions probed: {main_w}x{main_h}")

    if have_cta:
        inputs += ["-i", cta_path]
        cta_idx = next_input
        next_input += 1
        # Silent audio input, sized to main duration, so concat has two matching v+a pairs
        main_duration = _probe_duration(main_path, fallback=10.0)
        print(f"[postprocess] main duration probed: {main_duration:.2f}s")
        inputs += ["-f", "lavfi", "-t", f"{main_duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
        silent_idx = next_input
        next_input += 1

    if have_logo:
        inputs += ["-i", logo_path]
        logo_idx = next_input
        next_input += 1

    # Build filter graph
    filter_parts: list[str] = []

    # Main video stream: optionally overlay logo, always format to yuv420p,
    # and force dimensions/SAR to known values so concat sees matching params.
    main_norm = f"scale={main_w}:{main_h},setsar=1,setpts=PTS-STARTPTS,format=yuv420p"
    if have_logo:
        overlay_pos = _logo_overlay_pos(logo_position, logo_padding)
        filter_parts.append(f"[{logo_idx}:v]scale=-1:{logo_height}[logo]")
        filter_parts.append(f"[0:v][logo]overlay={overlay_pos}:format=auto[v0pre]")
        filter_parts.append(f"[v0pre]{main_norm}[v0]")
    else:
        filter_parts.append(f"[0:v]{main_norm}[v0]")

    if have_cta:
        # Main's silent audio track (comes from the anullsrc input)
        filter_parts.append(f"[{silent_idx}:a]asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo[a0]")
        # CTA video: scale to fit main dimensions (letterbox/pillarbox), pad,
        # force SAR 1:1, normalize format. This is the fix for the Sora 720x1280
        # vs square-CTA 1080x1080 dimension mismatch that concat refuses.
        cta_norm = (
            f"scale={main_w}:{main_h}:force_original_aspect_ratio=decrease,"
            f"pad={main_w}:{main_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,setpts=PTS-STARTPTS,format=yuv420p"
        )
        filter_parts.append(f"[{cta_idx}:v]{cta_norm}[v1]")
        filter_parts.append(f"[{cta_idx}:a]asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo[a1]")
        # Concat main + CTA
        filter_parts.append("[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]")
        maps = ["-map", "[outv]", "-map", "[outa]"]
        audio_codec = ["-c:a", "aac", "-ar", "44100", "-b:a", "128k"]
    else:
        # No CTA — just output the (possibly-logo'd) main video. Keep original audio if present.
        maps = ["-map", "[v0]", "-map", "0:a?"]
        audio_codec = ["-c:a", "copy"]

    filter_complex = ";".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", filter_complex]
        + maps
        + ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
        + audio_codec
        + [out_path]
    )
    print(f"[postprocess] filter_complex: {filter_complex}")
    result = subprocess.run(cmd, capture_output=True, timeout=360)

    if result.returncode != 0:
        stderr_tail = result.stderr.decode(errors="replace")[-800:]
        print(f"[postprocess] FAILED rc={result.returncode}\n{stderr_tail}")
        raise RuntimeError(f"postprocess_video failed: {stderr_tail[:500]}")

    print(f"[postprocess] OK, output={os.path.getsize(out_path)}B")


def mix_music_into_video(
    video_path: str,
    music_path: str,
    out_path: str,
    volume: float = 0.15,
) -> None:
    """Mix background music into a video (replaces / adds audio track).
    Handles mute AI-generated videos. Uses -shortest to match video length."""
    import subprocess, os
    if not os.path.exists(music_path):
        raise FileNotFoundError(f"Music file not found: {music_path}")
    filter_expr = f"[1:a]volume={volume},afade=t=in:st=0:d=1.5[mus]"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex", filter_expr,
        "-map", "0:v",
        "-map", "[mus]",
        "-c:v", "copy",
        "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
        "-shortest",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"mix_music failed: {result.stderr.decode(errors='replace')[-400:]}")
    print(f"[mix_music] OK output={os.path.getsize(out_path)}B")


def _auto_music_mood(content_type: str = "", tone: str = "", platform: str = "") -> str:
    """Pick a music mood automatically from content context."""
    t = tone.lower()
    ct = content_type.lower()
    if platform.lower() == "linkedin":
        return "corporate"
    if any(w in t for w in ["energetic", "bold", "exciting", "fun", "dynamic", "vibrant"]):
        return "energetic"
    if any(w in t for w in ["inspiring", "motivational", "aspirational", "uplifting"]):
        return "inspiring"
    if any(w in t for w in ["calm", "relaxed", "peaceful", "mindful", "zen"]):
        return "chill"
    if any(w in ct for w in ["educational", "informational", "how-to", "tutorial", "tips"]):
        return "corporate"
    return "chill"


# ── Legacy b64 wrappers (kept for backwards compatibility) ────────────────────
# These exist in case anything still imports them, but the generate endpoint
# now uses postprocess_video() directly with file paths.

def concat_cta_video(main_b64: str, cta_b64: str, mime_type: str = "video/mp4") -> str:
    """DEPRECATED — use postprocess_video() with file paths instead.
    Kept as a b64 wrapper around postprocess_video for any legacy callers."""
    import base64, tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        main_p = os.path.join(tmp, "main.mp4")
        cta_p  = os.path.join(tmp, "cta.mp4")
        out_p  = os.path.join(tmp, "out.mp4")
        with open(main_p, "wb") as f: f.write(base64.b64decode(main_b64))
        with open(cta_p,  "wb") as f: f.write(base64.b64decode(cta_b64))
        postprocess_video(main_path=main_p, out_path=out_p, cta_path=cta_p)
        with open(out_p, "rb") as f:
            return base64.b64encode(f.read()).decode()


def overlay_logo_on_video(
    video_b64: str,
    logo_b64: str,
    position: str = "top_left",
    padding: int = 18,
    logo_height: int = 52,
) -> str:
    """DEPRECATED — use postprocess_video() with file paths instead.
    Kept as a b64 wrapper around postprocess_video for any legacy callers."""
    import base64, tempfile, os
    clean_logo = logo_b64
    if "," in clean_logo[:64] and clean_logo.lstrip().startswith("data:"):
        clean_logo = clean_logo.split(",", 1)[1]
    with tempfile.TemporaryDirectory() as tmp:
        vid_p  = os.path.join(tmp, "video.mp4")
        logo_p = os.path.join(tmp, "logo.png")
        out_p  = os.path.join(tmp, "out.mp4")
        with open(vid_p,  "wb") as f: f.write(base64.b64decode(video_b64))
        with open(logo_p, "wb") as f: f.write(base64.b64decode(clean_logo))
        postprocess_video(
            main_path=vid_p, out_path=out_p,
            logo_path=logo_p, logo_position=position,
            logo_padding=padding, logo_height=logo_height,
        )
        with open(out_p, "rb") as f:
            return base64.b64encode(f.read()).decode()


# ── Cloudflare R2 Storage ─────────────────────────────────────────────────────

def _get_r2_client(account_id: str, access_key_id: str, secret_access_key: str):
    """Create a boto3 S3 client pointed at Cloudflare R2."""
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )


def upload_video_to_r2(
    video_base64: str,
    content_id: int,
    mime_type: str,
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
    bucket_name: str,
    public_url: str,
    filename_override: str = "",
) -> str:
    """Upload a base64-encoded video to Cloudflare R2.
    Returns the public URL of the uploaded video."""
    import base64
    import uuid

    video_bytes = base64.b64decode(video_base64)
    ext = "mp4" if "mp4" in mime_type else "webm"
    key = f"assets/{filename_override}" if filename_override else f"videos/{content_id}/{uuid.uuid4().hex}.{ext}"

    client = _get_r2_client(account_id, access_key_id, secret_access_key)
    client.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=video_bytes,
        ContentType=mime_type,
        CacheControl="public, max-age=86400",
    )

    public_url = public_url.rstrip("/")
    return f"{public_url}/{key}"


def delete_video_from_r2(
    video_url: str,
    public_url: str,
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
    bucket_name: str,
) -> bool:
    """Delete a video from Cloudflare R2 given its public URL.
    Returns True if deleted, False if key could not be determined."""
    public_url = public_url.rstrip("/")
    if not video_url.startswith(public_url):
        return False  # Not an R2 URL we own

    key = video_url[len(public_url) + 1:]  # strip "https://pub-xxx.r2.dev/"
    if not key:
        return False

    try:
        client = _get_r2_client(account_id, access_key_id, secret_access_key)
        client.delete_object(Bucket=bucket_name, Key=key)
        return True
    except Exception as e:
        logger.warning(f"R2 delete failed for key {key}: {e}")
        return False


def is_r2_configured(r2_config: dict) -> bool:
    """Check if all required R2 settings are present."""
    required = ["account_id", "access_key_id", "secret_access_key", "bucket_name", "public_url"]
    return all(r2_config.get(k, "").strip() for k in required)
