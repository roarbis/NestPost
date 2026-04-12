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


# ── Video prompt generation (uses Gemini to create 3 style variants) ──────────

async def generate_video_prompts(
    caption: str,
    platform: str,
    image_suggestion: str,
    hook: str,
    api_key: str,
) -> list[dict]:
    """Generate 3 video prompt variants (cinematic, dynamic, minimal) from post content.
    Returns list of {style, prompt, suggested_length, suggested_aspect_ratio}."""

    system = (
        "You are a senior video director and AI video prompt engineer specialising in smart home "
        "and PropTech content for Australian social media (Instagram Reels, TikTok, LinkedIn).\n\n"
        "Given a social media post, generate THREE distinct cinematography briefs optimised for "
        "any AI video model. Each brief must be detailed enough that the AI model can "
        "produce a publish-ready Reel with no ambiguity.\n\n"

        "═══ SMART HOME TECHNICAL VOCABULARY ═══\n"
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

        "═══ OUTPUT RULES ═══\n"
        "- Do NOT include brand names, logos, recognisable faces, or text overlays in prompts\n"
        "- Prompts are for AI video generation — describe only what the camera sees\n"
        "- Use present tense, active voice ('the camera pushes in', not 'camera pushed')\n"
        "- Suggest aspect ratio based on platform: 9:16 Instagram/TikTok, 16:9 LinkedIn, 1:1 feed\n"
        "- Suggest length: 5s (punchy hook), 8s (standard Reel), 10–15s (story/explainer)\n\n"

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

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    payload = {
        "contents": [{"parts": [{"text": f"{system}\n\n{user_prompt}"}]}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 4096},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{url}?key={api_key}", json=payload)
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    # Parse JSON from response (strip markdown fences if present)
    text = text.strip()
    if text.startswith("```"):
        # strip ```json or ``` opener
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()

    prompts = json.loads(text)
    return prompts


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
        return await generate_video_atlascloud(prompt, key, model, aspect_ratio, duration, negative_prompt)

    else:
        raise ValueError(f"Unknown video provider: {provider}")


async def generate_video_atlascloud(
    prompt: str,
    api_key: str,
    model: str = "kwaivgi/kling-v3.0-pro/text-to-video",
    aspect_ratio: str = "9:16",
    duration: int = 5,
    negative_prompt: str = "",
) -> dict:
    """Generate video via Atlas Cloud aggregator API (queue-based).
    Docs: https://www.atlascloud.ai/docs/models/video
    POST /api/v1/model/generateVideo → returns prediction_id → poll /api/v1/model/prediction/{id}"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": str(duration),
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

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

    return await _poll_atlascloud(prediction_id, api_key)


async def _poll_atlascloud(prediction_id: str, api_key: str, max_wait: int = 600) -> dict:
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
                    # Download and return as base64
                    async with httpx.AsyncClient(timeout=60.0) as dl:
                        vresp = await dl.get(video_url)
                        vresp.raise_for_status()
                    import base64
                    return {
                        "status": "complete",
                        "video_base64": base64.b64encode(vresp.content).decode(),
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


# ── CTA Video Concat ─────────────────────────────────────────────────────────

def concat_cta_video(main_b64: str, cta_b64: str, mime_type: str = "video/mp4") -> str:
    """Concatenate main video + CTA clip using FFmpeg.
    Both inputs are base64-encoded. Returns base64-encoded merged mp4."""
    import base64
    import subprocess
    import tempfile
    import os

    ext = "mp4"
    with tempfile.TemporaryDirectory() as tmp:
        main_path = os.path.join(tmp, f"main.{ext}")
        cta_path  = os.path.join(tmp, f"cta.{ext}")
        out_path  = os.path.join(tmp, f"out.{ext}")
        list_path = os.path.join(tmp, "concat.txt")

        with open(main_path, "wb") as f:
            f.write(base64.b64decode(main_b64))
        with open(cta_path, "wb") as f:
            f.write(base64.b64decode(cta_b64))

        # FFmpeg concat demuxer — lossless, no re-encode needed when codecs match
        with open(list_path, "w") as f:
            f.write(f"file '{main_path}'\nfile '{cta_path}'\n")

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                out_path,
            ],
            capture_output=True,
            timeout=120,
        )

        if result.returncode != 0:
            # If codec copy fails (different codecs/resolutions), re-encode
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", list_path,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac",
                    out_path,
                ],
                capture_output=True,
                timeout=180,
            )
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg concat failed: {result.stderr.decode()[:300]}")

        with open(out_path, "rb") as f:
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
