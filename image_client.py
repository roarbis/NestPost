import asyncio
import httpx
import base64
import json
import re
import io
from PIL import Image

# ── Image Generation Providers ─────────────────────────────────────────────────

IMAGE_PROVIDERS = {
    "imagen4": {
        "name": "Imagen 4",
        "description": "Google Imagen 4 — up to 4 images per prompt",
        "max_images": 4,
        "needs_key": "gemini_api_key",
    },
    "imagen4_fast": {
        "name": "Imagen 4 Fast",
        "description": "Google Imagen 4 Fast — quicker, slightly lower quality",
        "max_images": 4,
        "needs_key": "gemini_api_key",
    },
    "gemini_native": {
        "name": "Nano Banana (Free)",
        "description": "Gemini 2.5 Flash Image — context-aware, high-volume",
        "max_images": 1,
        "needs_key": "gemini_api_key",
    },
    "gemini_native_paid": {
        "name": "Nano Banana 2 (Paid)",
        "description": "Gemini 3.1 Flash Image — highest quality",
        "max_images": 1,
        "needs_key": "gemini_paid_api_key",
    },
    "stability": {
        "name": "Stability AI (SD3.5)",
        "description": "Stable Diffusion 3.5 — fast, reliable",
        "max_images": 4,
        "needs_key": "stability_api_key",
    },
    "dalle": {
        "name": "DALL-E 3",
        "description": "OpenAI DALL-E 3 — excellent prompt following",
        "max_images": 1,
        "needs_key": "openai_api_key",
    },
    "flux_schnell": {
        "name": "FLUX Schnell (fal.ai)",
        "description": "FLUX.1 Schnell via fal.ai — fast, up to 4 images",
        "max_images": 4,
        "needs_key": "fal_api_key",
    },
    "flux_dev": {
        "name": "FLUX Dev (fal.ai)",
        "description": "FLUX.1 Dev via fal.ai — higher quality, up to 4 images",
        "max_images": 4,
        "needs_key": "fal_api_key",
    },
}

# Aspect ratio options with social media context
ASPECT_RATIOS = {
    "1:1": "Square (Instagram feed, Facebook)",
    "4:5": "Portrait (Instagram feed optimal)",
    "9:16": "Story/Reel (Instagram/Facebook Stories)",
    "16:9": "Landscape (LinkedIn, Facebook cover)",
    "3:4": "Portrait (Pinterest-style)",
}


async def refine_image_prompt(
    image_suggestion: str,
    caption: str,
    platform: str,
    api_key: str,
) -> str:
    """Use Gemini text to refine an image_suggestion into a detailed image gen prompt."""
    system = (
        "You are an expert commercial photographer and image prompt engineer. "
        "Given a social media post caption and a rough image suggestion, "
        "create a highly detailed, specific image generation prompt that produces "
        "a stunning, professional image for ConnectNest — a premium smart home "
        "automation company serving customers across Australia.\n\n"
        "STYLE REQUIREMENTS — always include:\n"
        "- Photography style: hyper-realistic, ultra-detailed, 8K resolution\n"
        "- Camera/lens: specify appropriate lens (e.g. 35mm wide-angle for rooms, "
        "85mm portrait lens for close-ups, macro lens for device details)\n"
        "- Lighting: be specific (soft natural window light, golden hour warmth, "
        "cool LED ambient glow, studio rim lighting, etc.)\n"
        "- Composition: specify shot type — close-up, medium shot, wide establishing "
        "shot, overhead flat-lay, low-angle hero shot, or eye-level lifestyle\n"
        "- Depth of field: shallow bokeh for product focus, deep for room scenes\n"
        "- Mood & color palette: modern, premium feel with teal/emerald accents, "
        "warm wood tones, clean whites, matte black smart devices\n"
        "- Setting context: contemporary Australian home (generic — open-plan living, "
        "alfresco area, natural light), modern Australian residential architecture, "
        "minimalist interior design, natural materials. Do NOT name a specific city.\n\n"
        "RULES:\n"
        "- Be vivid and specific about every visual element — leave nothing to imagination\n"
        "- Describe textures, materials, reflections, and surface finishes\n"
        "- Include atmosphere details (morning mist, evening ambience, rain on windows)\n"
        "- Keep the prompt under 250 words\n"
        "- Do NOT include any text, words, logos, or watermarks in the image\n"
        "- Avoid people's faces (use back views, hands, silhouettes, or empty rooms)\n"
        "- Return ONLY the prompt text, nothing else"
    )

    user_prompt = (
        f"Platform: {platform}\n"
        f"Caption: {caption[:300]}\n"
        f"Image suggestion: {image_suggestion}\n\n"
        f"Write the refined image generation prompt:"
    )

    payload = {
        "contents": [{"parts": [{"text": f"{system}\n\n{user_prompt}"}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 500},
    }

    models = ["gemini-2.5-flash", "gemini-2.0-flash"]
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            resp = await client.post(url, json=payload)
            if resp.status_code == 503 and model != models[-1]:
                last_err = Exception(f"{model} 503")
                continue
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip().strip('"')
    raise last_err


async def generate_images_imagen4(
    prompt: str,
    api_key: str,
    num_images: int = 4,
    aspect_ratio: str = "1:1",
    model: str = "imagen-4.0-generate-001",
) -> list[dict]:
    """Generate images using Google Imagen 4 API. Returns list of {base64, mime_type}."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": min(num_images, 4),
            "aspectRatio": aspect_ratio,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    images = []
    for pred in data.get("predictions", []):
        b64 = pred.get("bytesBase64Encoded", "")
        if b64:
            images.append({"base64": b64, "mime_type": "image/png"})
    return images


async def generate_images_gemini_native(
    prompt: str,
    api_key: str,
    aspect_ratio: str = "1:1",
    model: str = "gemini-2.5-flash-preview-image-generation",
) -> list[dict]:
    """Generate image using Gemini native (Nano Banana). Returns list of {base64, mime_type}."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    images = []
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "inlineData" in part:
                inline = part["inlineData"]
                images.append({
                    "base64": inline.get("data", ""),
                    "mime_type": inline.get("mimeType", "image/png"),
                })
    return images


async def generate_images_stability(
    prompt: str,
    api_key: str,
    num_images: int = 4,
    aspect_ratio: str = "1:1",
) -> list[dict]:
    """Generate images using Stability AI API."""
    # Map aspect ratio to dimensions
    dimensions = {
        "1:1": (1024, 1024),
        "4:5": (896, 1120),
        "9:16": (720, 1280),
        "16:9": (1280, 720),
        "3:4": (896, 1120),
    }
    w, h = dimensions.get(aspect_ratio, (1024, 1024))

    url = "https://api.stability.ai/v2beta/stable-image/generate/sd3"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    async def _single_stability_request(client: httpx.AsyncClient) -> dict | None:
        resp = await client.post(
            url,
            headers=headers,
            data={"prompt": prompt, "output_format": "png", "aspect_ratio": aspect_ratio},
        )
        resp.raise_for_status()
        data = resp.json()
        return {"base64": data["image"], "mime_type": "image/png"} if "image" in data else None

    # Fire all requests in parallel — one shared client for connection reuse
    async with httpx.AsyncClient(timeout=120.0) as client:
        tasks = [_single_stability_request(client) for _ in range(min(num_images, 4))]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    images = [r for r in results if isinstance(r, dict)]
    return images


async def generate_images_dalle(
    prompt: str,
    api_key: str,
    num_images: int = 1,
    aspect_ratio: str = "1:1",
) -> list[dict]:
    """Generate images using OpenAI DALL-E 3 API."""
    size_map = {
        "1:1": "1024x1024",
        "16:9": "1792x1024",
        "9:16": "1024x1792",
    }
    size = size_map.get(aspect_ratio, "1024x1024")

    url = "https://api.openai.com/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,  # DALL-E 3 only supports 1 at a time
        "size": size,
        "response_format": "b64_json",
    }

    # DALL-E 3 only supports n=1 per call; run num_images calls in parallel
    async def _single_dalle_request(client: httpx.AsyncClient) -> dict | None:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        imgs = data.get("data", [])
        return {"base64": imgs[0]["b64_json"], "mime_type": "image/png"} if imgs else None

    async with httpx.AsyncClient(timeout=120.0) as client:
        tasks = [_single_dalle_request(client) for _ in range(min(num_images, 4))]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    return [r for r in results if isinstance(r, dict)]


async def generate_images_fal_flux(
    prompt: str,
    api_key: str,
    num_images: int = 4,
    aspect_ratio: str = "1:1",
    model: str = "fal-ai/flux/schnell",
) -> list[dict]:
    """Generate images using FLUX via fal.ai sync API.
    Returns list of {base64, mime_type}."""
    # Map aspect ratios to pixel dimensions
    dimensions = {
        "1:1":  {"width": 1024, "height": 1024},
        "4:5":  {"width": 896,  "height": 1120},
        "9:16": {"width": 720,  "height": 1280},
        "16:9": {"width": 1280, "height": 720},
        "3:4":  {"width": 896,  "height": 1120},
    }
    image_size = dimensions.get(aspect_ratio, {"width": 1024, "height": 1024})

    url = f"https://fal.run/{model}"
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "image_size": image_size,
        "num_images": min(num_images, 4),
        "output_format": "png",
        "enable_safety_checker": True,
        "sync_mode": True,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 401:
            raise ValueError("fal.ai: invalid API key — check Settings → Video Generation → fal.ai API Key")
        if resp.status_code == 403:
            raise ValueError("fal.ai: insufficient credits — top up at fal.ai/dashboard/billing")
        if resp.status_code == 422:
            raise ValueError(f"fal.ai: bad request — {resp.text[:200]}")
        resp.raise_for_status()
        data = resp.json()

    images = []
    img_urls = [img.get("url", "") for img in data.get("images", []) if img.get("url")]

    # Download images and convert to base64
    async with httpx.AsyncClient(timeout=60.0) as client:
        tasks = [client.get(img_url) for img_url in img_urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    for img_resp in responses:
        if isinstance(img_resp, Exception):
            continue
        if img_resp.status_code == 200:
            b64 = base64.b64encode(img_resp.content).decode("utf-8")
            images.append({"base64": b64, "mime_type": "image/png"})

    return images


async def generate_images(
    prompt: str,
    provider: str,
    api_keys: dict,
    num_images: int = 4,
    aspect_ratio: str = "1:1",
) -> list[dict]:
    """Route image generation to the appropriate provider.
    Returns list of {base64, mime_type} dicts.
    """
    if provider == "imagen4":
        key = api_keys.get("gemini", "")
        if not key:
            raise ValueError("Gemini API key required for Imagen 4")
        return await generate_images_imagen4(
            prompt, key, num_images, aspect_ratio, "imagen-4.0-generate-001"
        )

    elif provider == "imagen4_fast":
        key = api_keys.get("gemini", "")
        if not key:
            raise ValueError("Gemini API key required for Imagen 4 Fast")
        return await generate_images_imagen4(
            prompt, key, num_images, aspect_ratio, "imagen-4.0-fast-generate-001"
        )

    elif provider == "gemini_native":
        key = api_keys.get("gemini", "")
        if not key:
            raise ValueError("Gemini API key required for Gemini Native")
        return await generate_images_gemini_native(
            prompt, key, aspect_ratio, "gemini-2.5-flash-image"
        )

    elif provider == "gemini_native_paid":
        key = api_keys.get("gemini_paid", "") or api_keys.get("gemini", "")
        if not key:
            raise ValueError("Gemini Paid API key required for Nano Banana 2")
        return await generate_images_gemini_native(
            prompt, key, aspect_ratio, "gemini-3.1-flash-image-preview"
        )

    elif provider == "stability":
        key = api_keys.get("stability", "")
        if not key:
            raise ValueError("Stability AI API key required")
        return await generate_images_stability(prompt, key, num_images, aspect_ratio)

    elif provider == "dalle":
        key = api_keys.get("openai", "")
        if not key:
            raise ValueError("OpenAI API key required for DALL-E 3")
        return await generate_images_dalle(prompt, key, num_images, aspect_ratio)

    elif provider == "flux_schnell":
        key = api_keys.get("fal", "")
        if not key:
            raise ValueError("fal.ai API key required for FLUX Schnell — add it in Settings → Video Generation")
        return await generate_images_fal_flux(
            prompt, key, num_images, aspect_ratio, "fal-ai/flux/schnell"
        )

    elif provider == "flux_dev":
        key = api_keys.get("fal", "")
        if not key:
            raise ValueError("fal.ai API key required for FLUX Dev — add it in Settings → Video Generation")
        return await generate_images_fal_flux(
            prompt, key, num_images, aspect_ratio, "fal-ai/flux/dev"
        )

    else:
        raise ValueError(f"Unknown image provider: {provider}")


def overlay_logo(image_b64: str, logo_b64: str, image_mime: str = "image/png",
                 logo_mime: str = "image/png", logo_scale: float = 0.06,
                 padding_pct: float = 0.03, opacity: float = 0.85) -> tuple[str, str]:
    """Overlay a logo on the bottom-right corner of an image.

    Args:
        image_b64: Base64 encoded image data
        logo_b64: Base64 encoded logo data (should have transparent background)
        image_mime: MIME type of the source image
        logo_mime: MIME type of the logo
        logo_scale: Logo width as fraction of image width (default 12%)
        padding_pct: Padding from edge as fraction of image width (default 3%)
        opacity: Logo opacity 0.0-1.0 (default 0.85)

    Returns:
        Tuple of (base64_result, mime_type)
    """
    # Decode images
    img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGBA")
    logo = Image.open(io.BytesIO(base64.b64decode(logo_b64))).convert("RGBA")

    # Scale logo relative to image width
    logo_w = int(img.width * logo_scale)
    logo_h = int(logo.height * (logo_w / logo.width))
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

    # Apply opacity
    if opacity < 1.0:
        alpha = logo.getchannel("A")
        alpha = alpha.point(lambda a: int(a * opacity))
        logo.putalpha(alpha)

    # Position: bottom-right with padding
    pad = int(img.width * padding_pct)
    x = img.width - logo_w - pad
    y = img.height - logo_h - pad

    # Composite
    img.paste(logo, (x, y), logo)

    # Convert back to original format
    output = io.BytesIO()
    out_format = "PNG" if "png" in image_mime.lower() else "JPEG"
    if out_format == "JPEG":
        img = img.convert("RGB")
    img.save(output, format=out_format, quality=95)
    result_b64 = base64.b64encode(output.getvalue()).decode("utf-8")
    result_mime = f"image/{out_format.lower()}"
    return result_b64, result_mime
