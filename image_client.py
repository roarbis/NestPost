import httpx
import base64
import json
import re

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
        "You are an expert at writing image generation prompts. "
        "Given a social media post caption and a rough image suggestion, "
        "create a detailed, specific image generation prompt that would produce "
        "a professional, brand-appropriate image for a smart home automation company "
        "(ConnectNest, Melbourne, Australia).\n\n"
        "Rules:\n"
        "- Be specific about style: modern, clean, bright, professional photography\n"
        "- Include lighting, composition, and mood details\n"
        "- Mention specific objects, colors, and settings\n"
        "- Keep the prompt under 200 words\n"
        "- Do NOT include text/words in the image — social media text goes in the caption\n"
        "- Avoid people's faces (use back views, hands, or empty rooms)\n"
        "- Return ONLY the prompt text, nothing else"
    )

    user_prompt = (
        f"Platform: {platform}\n"
        f"Caption: {caption[:300]}\n"
        f"Image suggestion: {image_suggestion}\n\n"
        f"Write the refined image generation prompt:"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": f"{system}\n\n{user_prompt}"}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 300},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return text.strip().strip('"')


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

    images = []
    for _ in range(min(num_images, 4)):
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                data={
                    "prompt": prompt,
                    "output_format": "png",
                    "aspect_ratio": aspect_ratio,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if "image" in data:
                images.append({"base64": data["image"], "mime_type": "image/png"})
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

    images = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        for img in data.get("data", []):
            images.append({"base64": img["b64_json"], "mime_type": "image/png"})
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

    else:
        raise ValueError(f"Unknown image provider: {provider}")
