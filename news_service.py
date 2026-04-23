"""Smart-home news aggregator — fetches from curated RSS/Atom feeds.
Results are cached in-memory for NEWS_CACHE_TTL seconds (2 hours)."""

import time
import re
import httpx
import feedparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

NEWS_CACHE_TTL = 7200  # 2 hours

# Category keyword maps for client-side and server-side filtering
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "security":   ["security", "camera", "lock", "alarm", "surveillance", "motion", "sensor", "doorbell"],
    "lighting":   ["light", "lighting", "bulb", "switch", "dim", "lamp", "led", "hue"],
    "climate":    ["thermostat", "climate", "energy", "heating", "cooling", "hvac", "solar", "power", "temperature", "nest thermostat"],
    "automation": ["automate", "routine", "schedule", "trigger", "scene", "hub", "integration", "diy", "home assistant", "node-red"],
    "ecosystem":  ["matter", "thread", "zigbee", "z-wave", "homekit", "google home", "alexa", "amazon", "siri", "smartthings", "apple home"],
}

# Curated default smart-home feeds
DEFAULT_FEEDS: list[dict] = [
    {"url": "https://www.theverge.com/smart-home/rss/index.xml",                     "source": "The Verge"},
    {"url": "https://www.home-assistant.io/atom.xml",                                "source": "Home Assistant"},
    {"url": "https://automatedhome.com/feed/",                                       "source": "Automated Home"},
    {"url": "https://hackaday.com/tag/home-automation/feed/",                        "source": "Hackaday"},
    {"url": "https://mightygadget.co.uk/category/home-automation/feed/",             "source": "Mighty Gadget"},
    {"url": "https://econtroldevices.com/feed/",                                     "source": "eControl Devices"},
    {"url": "https://hometechhacker.com/feed/",                                      "source": "Home Tech Hacker"},
    {"url": "https://www.smarthomeworld.in/feed/",                                   "source": "Smart Home World"},
    {"url": "https://www.loxone.com/enen/feed/",                                     "source": "Loxone"},
    {"url": "https://terrywhite.com/category/home-automation/feed/",                 "source": "Terry White"},
    {"url": "https://www.thesmarthomehookup.com/feed/",                              "source": "Smart Home Hookup"},
    {"url": "https://www.tsp.space/smart-home-blog/feed/",                           "source": "TSP Space"},
    {"url": "https://blog.coldwellbanker.com/category/smart-home/feed/",             "source": "Coldwell Banker"},
    {"url": "https://living-smarter.com/feed/",                                      "source": "Living Smarter"},
    {"url": "https://digitized.house/feed/",                                         "source": "Digitized House"},
    {"url": "https://www.smarthomegeeks.co.uk/feed/",                                "source": "Smart Home Geeks"},
    {"url": "https://linkyourhouse.com/feed/",                                       "source": "Link Your House"},
    {"url": "https://www.gridconnect.com/blogs/news.atom",                           "source": "Grid Connect"},
    {"url": "https://www.levelupyourhome.com/blogs/level-up-smart-stuff.atom",       "source": "Level Up Your Home"},
    {"url": "https://blog.leviton.com/taxonomy/term/128/all/feed",                  "source": "Leviton"},
    {"url": "https://www.thehomeautomationblog.com/feed/",                           "source": "Home Automation Blog"},
    {"url": "https://buildyoursmarthome.co/feed/",                                   "source": "Build Your Smart Home"},
    {"url": "https://www.smarthome.com.au/blog/feed/",                               "source": "Smart Home AU"},
]

_cache: dict = {"articles": [], "fetched_at": 0.0, "custom_feeds_str": ""}


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_one(feed_cfg: dict) -> list[dict]:
    """Fetch + parse one RSS/Atom feed synchronously (called from thread pool)."""
    try:
        parsed = feedparser.parse(feed_cfg["url"])
        articles = []
        for entry in parsed.entries[:5]:  # max 5 per source
            title = _strip_html(entry.get("title", "")).strip()
            if not title:
                continue
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary = _strip_html(summary_raw)[:350]
            link = entry.get("link", "")
            published = entry.get("published", "") or entry.get("updated", "")
            articles.append({
                "title": title,
                "summary": summary,
                "url": link,
                "source": feed_cfg["source"],
                "published": published,
            })
        return articles
    except Exception:
        return []


def _build_feed_list(custom_feeds_str: str) -> list[dict]:
    feeds = list(DEFAULT_FEEDS)
    if custom_feeds_str:
        for line in custom_feeds_str.splitlines():
            url = line.strip()
            if url and url.startswith("http"):
                feeds.append({"url": url, "source": _source_label(url)})
    return feeds


def _source_label(url: str) -> str:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.replace("www.", "")
        return host.split(".")[0].replace("-", " ").title()
    except Exception:
        return "Custom"


def get_articles(
    category: Optional[str] = None,
    custom_feeds_str: str = "",
    limit: int = 12,
    force_refresh: bool = False,
) -> list[dict]:
    """Return articles from cache, refreshing if stale or feeds changed."""
    global _cache
    now = time.time()
    stale = (now - _cache["fetched_at"]) > NEWS_CACHE_TTL
    feeds_changed = _cache["custom_feeds_str"] != custom_feeds_str

    if force_refresh or stale or feeds_changed:
        feeds = _build_feed_list(custom_feeds_str)
        all_articles: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(len(feeds), 12)) as pool:
            futures = {pool.submit(_parse_one, f): f for f in feeds}
            try:
                for future in as_completed(futures, timeout=25):
                    try:
                        all_articles.extend(future.result())
                    except Exception:
                        pass
            except TimeoutError:
                # Collect results from any futures that finished before timeout
                for future in futures:
                    if future.done():
                        try:
                            all_articles.extend(future.result())
                        except Exception:
                            pass
        _cache = {
            "articles": all_articles,
            "fetched_at": now,
            "custom_feeds_str": custom_feeds_str,
        }

    articles = _cache["articles"]

    if category and category in CATEGORY_KEYWORDS:
        kws = CATEGORY_KEYWORDS[category]
        articles = [
            a for a in articles
            if any(kw in (a["title"] + " " + a["summary"]).lower() for kw in kws)
        ]

    return articles[:limit]


async def fetch_article_url(url: str) -> dict:
    """Fetch an arbitrary article URL and extract title + description as a news seed."""
    async with httpx.AsyncClient(
        timeout=12.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; NestPost/1.0)"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text

    # og:title > <title>
    og_title = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']{3,})["\']',
        html, re.IGNORECASE
    )
    title_tag = re.search(r"<title[^>]*>([^<]{3,})</title>", html, re.IGNORECASE)
    title = (og_title.group(1) if og_title else (title_tag.group(1) if title_tag else "")).strip()

    # og:description > meta description
    og_desc = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{10,})["\']',
        html, re.IGNORECASE
    )
    meta_desc = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{10,})["\']',
        html, re.IGNORECASE
    )
    summary = (og_desc.group(1) if og_desc else (meta_desc.group(1) if meta_desc else "")).strip()[:350]

    if not title:
        raise ValueError("Could not extract article title from that URL")

    from urllib.parse import urlparse
    source = urlparse(url).netloc.replace("www.", "")

    return {"title": title, "summary": summary, "url": url, "source": source}
