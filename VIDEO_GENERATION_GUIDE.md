# ConnectNest — Video Generation Guide
_Last updated: March 2026_

---

## Overview

This guide covers every option for creating social media video content for ConnectNest,
from fully manual through to heavily automated approaches. The goal is to reduce
video production time from the current 4-5 hours down to 30-60 minutes of human effort.

---

## 1. AI Video Generation Tools

### Quality Tiers (March 2026)

| Tool | Realism | Consistency | Cost | API? | Best Use |
|------|---------|-------------|------|------|----------|
| **Sora (OpenAI)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ~$20-200/mo | Yes (limited) | Photorealistic scenes |
| **Kling AI** | ⭐⭐⭐⭐½ | ⭐⭐⭐⭐ | ~$10/mo | Yes | Best motion coherence |
| **Google Veo 2** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Limited access | Vertex AI | Photorealistic |
| **Runway Gen-3** | ⭐⭐⭐⭐ | ⭐⭐⭐½ | ~$15/mo | Yes | Stylised clips, reliable |
| **Luma Dream Machine** | ⭐⭐⭐ | ⭐⭐⭐ | Free tier / $30/mo | Yes | Good starting point |
| **Pika Labs** | ⭐⭐⭐ | ⭐⭐½ | Free tier / $8/mo | Limited | Short accent clips |

### Pika Labs — Reliability Assessment
- **Usable output rate:** ~55-65% on first generation
- **Strengths:** Fun visual effects (zoom bursts, liquify transitions), good for 3-5s accent clips
- **Weaknesses:** Motion artifacts on complex scenes, inconsistent between tries, text generation poor
- **Best for ConnectNest:** Transition effects, abstract "smart home glow" sequences
- **Automation level:** Limited API — best used manually or via webhook

### Luma Dream Machine — Reliability Assessment
- **Usable output rate:** ~65-75% on first generation
- **Strengths:** Better realistic motion than Pika, good product-style "reveal" shots
- **Weaknesses:** 5-10 second clip limit, occasional drift/distortion in later frames
- **Best for ConnectNest:** Door/lock close-ups, phone screen reveals, lifestyle B-roll accents
- **Automation level:** Has REST API — can be called programmatically from NestPost

### Honest Assessment (2026)
AI video is still best used as **accent clips** (3-7 seconds) layered into a larger video
rather than as the primary footage. Photorealistic Melbourne suburban content
(specific locations, Australian homes) is still unreliable from AI generators.
**Hybrid approach** (stock footage + AI accents + branded text) is the current sweet spot.

---

## 2. Stock Footage Libraries

### Free Commercial-Use Sources

| Platform | API Available | Quality | Best For |
|----------|--------------|---------|----------|
| **Pexels** | ✅ Yes (free) | ⭐⭐⭐⭐⭐ | Everything — best library |
| **Pixabay** | ✅ Yes (free) | ⭐⭐⭐⭐ | Good depth, slightly older content |
| **Coverr** | ❌ No API | ⭐⭐⭐⭐ | Lifestyle/home content |
| **Mixkit** | ❌ No API | ⭐⭐⭐⭐ | High quality, curated |
| **Videvo** (free tier) | ❌ No API | ⭐⭐⭐ | Some require attribution |

### Automation Potential

**Pexels API** and **Pixabay API** are both free and allow:
- Keyword search for videos (e.g. "smart home", "security camera", "family Melbourne")
- Filter by orientation (portrait for Reels), resolution, duration
- Direct download URLs — no manual downloading needed
- This enables a fully automated pipeline: topic → keyword → API → downloaded clips

**FFmpeg** (free, open source) can then:
- Trim clips to required length
- Resize to 9:16 (Reels format) with smart cropping
- Concatenate multiple clips
- Overlay text captions with brand fonts/colours
- Add ConnectNest logo watermark
- Normalise audio / add background music
- Export at correct bitrate for Instagram/LinkedIn/Facebook

**Automation level achievable: ~80%** of the assembly process

### ConnectNest-Specific Search Keywords

For Pexels/Pixabay API queries:
```
Smart home:      "smart home", "home automation", "smart lighting"
Security:        "security camera", "doorbell", "home security", "lock"
Travel/Peace:    "holiday relaxation", "travelling couple", "phone remote"
Garage:          "garage door", "driveway", "suburban home"
Lifestyle:       "family home", "Melbourne suburb" (limited — use "australian home")
Energy:          "solar panels", "energy saving", "smart thermostat"
```

---

## 3. Talking Head / Avatar Video (HeyGen & Synthesia)

### Platform Fit for Instagram

| Platform | LinkedIn | Instagram | Facebook |
|----------|----------|-----------|----------|
| Talking head style | ✅ Excellent | ⚠️ Works if < 30s | ✅ Good |
| Full-video avatar | ✅ Great | ❌ Too boring | ⚠️ OK |
| Avatar intro + B-roll mix | ✅ | ✅ Best of both | ✅ |

**Instagram reality:** Pure talking head content underperforms on Instagram Reels.
However, a 5-second avatar hook ("Did you know your home can call you when it detects motion?")
followed by B-roll footage performs very well. Think of it as a news-style open.

### API Automation

Both tools have APIs that accept text input and return a video URL:

**Synthesia API:**
```
POST https://api.synthesia.io/v2/videos
{
  "test": false,
  "title": "ConnectNest Smart Security",
  "description": "Weekly social post",
  "visibility": "private",
  "aspectRatio": "9:16",
  "scenes": [{
    "avatar": "anna_costume1_cameraA",
    "script": "Did you know you can check your front door from Bali?..."
  }]
}
```

**HeyGen API:** Similar structure, also supports 9:16 vertical format.

**Result:** Given an approved NestPost caption, the script can be extracted automatically,
sent to Synthesia/HeyGen API, and the video URL saved back to NestPost — zero manual steps.

**Cost:** Synthesia ~$22/mo (125 mins), HeyGen ~$29/mo (unlimited videos, 3 min each)

---

## 4. Canva Automation

### What ConnectNest Already Has
- Paid Canva account ✅
- Slide-based Reels with animated text/transitions ✅
- Brand kit (fonts, colours, logo) ✅

### Current Time: 4-5 hours per video — Breakdown

| Step | Time | Automatable? |
|------|------|-------------|
| Write script/concept | 60-90 min | ✅ NestPost already does this |
| Find visuals/stock footage | 45-60 min | ✅ Pexels API + auto-download |
| Build slides in Canva | 90-120 min | ⚠️ Partially (Bulk Create) |
| Add captions, timing, music | 30-45 min | ✅ FFmpeg / Canva template |
| Export + format check | 15-20 min | ✅ Automated export |
| Upload to platforms | 15 min | 🔜 Phase 2 auto-posting |
| **Total** | **4-5 hrs** | |

### Canva Automation Options

**Option A — Bulk Create (Best for slides)**
1. Design ONE master Canva template per content type (myth buster, tip, pain point, etc.)
2. NestPost generates the text (hook, 3 key points, CTA)
3. Export as CSV → upload to Canva Bulk Create → generates N videos automatically
4. Download batch → ready to post
5. **Human time required: ~30 min** (review + download)

**Option B — Canva Developer API**
- Canva has a developer API but it is limited for automated design generation
- Better for reading/exporting existing designs than creating new ones
- Not recommended as primary automation path

**Option C — Remotion (React-based video generation)**
- Open source tool that renders videos programmatically using React components
- You define the template once in code, then pass different text/images
- Renders to MP4 via command line — no Canva dependency
- Full automation possible: NestPost content → Remotion → MP4 → ready to post
- **Learning curve:** Requires basic React/JS knowledge
- **Human time required: ~5-10 min** (just review the output)

**Option D — FFmpeg Pipeline (Most Automated)**
- Pure command-line video generation
- Download clips from Pexels API → FFmpeg assembles → add text overlay → add music → export
- No design tool needed at all
- Less "polished" than Canva but consistent and fast
- **Human time required: ~10-15 min** (review + adjust)

---

## 5. Recommended Automation Stack for ConnectNest

### Short-Term (Phase 1 — No new tools needed)

```
NestPost generates content (already works)
    ↓
Claude auto-searches Pexels API for 3-5 relevant clips
    ↓
Claude downloads clips + royalty-free music from Pixabay
    ↓
FFmpeg assembles: clips + text overlays + logo + music → MP4
    ↓
NestPost stores the video alongside the caption/hashtags
    ↓
Human reviews (5-10 min) and posts
```
**Estimated human time: 15-20 min vs current 4-5 hours**

### Medium-Term (Phase 2 — Small investment)

```
NestPost generates content + video script
    ↓
Synthesia/HeyGen API generates 5s presenter hook (auto)
    ↓
Pexels API fetches B-roll clips (auto)
    ↓
FFmpeg merges hook + B-roll + captions + music (auto)
    ↓
Auto-post to LinkedIn/Facebook (Phase 2 auto-posting)
    ↓
Human reviews Instagram and posts manually (5 min)
```
**Estimated human time: 5-10 min**

---

## 6. Legal Framework (Australia)

### What's Allowed

| Source | Commercial Use | Attribution |
|--------|---------------|-------------|
| Pexels videos | ✅ Free commercial | Not required |
| Pixabay videos | ✅ Free commercial | Not required |
| Coverr videos | ✅ Free commercial | Not required |
| Mixkit videos | ✅ Free commercial | Not required |
| AI-generated video (your prompts) | ✅ You own it | N/A |
| Your own customer videos | ✅ With written permission | Thank them publicly |
| Your own install/product footage | ✅ Completely | N/A |
| Creative Commons CC0 video | ✅ | Not required |
| Creative Commons CC-BY video | ✅ | Credit required |

### What's NOT Allowed (Australia — Fair Dealing, NOT Fair Use)

| Action | Legal? | Notes |
|--------|--------|-------|
| Clip from YouTube/Instagram video | ❌ | Copyright infringement |
| Recording a competitor's ad | ❌ | Even 2-3 seconds |
| Using a song from Spotify/Apple | ❌ | Always flagged by platforms |
| "De minimis" (tiny clip) defence | ❌ Unreliable | Not codified in AU law |
| Reaction/commentary videos | ⚠️ Grey area | Only if genuinely transformative |

### Safe Music Sources

| Source | Cost | Commercial OK |
|--------|------|--------------|
| YouTube Audio Library | Free | ✅ |
| Pixabay Music | Free | ✅ |
| Uppbeat (free tier) | Free | ✅ (with credit) |
| Epidemic Sound | ~$15/mo | ✅ |
| Artlist | ~$200/yr | ✅ |

---

## 7. NestPost Video Pipeline — Planned Features

- [ ] `POST /api/video/script` — Generate shot-by-shot video script from caption
- [ ] `POST /api/video/footage` — Auto-search Pexels API and return download URLs
- [ ] `POST /api/video/assemble` — Call FFmpeg to create final video
- [ ] `GET /api/video/{id}` — Return video file for review
- [ ] Video content type in the library (alongside static posts)
- [ ] Video preview in the content modal
- [ ] Canva Bulk Create CSV export

---

## 8. Quick Reference — ConnectNest Video Template

### Reel Structure (30 seconds)
```
0:00-0:03  Hook clip + bold text overlay (pain point or question)
0:03-0:10  Problem clips (2-3 cuts showing the "without ConnectNest" scenario)
0:10-0:22  Solution clips (ConnectNest app, smart devices, family peace of mind)
0:22-0:27  Result/benefit + price point ($299 installed)
0:27-0:30  Logo + CTA (link in bio / book free consultation)
```

### Text Overlay Timing
- Keep each text overlay to max 3 seconds
- Max 6-7 words per overlay
- Always caption the full video (85% of Reels watched without sound)
- Use ConnectNest brand colours: Indigo (#6366f1) and White (#ffffff)

### Aspect Ratios
- Instagram Reels / TikTok: 9:16 (1080x1920)
- LinkedIn video: 16:9 (1920x1080) or 1:1 (1080x1080)
- Facebook: Both 9:16 and 16:9 work

---

_This guide is a living document — update as new tools emerge._
