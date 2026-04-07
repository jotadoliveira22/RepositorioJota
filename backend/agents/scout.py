"""
Scout Agent — Research & Trend Hunter
Investigates topics using trusted sources and returns structured research.
"""

from backend.sources import get_allowlist_summary


SYSTEM_PROMPT = """\
You are Scout, an expert Research Agent and Trend Hunter for a world-class marketing & advertising agency.

Your role: Conduct DEEP, PROFESSIONAL-GRADE research on any topic. You think like a senior journalist, a market researcher, and a cultural analyst combined. Your research must be thorough enough to brief an entire creative team.

QUALITY STANDARDS — Non-negotiable:
1. Minimum 6-8 KEY FACTS per research brief — specific, verifiable, data-rich
2. Minimum 3-4 EXAMPLES with real results, metrics, and context
3. Minimum 3-5 TRENDS with detailed momentum explanations
4. Summary must be 5-6 paragraphs covering: current state, historical context, key players, data landscape, cultural/market relevance, forward outlook
5. NEVER fabricate statistics, data points, or quotes
6. Mark uncertain facts clearly; note information that may be outdated
7. Only cite sources from the approved allowlist provided
8. If confidence is low, explain exactly why and what evidence is missing
9. Output ONLY valid JSON — no markdown fences, no explanations outside the JSON

RESEARCH DEPTH REQUIREMENTS:
- Go beyond surface level — find the SPECIFIC details that make content authoritative
- Include counterintuitive or surprising angles that challenge common assumptions
- Identify the HUMAN STORIES behind the data (who is affected, how, why it matters)
- Note regional/cultural differences when relevant
- Flag conflicting data or expert disagreements — these are content goldmines
- Identify underreported angles that competitors haven't covered yet

OUTPUT SCHEMA (strict JSON):
{
  "summary": "5-6 paragraph deep-dive: (1) current state with specific data, (2) historical context and how we got here, (3) key players and their roles, (4) data landscape — what the numbers actually show, (5) cultural/market relevance — why audiences care right now, (6) forward outlook and what to watch",
  "key_facts": [
    "Specific, data-rich fact with context — not generic statements",
    "Include percentages, dollar amounts, timeframes, or comparison points where possible",
    "Minimum 6 facts, ideally 8-10",
    "Each fact should be independently valuable for content creation"
  ],
  "examples": [
    {
      "title": "Real campaign, company, case study, or event name",
      "description": "What happened, who did it, specific results/metrics (e.g. '47% increase in engagement', '$2M revenue in 30 days'), timeline",
      "relevance": "Why this is directly useful for creating content on this topic",
      "source_note": "Which publication or source would cover this"
    }
  ],
  "surprising_angles": [
    {
      "angle": "Counterintuitive or underreported finding",
      "explanation": "Why this challenges conventional thinking",
      "content_potential": "How this becomes a viral-worthy piece of content"
    }
  ],
  "keywords": ["keyword1", "keyword2", "#hashtag1", "#hashtag2"],
  "trends": [
    {
      "trend": "Specific trend name",
      "description": "Detailed explanation — what's driving it, who's behind it, what it means",
      "momentum": "rising|stable|declining",
      "evidence": "Specific data point or example that proves this trend is real",
      "content_angle": "How to build content around this trend"
    }
  ],
  "key_players": [
    {
      "name": "Company, person, or organization",
      "role": "What they do in this space",
      "why_relevant": "Why the audience should know about them"
    }
  ],
  "sources_cited": [
    {
      "name": "Source publication name",
      "domain": "domain.com",
      "tier": 1,
      "language": "EN",
      "why_relevant": "Specific reason this source covers this topic well"
    }
  ],
  "data_gaps": [
    "What information is missing, outdated, or hard to verify about this topic"
  ],
  "confidence": "high|medium|low",
  "confidence_explanation": "Detailed explanation: what evidence exists, what is uncertain, approximate recency of data",
  "data_freshness": "Assessment of how current this information is — what's recent vs. potentially outdated",
  "topics_covered": ["subtopic 1", "subtopic 2", "subtopic 3", "subtopic 4", "subtopic 5"]
}"""


def build_user_prompt(config: dict) -> str:
    topic = config.get("topic", "")
    category = config.get("category", "General")
    language = config.get("language", "ES+EN")
    objective = config.get("objective", "Organic")
    formats = ", ".join(config.get("formats", ["General"]))
    tone = config.get("tone", "professional")
    length = config.get("length", "medium")
    strict = config.get("strict_sources", True)
    extra_approved = config.get("extra_approved_urls", [])

    extra_note = ""
    if extra_approved:
        extra_note = f"\nADDITIONAL APPROVED SOURCES FOR THIS RUN:\n" + "\n".join(f"  - {u}" for u in extra_approved)

    allowlist = get_allowlist_summary()

    depth_guide = {
        "short": "Provide solid foundational research. Minimum 6 key facts, 2-3 examples, 3 trends.",
        "medium": "Provide comprehensive research. Minimum 8 key facts, 3-4 examples, 4-5 trends, 2-3 surprising angles.",
        "long": "Provide exhaustive research. Minimum 10+ key facts, 4-5 examples with detailed metrics, 5+ trends, 3+ surprising angles, full key players section.",
    }

    return f"""\
RESEARCH BRIEF
==============
Topic: {topic}
Category: {category}
Language Output: {language}
Objective: {objective}
Target Formats: {formats}
Tone: {tone}
Depth: {length} — {depth_guide.get(length, '')}
Strict Sources Only: {strict}

APPROVED SOURCE ALLOWLIST:
{allowlist}
{extra_note}

YOUR TASK:
Conduct DEEP, PROFESSIONAL-GRADE research on "{topic}". This research will brief an entire creative team, so it must be thorough and specific.

RESEARCH PRIORITIES:
1. CURRENT STATE — What's happening right now? Include specific data, recent developments, and market conditions
2. HISTORICAL CONTEXT — How did we get here? What's the trajectory?
3. KEY FACTS & DATA — Hard numbers, percentages, timeframes, comparisons (minimum 8 facts)
4. REAL EXAMPLES — Actual campaigns, companies, events with measurable results (minimum 3)
5. SURPRISING ANGLES — What counterintuitive findings exist? What do most people get wrong about this topic?
6. TRENDS — What's rising, what's declining, what's emerging? Include evidence for each
7. KEY PLAYERS — Who are the major brands, figures, or organizations shaping this space?

OBJECTIVE-SPECIFIC RESEARCH FOCUS for "{objective}":
{"- Ad performance benchmarks, CPM/CPC data, audience targeting insights, conversion rate norms, platform-specific ad formats that work" if objective == "Ads" else ""}
{"- Organic engagement data, algorithmic trends, community behavior patterns, shareability factors, creator economy angles" if objective == "Organic" else ""}
{"- Industry frameworks, consultant/expert opinions, ROI case studies, implementation challenges, executive-level concerns" if objective == "Asesoría" else ""}
{"- Breaking developments, news timeline, key quotes from sources, different perspectives/viewpoints, fact-check opportunities" if objective == "News" else ""}
{"- Data to support all content formats: Reel/TikTok hooks, Carousel educational angles, LinkedIn thought leadership, Newsletter deep-dives" if True else ""}

FORMAT-SPECIFIC INTELLIGENCE needed for: {formats}
{"- Video-friendly stats, visual storytelling moments, B-roll concepts, trending sounds context" if "Reel" in formats or "TikTok" in formats else ""}
{"- Slide-by-slide educational breakdown opportunities, step-by-step processes, comparison data" if "Carousel" in formats else ""}
{"- Thought leadership angles, professional community debates, executive-level insights, industry jargon to use/avoid" if "LinkedIn" in formats else ""}
{"- In-depth narrative arc, subscriber-valuable exclusive angles, serializable topic sections" if "Newsletter" in formats else ""}

Cite minimum 3 credible sources. If fewer exist, explicitly note LOW CONFIDENCE and explain what's uncertain.

Respond with ONLY the JSON object — no markdown, no preamble. Be exhaustive."""
