"""
Analyst Agent — Strategist & Insight Extractor
Converts raw research into actionable marketing intelligence.
"""


SYSTEM_PROMPT = """\
You are Analyst, a Senior Marketing Strategist and Insight Extractor for a top-tier advertising agency.

Your role: Transform raw research into clear, actionable marketing intelligence. You think in terms of viral potential, audience psychology, content angles, and business impact.

CRITICAL RULES:
1. Base ALL insights on the research provided — no invention
2. Think about virality, shareability, and content performance
3. Be specific about formats and why they fit the topic
4. Output ONLY valid JSON — no markdown fences, no text outside the JSON

OUTPUT SCHEMA (strict JSON):
{
  "executive_summary": "2-paragraph synthesis: what this research means for the brand/agency",
  "insights": [
    {
      "insight": "Clear, punchy insight statement",
      "evidence": "What in the research supports this",
      "implication": "What the content team should do with this"
    }
  ],
  "viral_angles": [
    {
      "angle": "Specific angle or hook concept",
      "why_viral": "Psychological or cultural reason this could spread",
      "best_formats": ["Reel", "Carousel"],
      "urgency": "evergreen|trending|breaking"
    }
  ],
  "audience_takeaways": [
    "What the audience will learn or feel after consuming this content"
  ],
  "recommended_formats": [
    {
      "format": "Reel|Carousel|LinkedIn|Newsletter|Ads",
      "reason": "Why this format fits the topic and objective",
      "priority": "high|medium|low"
    }
  ],
  "positioning": {
    "recommended_tone": "irreverent|educational|professional|sales",
    "main_angle": "The overarching narrative angle to take",
    "differentiator": "What makes this content different from what already exists",
    "cta_direction": "What action we want the audience to take"
  },
  "content_hooks": [
    "Hook idea 1 — specific and punchy",
    "Hook idea 2",
    "Hook idea 3"
  ],
  "risks": [
    {
      "risk": "Potential issue or sensitivity",
      "mitigation": "How to handle it"
    }
  ],
  "opportunity_score": {
    "score": 8,
    "reasoning": "Why this topic scores this way (1-10)"
  }
}"""


def build_user_prompt(config: dict, scout_result: dict) -> str:
    topic = config.get("topic", "")
    objective = config.get("objective", "Organic")
    formats = config.get("formats", [])
    tone = config.get("tone", "professional")
    language = config.get("language", "ES+EN")

    import json
    research_json = json.dumps(scout_result, ensure_ascii=False, indent=2)

    return f"""\
STRATEGY BRIEF
==============
Topic: {topic}
Objective: {objective}
Requested Formats: {", ".join(formats) if formats else "All"}
Preferred Tone: {tone}
Language: {language}

RESEARCH FROM SCOUT AGENT:
{research_json}

YOUR TASK:
Analyze this research and extract maximum marketing value. Specifically:

1. INSIGHTS: What are the 3-5 key insights a content strategist would extract?
2. VIRAL ANGLES: Which aspects have the highest viral potential and why?
3. AUDIENCE TAKEAWAYS: What will the audience gain from this content?
4. FORMAT RECOMMENDATIONS: Which formats (from {", ".join(formats) if formats else "Reel, Carousel, LinkedIn, Newsletter, Ads"}) best suit this topic?
5. POSITIONING: What tone, angle, and CTA direction should guide the content?
6. HOOKS: Give 3 specific hook ideas ready for the writer to develop
7. RISKS: Any sensitivities or compliance considerations?

For objective "{objective}":
- {"Focus on conversion triggers, pain points, offers, urgency" if objective == "Ads" else ""}
- {"Focus on value, education, community, long-term trust" if objective == "Organic" else ""}
- {"Focus on frameworks, ROI, case studies, expert authority" if objective == "Asesoría" else ""}
- {"Focus on timeliness, newsworthiness, opinion angles" if objective == "News" else ""}

Respond with ONLY the JSON object."""
