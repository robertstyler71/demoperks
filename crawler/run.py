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
USER_AGENT = "DemoPerksBot/0.2 (+https://github.com/robertstyler71/demoperks)"
TIMEOUT = 20

BLOCKED_DOMAINS = {
    "facebook.com", "www.facebook.com", "linkedin.com", "www.linkedin.com",
    "x.com", "twitter.com", "youtube.com", "www.youtube.com",
}

# These pages are usually articles about gift-card software rather than an incentive offer.
BAD_URL_PARTS = (
    "/blog/", "/blogs/", "/news/", "/article/", "/articles/", "/resources/",
    "/best-", "alternatives", "comparison", "reviews", "gift-card-software",
    "gift-card-api", "gift-card-platform", "code-generator",
)

DEMO_PATTERNS = (
    r"book (?:a|your) demo",
    r"schedule (?:a|your) demo",
    r"request (?:a|your) demo",
    r"attend (?:a|the) demo",
    r"complete (?:a|the) demo",
    r"product demonstration",
    r"software demonstration",
    r"meet with (?:our|a) (?:sales|product) team",
)

REWARD_PATTERNS = (
    r"(?:receive|get|earn|claim|qualify for|be sent|we(?:'|’)ll send).{0,100}(?:amazon|visa|mastercard|digital|e-?gift|gift) (?:gift )?card",
    r"(?:amazon|visa|mastercard|digital|e-?gift|gift) (?:gift )?card.{0,100}(?:after|for|when|upon|following|complete|attend)",
    r"\$\s?\d{2,4}(?:\.\d{1,2})?.{0,80}(?:gift card|prepaid card|reward)",
)


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
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def supabase_headers(service_key: str, prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def create_run(base_url: str, service_key: str) -> str:
    response = requests.post(
        f"{base_url}/rest/v1/crawler_runs",
        headers=supabase_headers(service_key, "return=representation"),
        json={"run_type": "discovery", "status": "running"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()[0]["id"]


def finish_run(base_url: str, service_key: str, run_id: str, stats: dict, status: str, error: str | None = None) -> None:
    payload = {
        **stats,
        "status": status,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "error_details": error,
    }
    response = requests.patch(
        f"{base_url}/rest/v1/crawler_runs?id=eq.{run_id}",
        headers=supabase_headers(service_key, "return=minimal"),
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def brave_search(api_key: str, query: str, count: int = 10) -> list[dict]:
    response = requests.get(
        BRAVE_ENDPOINT,
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        params={
            "q": query,
            "count": count,
            "safesearch": "strict",
            "freshness": "py",
            "search_lang": "en",
            "country": "us",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("web", {}).get("results", [])


def clean_page_text(html: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return text[:30000], title


def fetch_page(url: str) -> tuple[str, str | None, str]:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        raise ValueError("Not an HTML page")
    text, title = clean_page_text(response.text)
    return text, title, response.url


def infer_company(title: str | None, domain: str) -> str:
    if title:
        parts = [p.strip() for p in re.split(r"[|–—]", title) if p.strip()]
        if len(parts) > 1 and 2 <= len(parts[-1]) <= 60:
            return parts[-1]
        if parts and 2 <= len(parts[0]) <= 60:
            return parts[0]
    return domain.removeprefix("www.").split(".")[0].replace("-", " ").title()


def first_match(patterns: tuple[str, ...], text: str) -> re.Match | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return match
    return None


def terms_are_close(text: str) -> bool:
    demo_positions = [m.start() for p in DEMO_PATTERNS for m in re.finditer(p, text, re.I)]
    reward_positions = [m.start() for p in REWARD_PATTERNS for m in re.finditer(p, text, re.I | re.S)]
    return any(abs(d - r) <= 900 for d in demo_positions for r in reward_positions)


def extract_amount(text: str) -> float | None:
    contextual = re.search(
        r"\$\s?(\d{2,4}(?:\.\d{1,2})?).{0,100}(?:gift card|prepaid card|reward)|"
        r"(?:gift card|prepaid card|reward).{0,100}\$\s?(\d{2,4}(?:\.\d{1,2})?)",
        text,
        re.I | re.S,
    )
    if not contextual:
        return None
    raw = contextual.group(1) or contextual.group(2)
    return float(raw) if raw else None


def extract_candidate(url: str, query: str, snippet: str = "") -> Candidate:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    normalized_url = url.lower()

    if domain in BLOCKED_DOMAINS:
        raise ValueError("Blocked social or video domain")
    if any(part in normalized_url for part in BAD_URL_PARTS):
        raise ValueError("Likely editorial or gift-card software page")

    text, title, final_url = fetch_page(url)
    haystack = f"{title or ''} {snippet} {text}"
    lower = haystack.lower()

    demo_match = first_match(DEMO_PATTERNS, haystack)
    reward_match = first_match(REWARD_PATTERNS, haystack)
    close_match = bool(demo_match and reward_match and terms_are_close(haystack))
    amount = extract_amount(haystack)

    reward_type = None
    reward_map = {
        "Amazon Gift Card": ("amazon gift card", "amazon e-gift card", "amazon egift card"),
        "Visa Prepaid Card": ("visa gift card", "visa prepaid card", "visa virtual card"),
        "Mastercard Prepaid Card": ("mastercard gift card", "mastercard prepaid card"),
        "Digital Gift Card": ("digital gift card", "e-gift card", "egift card"),
        "Gift Card": ("gift card",),
    }
    for label, patterns in reward_map.items():
        if any(pattern in lower for pattern in patterns):
            reward_type = label
            break

    confidence = 0
    confidence += 30 if demo_match else 0
    confidence += 30 if reward_match else 0
    confidence += 20 if close_match else 0
    confidence += 10 if amount else 0
    confidence += 5 if reward_type else 0
    confidence += 5 if any(word in lower for word in ("qualified", "eligible", "terms apply", "participants")) else 0

    if not demo_match or not reward_match:
        status = "rejected"
        rejection_reason = "Did not clearly contain both a demo action and an incentive offer."
    elif not close_match:
        status = "rejected"
        rejection_reason = "Demo and gift-card language were not close enough to indicate the same promotion."
    elif confidence >= 90:
        status = "approved"
        rejection_reason = None
    elif confidence >= 75:
        status = "needs_review"
        rejection_reason = None
    else:
        status = "rejected"
        rejection_reason = "Offer details were incomplete or ambiguous."

    eligibility_match = re.search(r"(.{0,140}(?:qualified|eligible|eligibility|decision.?maker|job title|company size).{0,260})", text, re.I)
    geography_match = re.search(r"(.{0,100}(?:united states|u\.s\.|canada|uk|united kingdom|residents only).{0,140})", text, re.I)
    expiration_match = re.search(r"(.{0,100}(?:expires?|valid (?:until|through)|offer ends|promotion ends).{0,160})", text, re.I)

    return Candidate(
        discovered_url=final_url,
        source_domain=urlparse(final_url).netloc.lower(),
        search_query=query,
        page_title=title,
        company_name=infer_company(title, domain),
        offer_title=title or "Software demo reward offer",
        reward_amount=amount,
        reward_type=reward_type,
        category=None,
        extracted_text=text[:12000],
        eligibility_details=eligibility_match.group(1).strip() if eligibility_match else None,
        geographic_restrictions=geography_match.group(1).strip() if geography_match else None,
        expiration_text=expiration_match.group(1).strip() if expiration_match else None,
        confidence_score=confidence,
        processing_status=status,
        rejection_reason=rejection_reason,
    )


def upsert_candidate(base_url: str, service_key: str, candidate: Candidate) -> None:
    response = requests.post(
        f"{base_url}/rest/v1/offer_candidates?on_conflict=discovered_url",
        headers=supabase_headers(service_key, "resolution=merge-duplicates,return=minimal"),
        json=asdict(candidate),
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def main() -> int:
    supabase_url = required_env("SUPABASE_URL").rstrip("/")
    service_key = required_env("SUPABASE_SERVICE_ROLE_KEY")
    brave_key = required_env("BRAVE_SEARCH_API_KEY")

    query_path = os.path.join(os.path.dirname(__file__), "search_queries.txt")
    with open(query_path, encoding="utf-8") as query_file:
        queries = [line.strip() for line in query_file if line.strip() and not line.startswith("#")]

    stats = {
        "searches_performed": 0,
        "results_found": 0,
        "candidates_created": 0,
        "offers_published": 0,
        "offers_updated": 0,
        "offers_expired": 0,
        "errors_count": 0,
    }
    run_id = create_run(supabase_url, service_key)
    seen: set[str] = set()

    try:
        for query in queries:
            results = brave_search(brave_key, query, count=10)
            stats["searches_performed"] += 1
            stats["results_found"] += len(results)

            for result in results:
                url = result.get("url", "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                try:
                    candidate = extract_candidate(url, query, result.get("description", ""))
                    upsert_candidate(supabase_url, service_key, candidate)
                    stats["candidates_created"] += 1
                except ValueError as exc:
                    print(f"Filtered {url}: {exc}")
                except Exception as exc:
                    stats["errors_count"] += 1
                    print(f"Skipping {url}: {exc}", file=sys.stderr)

        status = "completed_with_errors" if stats["errors_count"] else "completed"
        finish_run(supabase_url, service_key, run_id, stats, status)
        print(json.dumps(stats, indent=2))
        return 0
    except Exception as exc:
        stats["errors_count"] += 1
        finish_run(supabase_url, service_key, run_id, stats, "failed", str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
