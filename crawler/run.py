from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
USER_AGENT = "DemoPerksBot/0.6 (+https://github.com/robertstyler71/demoperks)"
TIMEOUT = 20


BLOCKED_DOMAINS = {
    "facebook.com",
    "www.facebook.com",
    "linkedin.com",
    "www.linkedin.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "www.youtube.com",
    "demoloot.com",
    "www.demoloot.com",
    "giftogram.com",
    "www.giftogram.com",
    "visa.com",
    "www.visa.com",
    "cnbc.com",
    "www.cnbc.com",
    "groups.google.com",
    "amazon.com",
    "www.amazon.com",
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "giftcards.com",
    "www.giftcards.com",
    "alldigitalrewards.com",
    "www.alldigitalrewards.com",
    "tangocard.com",
    "www.tangocard.com",
    "yiftee.com",
    "www.yiftee.com",
    "ticketor.com",
    "www.ticketor.com",
    "wp-giftcard.com",
    "www.wp-giftcard.com",
    "getscratch.com",
    "www.getscratch.com",
}


BAD_URL_PARTS = (
    "/blog/",
    "/blogs/",
    "/news/",
    "/article/",
    "/articles/",
    "/best-",
    "alternatives",
    "comparison",
    "reviews",
    "roundup",
    "gift-card-software",
    "gift-card-api",
    "gift-card-platform",
    "code-generator",
    "gift-card-apps",
    "gift-card-companies",
    "terms-and-conditions",
    "/terms/",
    "/gift-card/visa",
    "/prepaid-cards",
    "/card-finder",
    "/refer-and-earn",
)


POSITIVE_URL_PARTS = (
    "/offer",
    "/offers",
    "/promo",
    "/promotion",
    "/campaign",
    "/demo",
    "/request-demo",
    "/book-demo",
    "/ac-offers",
    "/paid-demo",
    "/incentivized-demo",
)


BAD_TITLE_PATTERNS = (
    r"terms\s*(?:&|and)\s*conditions",
    r"buy\s+(?:and\s+send\s+)?(?:prepaid\s+)?gift cards",
    r"gift card platform",
    r"gift card software",
    r"gift card code generator",
    r"best gift card",
    r"gift card apps",
    r"gift card companies",
    r"gift card alternatives",
    r"gift card integration",
    r"gift card api",
    r"amazon gift card balance",
    r"visa gift card balance",
    r"virtual account gift card",
    r"buy e-?gift cards",
    r"prepaid visa",
    r"restricted use card",
    r"controlled spending",
    r"gift card payments platform",
    r"request a demo\s*\|\s*tango",
    r"demo\s*-\s*gift card",
)


DEMO_PATTERNS = (
    r"book\s+(?:a|your|the)?\s*(?:live\s+)?demo",
    r"schedule\s+(?:a|your|the)?\s*(?:live\s+)?demo",
    r"request\s+(?:a|your|the)?\s*(?:live\s+)?demo",
    r"take\s+(?:a|the)?\s*(?:live\s+)?demo",
    r"attend\s+(?:a|the|your)?\s*(?:live\s+)?demo",
    r"complete\s+(?:a|the|your)?\s*(?:live\s+)?demo",
    r"(?:30|45|60)[ -]?(?:minute|min)\s+(?:live\s+)?demo",
    r"product demonstration",
    r"software demonstration",
    r"live demonstration",
    r"meet with (?:our|a) (?:sales|product) team",
    r"once (?:an|the|your) appointment is completed",
    r"after (?:an|the|your) appointment is completed",
    r"complete (?:an|the|your) appointment",
)


REWARD_PATTERNS = (
    r"(?:get|receive|earn|claim|qualify for|be sent)\s+"
    r"(?:up to\s+)?(?:a\s+)?\$?\s?\d{2,4}(?:\.\d{1,2})?\s*"
    r"(?:amazon|visa|mastercard|digital|e-?gift|gift)?\s*"
    r"(?:gift\s+)?card.{0,180}(?:demo|demonstration|appointment)",

    r"gift card.{0,100}in exchange for.{0,80}"
    r"(?:demo|demonstration|appointment)",

    r"(?:demo|demonstration|appointment).{0,180}"
    r"(?:receive|get|earn|claim|be sent|we(?:'|’)ll send|we will send).{0,100}"
    r"(?:up to\s+)?(?:a\s+)?\$?\s?\d{2,4}(?:\.\d{1,2})?.{0,50}"
    r"(?:gift card|prepaid card|cash reward)",

    r"(?:book|schedule|request|take|attend|complete).{0,60}"
    r"(?:demo|demonstration|appointment).{0,180}"
    r"(?:receive|get|earn|claim|be sent|we(?:'|’)ll send|we will send).{0,100}"
    r"(?:gift card|prepaid card|cash reward)",

    r"(?:receive|get|earn|claim|qualify for|be sent|we(?:'|’)ll send|we will send).{0,120}"
    r"(?:up to\s+)?(?:a\s+)?\$?\s?\d{2,4}(?:\.\d{1,2})?.{0,60}"
    r"(?:gift card|prepaid card|cash reward)",

    r"(?:receive|get|earn|claim|qualify for|be sent|we(?:'|’)ll send|we will send).{0,120}"
    r"(?:amazon|visa|mastercard|digital|e-?gift|gift) (?:gift )?card",

    r"(?:amazon|visa|mastercard|digital|e-?gift|gift) (?:gift )?card.{0,120}"
    r"(?:after|for|when|upon|following|complete|attend|exchange)",

    r"\$\s?\d{2,4}(?:\.\d{1,2})?.{0,100}"
    r"(?:gift card|prepaid card|cash reward)",

    r"(?:gift card|prepaid card|cash reward).{0,100}"
    r"\$\s?\d{2,4}(?:\.\d{1,2})?",
)


CATEGORY_RULES = (
    (
        "HR & People Operations",
        (
            "recruiting",
            "talent acquisition",
            " hr ",
            "people operations",
            "hiring",
            "candidate assessment",
            "child care management",
            "childcare management",
            "employee management",
            "workforce management",
        ),
    ),
    (
        "Security & Compliance",
        (
            "security",
            "access control",
            "surveillance",
            "compliance",
            "cybersecurity",
            "workplace security",
            "threat detection",
            "network security",
        ),
    ),
    (
        "Finance & Accounting",
        (
            "accounts payable",
            "accounts receivable",
            "accounting firm",
            "wealth management",
            "expense management",
            "spend management",
            "finance",
            "payments",
            "billing",
            "payment platform",
            "insurance payments",
        ),
    ),
    (
        "Ecommerce & Customer Experience",
        (
            "ecommerce",
            "e-commerce",
            "returns",
            "claims",
            "checkout",
            "order protection",
            "customer experience",
        ),
    ),
    (
        "Marketing & Growth",
        (
            "marketing",
            "conversion",
            "campaign",
            "advertising",
            "growth",
            "lead generation",
        ),
    ),
    (
        "Sales & CRM",
        (
            "sales",
            "crm",
            "revenue operations",
            "revops",
            "customer relationship management",
        ),
    ),
    (
        "Engineering & DevOps",
        (
            "developer",
            "devops",
            "engineering",
            "cloud infrastructure",
            "observability",
        ),
    ),
    (
        "Data & Analytics",
        (
            "analytics",
            "business intelligence",
            "data platform",
            "data warehouse",
        ),
    ),
)


BRAND_OVERRIDES = {
    "hauntpay.com": "HauntPay",
    "www.hauntpay.com": "HauntPay",
    "reachfirst.com": "Reach First",
    "www.reachfirst.com": "Reach First",
    "tributetech.com": "Tribute Technology",
    "www.tributetech.com": "Tribute Technology",
    "info.jazzhr.com": "JazzHR",
    "jazzhr.com": "JazzHR",
    "www.jazzhr.com": "JazzHR",
    "procaresoftware.com": "Procare",
    "www.procaresoftware.com": "Procare",
    "bill.com": "BILL",
    "www.bill.com": "BILL",
    "pages.bill.com": "BILL",
    "taxdome.unstack.website": "TaxDome",
    "blackpointcyber.com": "Blackpoint Cyber",
    "www.blackpointcyber.com": "Blackpoint Cyber",
    "epaypolicy.com": "ePayPolicy",
    "www.epaypolicy.com": "ePayPolicy",
    "crave.cards": "Crave",
    "rise.ai": "Rise",
    "www.rise.ai": "Rise",
    "get.nectarhr.com": "Nectar",
    "trytoolbox.com": "Toolbox",
    "www.trytoolbox.com": "Toolbox",
    "gratiflow.com": "Gratiflow",
    "www.gratiflow.com": "Gratiflow",
    "go.demandforce.com": "Demandforce",
    "demandforce.com": "Demandforce",
    "www.demandforce.com": "Demandforce",
    "shipinsure.io": "ShipInsure",
    "www.shipinsure.io": "ShipInsure",
    "glider.ai": "Glider AI",
    "www.glider.ai": "Glider AI",
    "rightsystems.com": "Right! Systems",
    "www.rightsystems.com": "Right! Systems",
}


@dataclass
class Candidate:
    discovered_url: str
    source_domain: str
    search_query: str
    page_title: str | None
    company_name: str | None
    offer_title: str | None
    reward_amount: float | None
    reward_type: str | None
    category: str | None
    extracted_text: str
    eligibility_details: str | None
    geographic_restrictions: str | None
    expiration_text: str | None
    confidence_score: int
    processing_status: str
    rejection_reason: str | None


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}"
        )

    return value


def supabase_headers(
    service_key: str,
    prefer: str | None = None,
) -> dict[str, str]:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }

    if prefer:
        headers["Prefer"] = prefer

    return headers


def create_run(
    base_url: str,
    service_key: str,
) -> str:
    response = requests.post(
        f"{base_url}/rest/v1/crawler_runs",
        headers=supabase_headers(
            service_key,
            "return=representation",
        ),
        json={
            "run_type": "discovery",
            "status": "running",
        },
        timeout=TIMEOUT,
    )

    response.raise_for_status()
    return response.json()[0]["id"]


def finish_run(
    base_url: str,
    service_key: str,
    run_id: str,
    stats: dict,
    status: str,
    error: str | None = None,
) -> None:
    payload = {
        **stats,
        "status": status,
        "completed_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "error_details": error,
    }

    response = requests.patch(
        f"{base_url}/rest/v1/crawler_runs?id=eq.{run_id}",
        headers=supabase_headers(
            service_key,
            "return=minimal",
        ),
        json=payload,
        timeout=TIMEOUT,
    )

    response.raise_for_status()


def brave_search(
    api_key: str,
    query: str,
    count: int = 10,
) -> list[dict]:
    response = requests.get(
        BRAVE_ENDPOINT,
        headers={
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
        },
        params={
            "q": query,
            "count": count,
            "safesearch": "strict",
            "search_lang": "en",
            "country": "us",
        },
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    return response.json().get(
        "web",
        {},
    ).get(
        "results",
        [],
    )


def clean_page_text(
    html: str,
) -> tuple[str, str | None]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    title = (
        soup.title.get_text(
            " ",
            strip=True,
        )
        if soup.title
        else None
    )

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "footer",
        ]
    ):
        tag.decompose()

    text = re.sub(
        r"\s+",
        " ",
        soup.get_text(
            " ",
            strip=True,
        ),
    )

    return text[:40000], title


def fetch_page(
    url: str,
) -> tuple[str, str | None, str]:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    response.raise_for_status()

    content_type = response.headers.get(
        "content-type",
        "",
    )

    if "text/html" not in content_type:
        raise ValueError(
            "Not an HTML page"
        )

    text, title = clean_page_text(
        response.text
    )

    return text, title, response.url


def domain_to_brand(domain: str) -> str:
    normalized = domain.lower().strip()

    if normalized in BRAND_OVERRIDES:
        return BRAND_OVERRIDES[normalized]

    parts = normalized.removeprefix("www.").split(".")

    ignored_subdomains = {
        "info",
        "go",
        "get",
        "pages",
        "lp",
        "try",
        "app",
        "demo",
        "offers",
    }

    if len(parts) >= 3 and parts[0] in ignored_subdomains:
        brand_part = parts[1]
    else:
        brand_part = parts[0]

    return brand_part.replace("-", " ").strip().title()


def infer_company(
    title: str | None,
    domain: str,
) -> str:
    normalized_domain = domain.lower().strip()

    if normalized_domain in BRAND_OVERRIDES:
        return BRAND_OVERRIDES[normalized_domain]

    domain_brand = domain_to_brand(
        normalized_domain
    )

    if not title:
        return domain_brand

    title_parts = [
        part.strip()
        for part in re.split(
            r"[|–—]",
            title,
        )
        if part.strip()
    ]

    blocked_title_phrases = (
        "book a demo",
        "request a demo",
        "schedule a demo",
        "take a demo",
        "attend a demo",
        "complete a demo",
        "get paid",
        "gift card",
        "receive a",
        "receive an",
        "leader in",
        "see ",
        "demo request",
        "paid demo",
        "incentivized demo",
        "get a $",
        "get an amazon",
    )

    for part in reversed(title_parts):
        lower_part = part.lower()

        if any(
            phrase in lower_part
            for phrase in blocked_title_phrases
        ):
            continue

        if re.fullmatch(
            r"[A-Za-z0-9!&.' -]{2,45}",
            part,
        ):
            return part

    return domain_brand


def first_match(
    patterns: tuple[str, ...],
    text: str,
) -> re.Match | None:
    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.I | re.S,
        )

        if match:
            return match

    return None


def match_positions(
    patterns: tuple[str, ...],
    text: str,
) -> list[int]:
    positions: list[int] = []

    for pattern in patterns:
        positions.extend(
            match.start()
            for match in re.finditer(
                pattern,
                text,
                re.I | re.S,
            )
        )

    return positions


def terms_are_close(
    text: str,
    max_distance: int = 1600,
) -> bool:
    demo_positions = match_positions(
        DEMO_PATTERNS,
        text,
    )

    reward_positions = match_positions(
        REWARD_PATTERNS,
        text,
    )

    return any(
        abs(demo - reward) <= max_distance
        for demo in demo_positions
        for reward in reward_positions
    )


def extract_amount(
    text: str,
) -> float | None:
    contextual = re.search(
        r"(?:up to\s+)?\$\s?(\d{2,4}(?:\.\d{1,2})?).{0,120}"
        r"(?:gift card|prepaid card|cash reward)|"
        r"(?:gift card|prepaid card|cash reward).{0,120}"
        r"(?:up to\s+)?\$\s?(\d{2,4}(?:\.\d{1,2})?)",
        text,
        re.I | re.S,
    )

    if not contextual:
        return None

    raw = (
        contextual.group(1)
        or contextual.group(2)
    )

    return float(raw) if raw else None


def infer_reward_type(
    text: str,
) -> str | None:
    lower = text.lower()

    if (
        "visa" in lower
        and "mastercard" in lower
        and (
            "gift card" in lower
            or "prepaid card" in lower
        )
    ):
        return "Visa or Mastercard Gift Card"

    reward_map = {
        "Amazon Gift Card": (
            "amazon gift card",
            "amazon e-gift card",
            "amazon egift card",
        ),
        "Visa Prepaid Card": (
            "visa gift card",
            "visa prepaid card",
            "visa virtual card",
        ),
        "Mastercard Prepaid Card": (
            "mastercard gift card",
            "mastercard prepaid card",
        ),
        "Digital Gift Card": (
            "digital gift card",
            "e-gift card",
            "egift card",
        ),
        "Gift Card of Choice": (
            "gift card of your choice",
            "gift card of choice",
        ),
        "Gift Card": (
            "gift card",
        ),
    }

    for label, patterns in reward_map.items():
        if any(
            pattern in lower
            for pattern in patterns
        ):
            return label

    return None


def infer_category(
    text: str,
) -> str | None:
    lower = f" {text.lower()} "

    category_scores: dict[str, int] = {}

    for category, keywords in CATEGORY_RULES:
        score = sum(
            1
            for keyword in keywords
            if keyword in lower
        )

        if score:
            category_scores[category] = score

    if not category_scores:
        return None

    return max(
        category_scores,
        key=category_scores.get,
    )


def extract_context(
    text: str,
    terms: tuple[str, ...],
    before: int = 160,
    after: int = 360,
) -> str | None:
    for term in terms:
        match = re.search(
            term,
            text,
            re.I,
        )

        if match:
            start = max(
                0,
                match.start() - before,
            )

            end = min(
                len(text),
                match.end() + after,
            )

            return text[start:end].strip()

    return None


def contains_expired_year(
    title: str,
    url: str,
) -> bool:
    current_year = datetime.now(
        timezone.utc
    ).year

    years_found = [
        int(year)
        for year in re.findall(
            r"\b20\d{2}\b",
            f"{title} {url}",
        )
    ]

    return bool(
        years_found
        and max(years_found) < current_year
    )


def extract_candidate(
    url: str,
    query: str,
    snippet: str = "",
) -> Candidate:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    normalized_url = url.lower()

    if domain in BLOCKED_DOMAINS:
        raise ValueError(
            "Blocked marketplace, directory, social, discussion, media, or gift-card service domain"
        )

    if any(
        part in normalized_url
        for part in BAD_URL_PARTS
    ):
        raise ValueError(
            "Likely editorial, terms, consumer, or gift-card software page"
        )

    text, title, final_url = fetch_page(
        url
    )

    final_domain = urlparse(
        final_url
    ).netloc.lower()

    if final_domain in BLOCKED_DOMAINS:
        raise ValueError(
            "Redirected to a blocked domain"
        )

    title_text = title or ""

    if any(
        re.search(
            pattern,
            title_text,
            re.I,
        )
        for pattern in BAD_TITLE_PATTERNS
    ):
        raise ValueError(
            "Title indicates a terms page, gift-card seller, or editorial page"
        )

    if contains_expired_year(
        title_text,
        final_url,
    ):
        raise ValueError(
            "Page appears to be an expired campaign from a previous year"
        )

    haystack = (
        f"{title_text} {snippet} {text}"
    )

    demo_match = first_match(
        DEMO_PATTERNS,
        haystack,
    )

    reward_match = first_match(
        REWARD_PATTERNS,
        haystack,
    )

    close_match = bool(
        demo_match
        and reward_match
        and terms_are_close(
            haystack
        )
    )

    amount = extract_amount(
        haystack
    )

    reward_type = infer_reward_type(
        haystack
    )

    category = infer_category(
        haystack
    )

    variable_reward = bool(
        re.search(
            r"\bup to\s+\$?\s?\d{2,4}",
            haystack,
            re.I,
        )
    )

    completion_language = bool(
        re.search(
            r"(?:after|once|upon|following).{0,80}"
            r"(?:demo|demonstration|appointment).{0,60}"
            r"(?:complete|completed)|"
            r"(?:complete|completed).{0,60}"
            r"(?:demo|demonstration|appointment)",
            haystack,
            re.I | re.S,
        )
    )

    positive_url = any(
        part in final_url.lower()
        for part in POSITIVE_URL_PARTS
    )

    qualification_language = bool(
        re.search(
            r"\b(?:qualified|eligible|eligibility|"
            r"decision.?maker|job title|company size|"
            r"employees|work email|terms apply|"
            r"participants|leader)\b",
            haystack,
            re.I,
        )
    )

    confidence = 0
    confidence += 25 if demo_match else 0
    confidence += 25 if reward_match else 0
    confidence += 20 if close_match else 0
    confidence += 10 if amount else 0
    confidence += 5 if reward_type else 0
    confidence += 5 if qualification_language else 0
    confidence += 5 if positive_url else 0
    confidence += 5 if completion_language else 0

    confidence = min(
        confidence,
        100,
    )

    if not demo_match or not reward_match:
        status = "rejected"
        rejection_reason = (
            "Did not clearly contain both a demo action "
            "and an incentive offer."
        )

    elif not close_match:
        status = "rejected"
        rejection_reason = (
            "Demo and gift-card language were not close "
            "enough to indicate the same promotion."
        )

    elif confidence >= 85:
        status = "approved"
        rejection_reason = None

    elif confidence >= 70:
        status = "needs_review"
        rejection_reason = None

    else:
        status = "rejected"
        rejection_reason = (
            "Offer details were incomplete or ambiguous."
        )

    eligibility = extract_context(
        text,
        (
            r"\bqualified\b",
            r"\beligible\b",
            r"\beligibility\b",
            r"\bdecision.?maker\b",
            r"\bjob title\b",
            r"\bcompany size\b",
            r"\bnumber of employees\b",
            r"\bwork email\b",
            r"\bHR or TA leader\b",
            r"\baccounting firm\b",
            r"\bwealth management firm\b",
            r"\bbusiness owner\b",
            r"\bnew customers only\b",
        ),
    )

    geography = extract_context(
        text,
        (
            r"\bunited states\b",
            r"\bu\.s\.\b",
            r"\bcanada\b",
            r"\bunited kingdom\b",
            r"\bresidents only\b",
        ),
        before=100,
        after=180,
    )

    expiration = extract_context(
        text,
        (
            r"\bexpires?\b",
            r"\bvalid (?:until|through)\b",
            r"\boffer ends\b",
            r"\bpromotion ends\b",
        ),
        before=100,
        after=200,
    )

    qualifier = (
        "Variable reward: up to stated amount. "
        if variable_reward
        else ""
    )

    extracted_text = (
        f"{qualifier}{text[:11900]}"
    )

    return Candidate(
        discovered_url=final_url,
        source_domain=final_domain,
        search_query=query,
        page_title=title,
        company_name=infer_company(
            title,
            final_domain,
        ),
        offer_title=(
            title
            or "Software demo reward offer"
        ),
        reward_amount=amount,
        reward_type=reward_type,
        category=category,
        extracted_text=extracted_text,
        eligibility_details=eligibility,
        geographic_restrictions=geography,
        expiration_text=expiration,
        confidence_score=confidence,
        processing_status=status,
        rejection_reason=rejection_reason,
    )


def upsert_candidate(
    base_url: str,
    service_key: str,
    candidate: Candidate,
) -> None:
    response = requests.post(
        (
            f"{base_url}/rest/v1/offer_candidates"
            "?on_conflict=discovered_url"
        ),
        headers=supabase_headers(
            service_key,
            "resolution=merge-duplicates,return=minimal",
        ),
        json=asdict(
            candidate
        ),
        timeout=TIMEOUT,
    )

    response.raise_for_status()


def main() -> int:
    supabase_url = required_env(
        "SUPABASE_URL"
    ).rstrip("/")

    service_key = required_env(
        "SUPABASE_SERVICE_ROLE_KEY"
    )

    brave_key = required_env(
        "BRAVE_SEARCH_API_KEY"
    )

    query_path = os.path.join(
        os.path.dirname(__file__),
        "search_queries.txt",
    )

    with open(
        query_path,
        encoding="utf-8",
    ) as query_file:
        queries = [
            line.strip()
            for line in query_file
            if line.strip()
            and not line.startswith("#")
        ]

    stats = {
        "searches_performed": 0,
        "results_found": 0,
        "candidates_created": 0,
        "offers_published": 0,
        "offers_updated": 0,
        "offers_expired": 0,
        "errors_count": 0,
    }

    run_id = create_run(
        supabase_url,
        service_key,
    )

    seen: set[str] = set()

    try:
        for query in queries:
            results = brave_search(
                brave_key,
                query,
                count=10,
            )

            stats["searches_performed"] += 1
            stats["results_found"] += len(
                results
            )

            for result in results:
                url = result.get(
                    "url",
                    "",
                ).strip()

                if not url or url in seen:
                    continue

                seen.add(
                    url
                )

                try:
                    candidate = extract_candidate(
                        url,
                        query,
                        result.get(
                            "description",
                            "",
                        ),
                    )

                    upsert_candidate(
                        supabase_url,
                        service_key,
                        candidate,
                    )

                    stats["candidates_created"] += 1

                    print(
                        f"Saved "
                        f"{candidate.processing_status} "
                        f"candidate "
                        f"({candidate.confidence_score}): "
                        f"{candidate.company_name} - "
                        f"{candidate.discovered_url}"
                    )

                except ValueError as exc:
                    print(
                        f"Filtered {url}: {exc}"
                    )

                except Exception as exc:
                    stats["errors_count"] += 1

                    print(
                        f"Skipping {url}: {exc}",
                        file=sys.stderr,
                    )

        status = (
            "completed_with_errors"
            if stats["errors_count"]
            else "completed"
        )

        finish_run(
            supabase_url,
            service_key,
            run_id,
            stats,
            status,
        )

        print(
            json.dumps(
                stats,
                indent=2,
            )
        )

        return 0

    except Exception as exc:
        stats["errors_count"] += 1

        finish_run(
            supabase_url,
            service_key,
            run_id,
            stats,
            "failed",
            str(exc),
        )

        raise


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
