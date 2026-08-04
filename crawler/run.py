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
    "/referral-program/",
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
    r"referral program",
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




def get_search_config() -> tuple[str, str, int, int]:
    search_mode = os.getenv(
        "SEARCH_MODE",
        "daily",
    ).strip().lower()

    if search_mode not in {"daily", "deep"}:
        print(
            f"Unknown SEARCH_MODE '{search_mode}'. "
            "Falling back to daily mode.",
            file=sys.stderr,
        )
        search_mode = "daily"

    if search_mode == "deep":
        query_filename = "search_queries_deep.txt"
        pages = 3
        count = 20
    else:
        query_filename = "search_queries_daily.txt"
        pages = 2
        count = 20

    query_path = os.path.join(
        os.path.dirname(__file__),
        query_filename,
    )

    return search_mode, query_path, pages, count


def load_queries(query_path: str) -> list[str]:
    if not os.path.exists(query_path):
        raise FileNotFoundError(
            f"Search query file not found: {query_path}"
        )

    with open(
        query_path,
        encoding="utf-8",
    ) as query_file:
        queries = [
            line.strip()
            for line in query_file
            if line.strip()
            and not line.lstrip().startswith("#")
        ]

    if not queries:
        raise RuntimeError(
            f"No search queries found in: {query_path}"
        )

    return queries


def build_search_snippet(result: dict) -> str:
    snippets: list[str] = []

    description = result.get("description", "")
    if description:
        snippets.append(str(description))

    extra_snippets = result.get("extra_snippets", [])
    if isinstance(extra_snippets, list):
        snippets.extend(
            str(item)
            for item in extra_snippets
            if item
        )

    return " ".join(snippets)


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
    pages: int = 2,
    count: int = 20,
) -> tuple[list[dict], int]:
    all_results: list[dict] = []
    seen_urls: set[str] = set()
    requests_performed = 0

    for offset in range(pages):
        response = requests.get(
            BRAVE_ENDPOINT,
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
            params={
                "q": query,
                "count": count,
                "offset": offset,
                "safesearch": "strict",
                "search_lang": "en",
                "country": "us",
                "extra_snippets": True,
            },
            timeout=TIMEOUT,
        )

        requests_performed += 1
        response.raise_for_status()
        data = response.json()

        results = data.get(
            "web",
            {},
        ).get(
            "results",
            [],
        )

        for result in results:
            url = result.get(
                "url",
                "",
            ).strip()

            if not url or url in seen_urls:
                continue

            seen_urls.add(url)
            all_results.append(result)

        more_results = data.get(
            "query",
            {},
        ).get(
            "more_results_available",
            False,
        )

        if not more_results:
            break

    return all_results, requests_performed


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



EDITORIAL_TITLE_PATTERNS = (
    r"\\bhow to\\b",
    r"\\bcomplete guide\\b",
    r"\\bguide to\\b",
    r"\\bplaybook\\b",
    r"\\bblog\\b",
    r"\\barticle\\b",
    r"\\bwebinar\\b",
    r"\\bebook\\b",
    r"\\bwhitepaper\\b",
    r"\\breport\\b",
    r"\\btemplate\\b",
    r"\\bbest \\d+\\b",
    r"\\btop \\d+\\b",
)

CONTEST_PATTERNS = (
    r"\\benter(?:ed)? to win\\b",
    r"\\bchance to win\\b",
    r"\\bdrawing\\b",
    r"\\bsweepstakes\\b",
    r"\\braffle\\b",
    r"\\bone of \\d+ winners?\\b",
    r"\\bselected winners?\\b",
)

EXPLICIT_OFFER_PATTERNS = (
    r"(?:book|schedule|request|attend|take|complete).{0,90}(?:demo|demonstration|appointment).{0,180}(?:receive|get|earn|claim|be sent|we(?:'|’)ll send|we will send).{0,120}(?:\\$\\s?\\d{2,4}(?:\\.\\d{1,2})?|amazon|visa|mastercard|gift card|prepaid card)",
    r"(?:receive|get|earn|claim|be sent|we(?:'|’)ll send|we will send).{0,120}(?:\\$\\s?\\d{2,4}(?:\\.\\d{1,2})?|amazon|visa|mastercard|gift card|prepaid card).{0,180}(?:after|upon|following|when|for).{0,100}(?:demo|demonstration|appointment)",
)

DATE_PATTERNS = (
    r"(?:must be completed|must attend|complete(?:d)? by|attend(?:ed)? by|valid through|valid until|expires?|offer ends?|promotion ends?)\\s*(?:on\\s*)?([A-Za-z]+\\s+\\d{1,2},?\\s+20\\d{2})",
    r"(?:must be completed|must attend|complete(?:d)? by|attend(?:ed)? by|valid through|valid until|expires?|offer ends?|promotion ends?)\\s*(?:on\\s*)?(20\\d{2}-\\d{1,2}-\\d{1,2})",
)


def find_offer_window(text: str) -> str | None:
    for pattern in EXPLICIT_OFFER_PATTERNS:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            start = max(0, match.start() - 220)
            end = min(len(text), match.end() + 420)
            return re.sub(r"\\s+", " ", text[start:end]).strip()
    return None


def parse_expiration_date(text: str) -> datetime | None:
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text, re.I | re.S)
        if not match:
            continue
        raw = match.group(1).strip().replace(',', '')
        for fmt in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return None


def is_editorial_page(title: str, url: str) -> bool:
    combined = f"{title} {url}"
    return any(re.search(pattern, combined, re.I) for pattern in EDITORIAL_TITLE_PATTERNS)

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

    if any(part in normalized_url for part in BAD_URL_PARTS):
        raise ValueError(
            "Likely editorial, terms, consumer, or gift-card software page"
        )

    text, title, final_url = fetch_page(url)
    final_domain = urlparse(final_url).netloc.lower()

    if final_domain in BLOCKED_DOMAINS:
        raise ValueError("Redirected to a blocked domain")

    title_text = title or ""
    page_text = re.sub(r"\\s+", " ", f"{title_text} {text}").strip()

    if any(re.search(pattern, title_text, re.I) for pattern in BAD_TITLE_PATTERNS):
        raise ValueError(
            "Title indicates a terms page, gift-card seller, or editorial page"
        )

    if is_editorial_page(title_text, final_url):
        raise ValueError(
            "Editorial, educational, guide, playbook, or resource page rather than a live demo offer"
        )

    if any(re.search(pattern, page_text, re.I | re.S) for pattern in CONTEST_PATTERNS):
        raise ValueError(
            "Contest, drawing, sweepstakes, or chance-to-win promotion rather than a guaranteed reward"
        )

    if contains_expired_year(title_text, final_url):
        raise ValueError(
            "Page appears to be an expired campaign from a previous year"
        )

    expiration_date = parse_expiration_date(page_text)
    if expiration_date and expiration_date.date() < datetime.now(timezone.utc).date():
        raise ValueError(
            f"Offer expired on {expiration_date.date().isoformat()}"
        )

    offer_window = find_offer_window(page_text)
    if not offer_window:
        raise ValueError(
            "No explicit sentence connects completing a demo with receiving a reward"
        )

    demo_match = first_match(DEMO_PATTERNS, offer_window)
    reward_match = first_match(REWARD_PATTERNS, offer_window)
    close_match = bool(
        demo_match and reward_match and terms_are_close(offer_window, max_distance=650)
    )

    if not demo_match or not reward_match or not close_match:
        raise ValueError(
            "Demo and reward language do not describe the same explicit promotion"
        )

    amount = extract_amount(offer_window)
    reward_type = infer_reward_type(offer_window)

    if amount is None or amount < 10 or amount > 1000:
        raise ValueError(
            "A plausible reward amount was not found inside the actual offer wording"
        )

    category = infer_category(page_text)
    variable_reward = bool(
        re.search(r"\\bup to\\s+\\$?\\s?\\d{2,4}", offer_window, re.I)
    )
    completion_language = bool(
        re.search(
            r"(?:after|once|upon|following).{0,90}(?:demo|demonstration|appointment)|"
            r"(?:demo|demonstration|appointment).{0,90}(?:complete|completed|attend|attended)",
            offer_window,
            re.I | re.S,
        )
    )
    positive_url = any(part in final_url.lower() for part in POSITIVE_URL_PARTS)
    qualification_language = bool(
        re.search(
            r"\\b(?:qualified|eligible|eligibility|decision.?maker|job title|company size|employees|work email|terms apply|participants|leader|new customers?)\\b",
            page_text,
            re.I,
        )
    )

    confidence = 70
    confidence += 10 if amount else 0
    confidence += 5 if reward_type else 0
    confidence += 5 if qualification_language else 0
    confidence += 5 if positive_url else 0
    confidence += 5 if completion_language else 0
    confidence = min(confidence, 100)

    status = "approved" if confidence >= 90 else "needs_review"
    rejection_reason = None

    eligibility = extract_context(
        page_text,
        (
            r"\\bqualified\\b",
            r"\\beligible\\b",
            r"\\beligibility\\b",
            r"\\bdecision.?maker\\b",
            r"\\bjob title\\b",
            r"\\bcompany size\\b",
            r"\\bnumber of employees\\b",
            r"\\bwork email\\b",
            r"\\bnew customers only\\b",
            r"\\bcurrent customers are not eligible\\b",
        ),
        before=120,
        after=260,
    )

    geography = extract_context(
        page_text,
        (
            r"\\bunited states\\b",
            r"\\bu\\.s\\.\\b",
            r"\\bcanada\\b",
            r"\\bunited kingdom\\b",
            r"\\bresidents only\\b",
        ),
        before=100,
        after=180,
    )

    expiration = extract_context(
        page_text,
        (
            r"\\bexpires?\\b",
            r"\\bvalid (?:until|through)\\b",
            r"\\boffer ends\\b",
            r"\\bpromotion ends\\b",
            r"\\bmust (?:attend|be completed) by\\b",
        ),
        before=100,
        after=220,
    )

    qualifier = "Variable reward: up to stated amount. " if variable_reward else ""
    extracted_text = f"{qualifier}{offer_window[:1800]}"

    return Candidate(
        discovered_url=final_url,
        source_domain=final_domain,
        search_query=query,
        page_title=title,
        company_name=infer_company(title, final_domain),
        offer_title=title or "Software demo reward offer",
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

    (
        search_mode,
        query_path,
        search_pages,
        results_per_page,
    ) = get_search_config()

    queries = load_queries(
        query_path
    )

    print(
        f"Search mode: {search_mode}"
    )
    print(
        f"Query file: {query_path}"
    )
    print(
        f"Queries loaded: {len(queries)}"
    )
    print(
        f"Search depth: {search_pages} page(s) "
        f"of up to {results_per_page} results"
    )

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
        for query_number, query in enumerate(
            queries,
            start=1,
        ):
            print(
                f"[{query_number}/{len(queries)}] "
                f"Searching: {query}"
            )

            try:
                results, requests_performed = brave_search(
                    brave_key,
                    query,
                    pages=search_pages,
                    count=results_per_page,
                )
            except Exception as exc:
                stats["errors_count"] += 1
                print(
                    f"Search failed for '{query}': {exc}",
                    file=sys.stderr,
                )
                continue

            stats["searches_performed"] += requests_performed
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
                        build_search_snippet(
                            result
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
