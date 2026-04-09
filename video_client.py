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

FFMPEG_PATH = os.environ.get(
    "FFMPEG_PATH", str(Path(__file__).parent.parent / "ffmpeg" / "ffmpeg.exe")
)

# ── Video Provider Registry ───────────────────────────────────────────────────

VIDEO_PROVIDERS = {
    # ── Free tier ──
    "veo3_free": {
        "name": "Veo 3 (Free)",
        "description": "Google Veo 3 via Gemini API — top quality, free tier ~5-10/day",
        "paid": False,
        "needs_key": "gemini_api_key",
        "max_length": 8,
        "quality": 5,
    },
    "kling_free": {
        "name": "Kling AI (Free)",
        "description": "Kling AI — good motion coherence, 66 free credits/day",
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
        "name": "Kling AI Pro",
        "description": "Kling AI Pro — 1080p, no watermark",
        "paid": True,
        "needs_key": "kling_api_key",
        "max_length": 10,
        "quality": 4,
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
        "You are an expert video director and AI video prompt engineer. "
        "Given a social media post caption and context, create THREE distinct video "
        "generation prompts optimised for AI video models (Veo, Kling, Runway).\n\n"
        "Each prompt should describe a 5-15 second video clip.\n\n"
        "THE THREE STYLES:\n"
        "1. **Cinematic** — dramatic lighting, slow camera movements, film-grade color grading, "
        "shallow depth of field, anamorphic lens feel\n"
        "2. **Dynamic** — fast cuts, energetic motion, bold transitions, punchy rhythm, "
        "action-oriented camera work (dolly, tracking, reveal shots)\n"
        "3. **Minimal** — clean, simple, elegant. Static or gentle motion, lots of negative "
        "space, soft lighting, zen-like calm, focus on one subject\n\n"
        "PROMPT RULES:\n"
        "- Describe the visual scene vividly: setting, objects, lighting, camera movement, mood\n"
        "- Specify camera angle and motion (e.g., 'slow dolly forward', 'aerial descending shot')\n"
        "- Include lighting and color palette details\n"
        "- Reference smart home / technology context when relevant\n"
        "- Each prompt should be 50-100 words\n"
        "- Do NOT include text overlays, logos, or UI elements in the video description\n"
        "- Do NOT mention brand names\n"
        "- Avoid depicting recognisable faces\n\n"
        "Also suggest the ideal video length (5, 8, 10, or 15 seconds) and aspect ratio "
        "(9:16 for Reels/Stories, 16:9 for LinkedIn/YouTube, 1:1 for feed posts) "
        "based on the target platform.\n\n"
        "Return ONLY valid JSON array with exactly 3 objects:\n"
        '[\n  {"style": "Cinematic", "prompt": "...", "suggested_length": 8, "suggested_aspect_ratio": "9:16"},\n'
        '  {"style": "Dynamic", "prompt": "...", "suggested_length": 8, "suggested_aspect_ratio": "9:16"},\n'
        '  {"style": "Minimal", "prompt": "...", "suggested_length": 8, "suggested_aspect_ratio": "9:16"}\n]'
    )

    user_prompt = (
        f"Platform: {platform}\n"
        f"Caption: {caption[:500]}\n"
        f"Visual suggestion: {image_suggestion or 'N/A'}\n"
        f"Hook: {hook or 'N/A'}\n\n"
        f"Generate the three video prompts:"
    )

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    payload = {
        "contents": [{"parts": [{"text": f"{system}\n\n{user_prompt}"}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048},
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
    url = "https://generativelanguage.googleapis.com/v1beta/models/veo-3.0-generate-preview:generateVideos"

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
            return {"status": "error", "error": "Veo 3 not available on this API key. Request access at ai.google.dev, or use Kling AI / stock footage instead."}
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
    while time.time() - start < max_wait:
        await asyncio.sleep(5)
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

    payload = {
        "model_name": "kling-v1",   # required field
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": kling_duration,
        "mode": mode,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            return {"status": "rate_limited", "error": "Kling daily limit reached."}
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
    while time.time() - start < max_wait:
        await asyncio.sleep(5)
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
    while time.time() - start < max_wait:
        await asyncio.sleep(5)
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
    while time.time() - start < max_wait:
        await asyncio.sleep(5)
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


# ── Router ────────────────────────────────────────────────────────────────────

async def generate_video(
    prompt: str,
    provider: str,
    api_keys: dict,
    aspect_ratio: str = "9:16",
    duration: int = 8,
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
        return await generate_video_kling(prompt, access_key, secret_key, aspect_ratio, duration, mode)

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

    else:
        raise ValueError(f"Unknown video provider: {provider}")


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
) -> str:
    """Upload a base64-encoded video to Cloudflare R2.
    Returns the public URL of the uploaded video."""
    import base64
    import uuid

    video_bytes = base64.b64decode(video_base64)
    ext = "mp4" if "mp4" in mime_type else "webm"
    key = f"videos/{content_id}/{uuid.uuid4().hex}.{ext}"

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
