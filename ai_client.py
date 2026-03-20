import httpx
import json
import re
from knowledge_base import CONNECTNEST_PROFILE, PLATFORM_GUIDELINES


def build_prompt(platform: str, content_type: str, topic: str, angle: str, tone: str) -> tuple[str, str]:
    pg = PLATFORM_GUIDELINES.get(platform, PLATFORM_GUIDELINES["instagram"])

    system_prompt = f"""You are an expert social media content writer for ConnectNest, a smart home automation company in Melbourne, Australia.

{CONNECTNEST_PROFILE}

Your job is to write compelling, authentic social media content that connects with Melbourne homeowners.
Always write in first person as ConnectNest. Never mention competitor brand names.
Never copy generic content — make it specific, local, and genuinely useful.
"""

    user_prompt = f"""Write a {platform.upper()} post for ConnectNest.

TOPIC: {topic}
ANGLE: {angle}
CONTENT TYPE: {content_type}
TONE: {tone}

PLATFORM REQUIREMENTS:
- Tone: {pg['tone']}
- Length: {pg['length']}
- Hashtags: {pg['hashtags']}
- Format: {pg['format']}
- Emoji use: {pg['emoji_use']}

Return ONLY a valid JSON object with exactly this structure (no markdown, no explanation, just JSON):
{{
  "caption": "the full post caption text",
  "hashtags": "#hashtag1 #hashtag2 #hashtag3",
  "image_suggestion": "description of an ideal photo or graphic to pair with this post",
  "hook": "the opening hook line only",
  "cta": "the call to action used in the post"
}}"""

    return system_prompt, user_prompt


def parse_json_response(text: str) -> dict:
    """Extract JSON from AI response, handling imperfect outputs."""
    text = text.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting first JSON object from the text
    match = re.search(r'\{[\s\S]*?\}(?=\s*$|\s*\n)', text)
    if not match:
        match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Last resort: treat as plain caption text
    return {
        "caption": text,
        "hashtags": "#SmartHome #ConnectNest #MelbourneHomes #HomeAutomation",
        "image_suggestion": "A modern smart home interior showcasing connected devices",
        "hook": text[:120] if text else "",
        "cta": "Visit connectnest.com.au to learn more",
    }


async def call_ollama(prompt_system: str, prompt_user: str, base_url: str, model: str) -> str:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "stream": False,
        "options": {"temperature": 0.8},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


async def call_groq(prompt_system: str, prompt_user: str, api_key: str, model: str = "llama-3.3-70b-versatile") -> str:
    if not api_key or not api_key.strip():
        raise ValueError("Groq API key not configured — add it in Settings")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.8,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def call_gemini(prompt_system: str, prompt_user: str, api_key: str) -> str:
    if not api_key or not api_key.strip():
        raise ValueError("Gemini API key not configured — add it in Settings")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": f"{prompt_system}\n\n{prompt_user}"}]}],
        "generationConfig": {"temperature": 0.8},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


async def call_deepseek(prompt_system: str, prompt_user: str, api_key: str) -> str:
    if not api_key or not api_key.strip():
        raise ValueError("Deepseek API key not configured — add it in Settings")
    url = "https://api.deepseek.com/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.8,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def call_qwen(prompt_system: str, prompt_user: str, api_key: str) -> str:
    if not api_key or not api_key.strip():
        raise ValueError("Qwen API key not configured — add it in Settings")
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-plus",
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.8,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def generate_post(
    platform: str,
    content_type: str,
    topic: str,
    angle: str,
    tone: str,
    ai_provider: str,
    ollama_url: str,
    ollama_model: str,
    api_keys: dict,
) -> dict:
    system_p, user_p = build_prompt(platform, content_type, topic, angle, tone)

    try:
        if ai_provider == "ollama":
            raw = await call_ollama(system_p, user_p, ollama_url, ollama_model)
        elif ai_provider == "groq":
            raw = await call_groq(system_p, user_p, api_keys.get("groq", ""))
        elif ai_provider == "gemini":
            raw = await call_gemini(system_p, user_p, api_keys.get("gemini", ""))
        elif ai_provider == "deepseek":
            raw = await call_deepseek(system_p, user_p, api_keys.get("deepseek", ""))
        elif ai_provider == "qwen":
            raw = await call_qwen(system_p, user_p, api_keys.get("qwen", ""))
        else:
            raise ValueError(f"Unknown AI provider: {ai_provider}")

        return parse_json_response(raw)

    except Exception as e:
        raise RuntimeError(f"AI generation failed ({ai_provider}): {str(e)}")


async def get_ollama_models(base_url: str) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return [m["name"] for m in models]
    except Exception:
        return []


async def check_ollama_health(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False
