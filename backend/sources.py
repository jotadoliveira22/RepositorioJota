"""
Source allowlist and validation for the Agent Research Platform.
Only these trusted sources are accepted. Strict mode enforces this.
"""

# ---------------------------------------------------------------------------
# ALLOWLIST — Tier 1: Primary / Official sources
# ---------------------------------------------------------------------------
TIER_1_SOURCES = [
    # AI labs & primary docs
    {"name": "OpenAI Blog", "domain": "openai.com", "language": "EN", "category": "AI"},
    {"name": "Anthropic Blog", "domain": "anthropic.com", "language": "EN", "category": "AI"},
    {"name": "Google DeepMind", "domain": "deepmind.com", "language": "EN", "category": "AI"},
    {"name": "Google AI Blog", "domain": "ai.google", "language": "EN", "category": "AI"},
    {"name": "Meta AI", "domain": "ai.meta.com", "language": "EN", "category": "AI"},
    {"name": "Microsoft Research", "domain": "microsoft.com/research", "language": "EN", "category": "AI"},
    {"name": "arXiv", "domain": "arxiv.org", "language": "EN", "category": "Academic"},
    {"name": "NeurIPS", "domain": "nips.cc", "language": "EN", "category": "Academic"},
    {"name": "ICLR", "domain": "iclr.cc", "language": "EN", "category": "Academic"},
    {"name": "ICML", "domain": "icml.cc", "language": "EN", "category": "Academic"},
    # Advertising platforms (official)
    {"name": "Meta for Business", "domain": "business.meta.com", "language": "EN", "category": "Ads"},
    {"name": "Meta Ads Library", "domain": "facebook.com/ads/library", "language": "EN", "category": "Ads"},
    {"name": "TikTok for Business", "domain": "business.tiktok.com", "language": "EN", "category": "Ads"},
    {"name": "TikTok Creative Center", "domain": "ads.tiktok.com/business/creativecenter", "language": "EN", "category": "Ads"},
    {"name": "Google Ads", "domain": "ads.google.com", "language": "EN", "category": "Ads"},
    {"name": "Google Think", "domain": "thinkwithgoogle.com", "language": "EN", "category": "Marketing"},
    {"name": "LinkedIn Marketing Solutions", "domain": "business.linkedin.com", "language": "EN", "category": "Ads"},
]

# ---------------------------------------------------------------------------
# ALLOWLIST — Tier 2: Premium media (EN)
# ---------------------------------------------------------------------------
TIER_2_SOURCES_EN = [
    {"name": "The Verge", "domain": "theverge.com", "language": "EN", "category": "Tech"},
    {"name": "TechCrunch", "domain": "techcrunch.com", "language": "EN", "category": "Tech"},
    {"name": "Wired", "domain": "wired.com", "language": "EN", "category": "Tech"},
    {"name": "MIT Technology Review", "domain": "technologyreview.com", "language": "EN", "category": "Tech"},
    {"name": "Ars Technica", "domain": "arstechnica.com", "language": "EN", "category": "Tech"},
    {"name": "VentureBeat", "domain": "venturebeat.com", "language": "EN", "category": "Tech"},
    {"name": "Bloomberg", "domain": "bloomberg.com", "language": "EN", "category": "Business"},
    {"name": "Reuters", "domain": "reuters.com", "language": "EN", "category": "News"},
    {"name": "AP News", "domain": "apnews.com", "language": "EN", "category": "News"},
    {"name": "BBC", "domain": "bbc.com", "language": "EN", "category": "News"},
    {"name": "The Guardian", "domain": "theguardian.com", "language": "EN", "category": "News"},
    {"name": "Forbes", "domain": "forbes.com", "language": "EN", "category": "Business"},
    {"name": "Harvard Business Review", "domain": "hbr.org", "language": "EN", "category": "Business"},
    {"name": "Wall Street Journal", "domain": "wsj.com", "language": "EN", "category": "Business"},
    {"name": "Financial Times", "domain": "ft.com", "language": "EN", "category": "Business"},
]

# ---------------------------------------------------------------------------
# ALLOWLIST — Tier 2: Premium media (ES)
# ---------------------------------------------------------------------------
TIER_2_SOURCES_ES = [
    {"name": "El País", "domain": "elpais.com", "language": "ES", "category": "News"},
    {"name": "El Confidencial", "domain": "elconfidencial.com", "language": "ES", "category": "News"},
    {"name": "El Español", "domain": "elespanol.com", "language": "ES", "category": "News"},
    {"name": "Expansión", "domain": "expansion.com", "language": "ES", "category": "Business"},
    {"name": "Cinco Días", "domain": "cincodias.elpais.com", "language": "ES", "category": "Business"},
    {"name": "Xataka", "domain": "xataka.com", "language": "ES", "category": "Tech"},
    {"name": "Hipertextual", "domain": "hipertextual.com", "language": "ES", "category": "Tech"},
    {"name": "ADSLZone", "domain": "adslzone.net", "language": "ES", "category": "Tech"},
]

# ---------------------------------------------------------------------------
# ALLOWLIST — Tier 3: Industry / Marketing sources
# ---------------------------------------------------------------------------
TIER_3_SOURCES = [
    {"name": "Marketing Week", "domain": "marketingweek.com", "language": "EN", "category": "Marketing"},
    {"name": "HubSpot Blog", "domain": "blog.hubspot.com", "language": "EN", "category": "Marketing"},
    {"name": "Adweek", "domain": "adweek.com", "language": "EN", "category": "Marketing"},
    {"name": "AdAge", "domain": "adage.com", "language": "EN", "category": "Marketing"},
    {"name": "Search Engine Journal", "domain": "searchenginejournal.com", "language": "EN", "category": "Marketing"},
    {"name": "Hootsuite Blog", "domain": "blog.hootsuite.com", "language": "EN", "category": "Marketing"},
    {"name": "Social Media Today", "domain": "socialmediatoday.com", "language": "EN", "category": "Marketing"},
    {"name": "Content Marketing Institute", "domain": "contentmarketinginstitute.com", "language": "EN", "category": "Marketing"},
    {"name": "Marketing Directo", "domain": "marketingdirecto.com", "language": "ES", "category": "Marketing"},
    {"name": "IPMARK", "domain": "ipmark.com", "language": "ES", "category": "Marketing"},
    {"name": "Anuncios", "domain": "anuncios.com", "language": "ES", "category": "Marketing"},
    {"name": "Reason Why", "domain": "reasonwhy.es", "language": "ES", "category": "Marketing"},
    {"name": "Neil Patel Blog", "domain": "neilpatel.com/blog", "language": "EN", "category": "Marketing"},
    {"name": "Sprout Social", "domain": "sproutsocial.com/insights", "language": "EN", "category": "Marketing"},
]

# ---------------------------------------------------------------------------
# Combine all sources into a single allowlist
# ---------------------------------------------------------------------------
ALL_ALLOWED_SOURCES = TIER_1_SOURCES + TIER_2_SOURCES_EN + TIER_2_SOURCES_ES + TIER_3_SOURCES

# Build a lookup dict by domain for quick validation
ALLOWED_DOMAINS: dict[str, dict] = {}
for source in ALL_ALLOWED_SOURCES:
    domain = source["domain"].lower().strip("/")
    ALLOWED_DOMAINS[domain] = source

# ---------------------------------------------------------------------------
# CATEGORIES for the topic selector
# ---------------------------------------------------------------------------
RESEARCH_CATEGORIES = [
    {
        "id": "ai_news",
        "name": "AI News Radar",
        "description": "Noticias de IA relevantes y últimos lanzamientos",
        "subtopics": [
            "Últimos modelos de lenguaje (LLMs)",
            "Agentes de IA y automatización",
            "IA generativa para creación de contenido",
            "Regulación y ética en IA",
            "Aplicaciones de IA en empresas",
        ],
    },
    {
        "id": "viral_campaigns",
        "name": "Viral Campaigns Watch",
        "description": "Campañas de marketing virales y análisis de lo que funciona",
        "subtopics": [
            "Campañas virales en TikTok",
            "Tendencias en Instagram Reels",
            "Campañas UGC que explotaron",
            "Memes convertidos en marketing",
            "Campañas de influencers exitosas",
        ],
    },
    {
        "id": "ads_intelligence",
        "name": "Ads Intelligence",
        "description": "Estrategias y creatividades de publicidad digital",
        "subtopics": [
            "Mejores ads de Meta 2024-2025",
            "Performance marketing avanzado",
            "Creatividades que convierten en frío",
            "Google Ads estrategias",
            "TikTok Ads tendencias",
        ],
    },
    {
        "id": "digital_marketing",
        "name": "Digital Marketing Playbooks",
        "description": "Tácticas y herramientas de marketing digital",
        "subtopics": [
            "Email marketing avanzado",
            "SEO y contenido orgánico",
            "Social media strategy",
            "Content marketing B2B",
            "Automatización de marketing",
        ],
    },
    {
        "id": "marketing_strategy",
        "name": "Marketing Strategy & Fundamentals",
        "description": "Estrategia de marketing general y fundamentos",
        "subtopics": [
            "Branding y posicionamiento",
            "Customer journey mapping",
            "Pricing strategy",
            "Go-to-market strategy",
            "Marketing analytics y métricas",
        ],
    },
]


def validate_url(url: str) -> tuple[bool, str, dict | None]:
    """
    Validate a URL against the allowlist.
    Returns (is_valid, reason, source_info)
    """
    if not url:
        return False, "URL vacía", None

    url = url.strip().lower()
    # Remove protocol
    for prefix in ["https://", "http://", "www."]:
        if url.startswith(prefix):
            url = url[len(prefix):]

    # Try exact and partial domain matching
    for domain, source_info in ALLOWED_DOMAINS.items():
        if url.startswith(domain) or domain in url:
            return True, f"Fuente aprobada: {source_info['name']} (Tier {source_info.get('tier', '?')})", source_info

    return False, f"'{url}' no está en la lista blanca de fuentes aprobadas", None


def validate_urls(urls: list[str]) -> dict:
    """Validate a list of URLs and return categorized results."""
    approved = []
    rejected = []
    for url in urls:
        if not url.strip():
            continue
        is_valid, reason, info = validate_url(url)
        if is_valid:
            approved.append({"url": url, "reason": reason, "info": info})
        else:
            rejected.append({"url": url, "reason": reason})
    return {"approved": approved, "rejected": rejected}


def get_allowlist_summary() -> str:
    """Return a text summary of the allowlist for use in agent prompts."""
    lines = [
        "FUENTES TIER 1 (Primarias/Oficiales):",
        "  " + ", ".join(s["name"] for s in TIER_1_SOURCES),
        "",
        "FUENTES TIER 2 EN (Premium Media EN):",
        "  " + ", ".join(s["name"] for s in TIER_2_SOURCES_EN),
        "",
        "FUENTES TIER 2 ES (Premium Media ES):",
        "  " + ", ".join(s["name"] for s in TIER_2_SOURCES_ES),
        "",
        "FUENTES TIER 3 (Industria/Marketing):",
        "  " + ", ".join(s["name"] for s in TIER_3_SOURCES),
    ]
    return "\n".join(lines)
