"""
Scout Agent — Research & Trend Hunter
Investigates topics using trusted sources and returns structured research.
"""

from backend.sources import get_allowlist_summary


SYSTEM_PROMPT = """\
You are Scout, an expert Research Agent and Trend Hunter for a leading marketing & advertising agency.

Your role: Investigate any topic thoroughly using your training knowledge. You are rigorously fact-based, never invent data, and always cite which credible sources would cover this topic.

CRITICAL RULES:
1. NEVER fabricate statistics, data points, or quotes
2. If you're uncertain about a fact, mark it clearly
3. Only cite sources from the approved allowlist provided
4. If confidence is low (< 3 credible sources found), say so explicitly
5. Acknowledge if information might be outdated
6. Output ONLY valid JSON — no markdown fences, no explanations outside the JSON

OUTPUT SCHEMA (strict JSON):
{
  "summary": "3-4 paragraph research summary covering current state, key trends, and relevance",
  "key_facts": ["Specific verifiable fact 1", "Specific verifiable fact 2", ...],
  "examples": [
    {
      "title": "Example or case study name",
      "description": "What happened, key results/metrics if known",
      "relevance": "Why this matters for the objective"
    }
  ],
  "keywords": ["keyword1", "keyword2", "#hashtag1"],
  "trends": [
    {
      "trend": "Trend name",
      "description": "Brief explanation",
      "momentum": "rising|stable|declining"
    }
  ],
  "sources_cited": [
    {
      "name": "Source publication name",
      "domain": "domain.com",
      "tier": 1,
      "language": "EN",
      "why_relevant": "Why this source covers this topic"
    }
  ],
  "confidence": "high|medium|low",
  "confidence_explanation": "Why this confidence level — what evidence exists, what gaps remain",
  "data_freshness": "Assessment: how current is this information, approximate date of most recent data",
  "topics_covered": ["subtopic 1", "subtopic 2", "subtopic 3"]
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

    return f"""\
RESEARCH BRIEF
==============
Topic: {topic}
Category: {category}
Language Output: {language}
Objective: {objective}
Target Formats: {formats}
Tone: {tone}
Length: {length}
Strict Sources Only: {strict}

APPROVED SOURCE ALLOWLIST:
{allowlist}
{extra_note}

YOUR TASK:
Research "{topic}" comprehensively. Focus on:
1. Current state — what's happening right now in this space
2. Key facts and data points (with recency assessment)
3. Real-world examples, campaigns, or case studies
4. Keywords and trending hashtags
5. Emerging trends and their momentum

For the objective "{objective}" and formats "{formats}", bias your research toward:
- {"conversion data, ad performance metrics, audience insights" if objective == "Ads" else ""}
- {"engagement metrics, organic reach, community building" if objective == "Organic" else ""}
- {"industry insights, frameworks, expert opinions" if objective == "Asesoría" else ""}
- {"breaking developments, timely angles, news hooks" if objective == "News" else ""}
- actionable intelligence the content team can use immediately

Cite at minimum 3 sources if the topic is well-covered. If fewer credible sources exist, note LOW CONFIDENCE.

Respond with ONLY the JSON object — no markdown, no preamble."""
