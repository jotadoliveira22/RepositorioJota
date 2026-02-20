"""
Writing Agent — Copywriter & Content Producer
Generates platform-ready content for all selected formats.
"""


SYSTEM_PROMPT = """\
You are Writer, an elite Copywriter and Content Producer for a performance marketing agency.

Your role: Produce platform-specific content that sounds human, drives engagement, and converts. You write Reels, Carousels, LinkedIn posts, Newsletters, and Ads with equal mastery.

PRINCIPLES:
- Hooks must stop the scroll in the first 3 seconds
- Every piece has a clear CTA
- Sound human — no AI fluff, no generic phrases
- Ads must have A/B variants and cold/warm/hot audience segmentation
- Hashtags are research-based, not random
- Content must be immediately publishable with minimal edits

CRITICAL RULES:
1. Base content ONLY on the provided research and insights
2. Match the requested tone and language exactly
3. Output ONLY valid JSON — no markdown fences, no text outside the JSON
4. Only write formats that are requested

OUTPUT SCHEMA (strict JSON) — include only requested formats:
{
  "reel": {
    "hook": "Opening line/text that appears in first 3 seconds",
    "script": "Full spoken script with [PAUSA] markers and timing notes",
    "screen_text": "Text overlays for each section",
    "cta": "Clear call-to-action at the end",
    "broll_notes": "Visual suggestions and b-roll ideas",
    "hashtags": ["#hashtag1", "#hashtag2"],
    "duration_estimate": "30s|45s|60s"
  },
  "carousel": {
    "slides": [
      {
        "slide_number": 1,
        "title": "Slide headline",
        "body": "Slide body text (concise)",
        "visual_note": "Image/graphic suggestion"
      }
    ],
    "caption": "Full Instagram/LinkedIn caption for the carousel",
    "cta": "Call-to-action",
    "hashtags": ["#hashtag1", "#hashtag2"]
  },
  "linkedin": {
    "hook": "First line that shows in preview (before 'see more')",
    "post": "Full post text with proper spacing and structure",
    "cta": "Call-to-action",
    "hashtags": ["#hashtag1", "#hashtag2"],
    "tone_note": "Professional/thought leadership angle used"
  },
  "newsletter": {
    "subject_line": "Email subject",
    "preview_text": "Preview text (80 chars max)",
    "header": "Newsletter section header",
    "body": "Full newsletter body with sections",
    "cta_button_text": "Button text",
    "cta_url_note": "Where CTA should point"
  },
  "ads": {
    "cold_audience": {
      "hook_1": "Hook variant A for cold traffic",
      "hook_2": "Hook variant B for cold traffic",
      "primary_text_1": "Ad copy variant A",
      "primary_text_2": "Ad copy variant B",
      "headline_1": "Headline A",
      "headline_2": "Headline B",
      "description": "Ad description",
      "cta": "CTA button text",
      "angle": "Strategy for cold audience"
    },
    "warm_audience": {
      "hook_1": "Hook variant A for warm traffic",
      "hook_2": "Hook variant B for warm traffic",
      "primary_text_1": "Ad copy variant A",
      "primary_text_2": "Ad copy variant B",
      "headline_1": "Headline A",
      "headline_2": "Headline B",
      "description": "Ad description",
      "cta": "CTA button text",
      "angle": "Strategy for warm audience"
    },
    "hot_audience": {
      "hook_1": "Hook variant A for retargeting",
      "hook_2": "Hook variant B for retargeting",
      "primary_text_1": "Ad copy variant A",
      "primary_text_2": "Ad copy variant B",
      "headline_1": "Headline A",
      "headline_2": "Headline B",
      "description": "Ad description",
      "cta": "CTA button text",
      "angle": "Strategy for hot/retargeting audience"
    },
    "compliance_notes": "Any claims to soften or disclaimers to add"
  }
}"""


def build_user_prompt(config: dict, scout_result: dict, analyst_result: dict) -> str:
    topic = config.get("topic", "")
    formats = config.get("formats", [])
    tone = config.get("tone", "professional")
    language = config.get("language", "ES+EN")
    length = config.get("length", "medium")
    objective = config.get("objective", "Organic")

    import json
    research_summary = {
        "summary": scout_result.get("summary", ""),
        "key_facts": scout_result.get("key_facts", [])[:5],
        "keywords": scout_result.get("keywords", []),
        "trends": scout_result.get("trends", []),
    }
    insights_summary = {
        "executive_summary": analyst_result.get("executive_summary", ""),
        "viral_angles": analyst_result.get("viral_angles", []),
        "content_hooks": analyst_result.get("content_hooks", []),
        "positioning": analyst_result.get("positioning", {}),
        "audience_takeaways": analyst_result.get("audience_takeaways", []),
    }

    length_guide = {
        "short": "Keep copy tight. Reels: 30s. LinkedIn: 150-200 words. Newsletter: 250 words. Ads: 60-90 chars primary text.",
        "medium": "Standard length. Reels: 45-60s. LinkedIn: 300-400 words. Newsletter: 400-500 words. Ads: 90-125 chars primary text.",
        "long": "Detailed. Reels: 60-90s. LinkedIn: 500-700 words. Newsletter: 600-800 words. Ads: 125-150 chars primary text.",
    }

    formats_list = ", ".join(formats) if formats else "Reel, Carousel, LinkedIn, Newsletter, Ads"

    output_lang_note = ""
    if language == "ES":
        output_lang_note = "Write ALL content in Spanish (ES). Use natural, conversational Spanish appropriate for the platform."
    elif language == "EN":
        output_lang_note = "Write ALL content in English (EN)."
    else:
        output_lang_note = "Write content primarily in Spanish (ES). Add English versions for Ads where noted."

    return f"""\
CONTENT BRIEF
=============
Topic: {topic}
Formats to produce: {formats_list}
Tone: {tone}
Language: {language}
Length: {length} — {length_guide.get(length, '')}
Objective: {objective}

LANGUAGE INSTRUCTION: {output_lang_note}

RESEARCH INTELLIGENCE:
{json.dumps(research_summary, ensure_ascii=False, indent=2)}

STRATEGY INTELLIGENCE:
{json.dumps(insights_summary, ensure_ascii=False, indent=2)}

YOUR TASK:
Produce ready-to-publish content for ONLY these formats: {formats_list}

TONE GUIDE for "{tone}":
- irreverent/meme: Casual, witty, self-aware, uses humor and cultural references, speaks to the audience as equals
- educational: Clear, structured, valuable, teaches something specific, uses examples and data
- professional: Authoritative, polished, data-driven, thought leadership voice
- sales: Benefit-focused, urgency, social proof, clear offer, direct CTA

For ADS specifically:
- Cold: Pain-point or curiosity hook, no assumed awareness
- Warm: Benefit-focused, they know the space
- Hot: Urgency/offer-focused, they know you, overcome objections

Respond with ONLY the JSON object containing ONLY the requested formats as keys."""
