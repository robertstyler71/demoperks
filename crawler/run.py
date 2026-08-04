from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
USER_AGENT = "DemoPerksBot/0.1 (+https://github.com/robertstyler71/demoperks)"
TIMEOUT = 15


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
        params={"q": query, "count": count, "safesearch": "strict", "freshness": "py"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("web", {}).get("results", [])


def clean_page_text(html: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return text[:25000], title


def fetch_page(url: str) -> tuple[str, str | None]:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        raise ValueError("Not an HTML page")
    return clean_page_text(response.text)


def infer_company(title: str | None, domain: str) -> str:
    if title:
        first = re.split(r"[|–—-]", title)[0].strip()
        if 2 <= len(first) <= 80:
            return first
    return domain.removeprefix("www.").split(".")[0].replace("-", " ").title()


def extract_candidate(url: str, query: str, snippet: str = "") -> Candidate:
    domain = urlparse(url).netloc.lower()
    text, title = fetch_page(url)
    haystack = f"{title or ''} {snippet} {text}"
    lower = haystack.lower()

    demo_terms = ["book a demo", "schedule a demo", "attend a demo", "product demo", "software demo", "demonstration"]
    reward_terms = ["gift card", "amazon card", "visa card", "prepaid card", "reward"]
    has_demo = any(term in lower for term in demo_terms)
    has_reward = any(term in lower for term in reward_terms)

    amount_match = re.search(r"\$\s?(\d{2,4}(?:\.\d{1,2})?)", haystack)
    reward_amount = float(amount_match.group(1)) if amount_match else None

    reward_type = None
    for label, patterns in {
        "Amazon Gift Card": ["amazon gift card", "amazon card"],
        "Visa Prepaid Card": ["visa gift card", "visa prepaid card", "visa card"],
        "Digital Gift Card": ["digital gift card", "e-gift card", "egift card"],
        "Gift Card": ["gift card"],
    }.items():
        if any(pattern in lower for pattern in patterns):
            reward_type = label
            break

    confidence = 0
    confidence += 35 if has_demo else 0
    confidence += 35 if has_reward else 0
    confidence += 15 if reward_amount else 0
    confidence += 10 if reward_type else 0
    confidence += 5 if domain and not domain.endswith(("facebook.com", "linkedin.com", "x.com")) else 0

    status = "approved" if confidence >= 85 else "needs_review" if confidence >= 60 else "rejected"
    rejection_reason = None if status != "rejected" else "Page did not clearly contain both demo and reward language."

    eligibility_match = re.search(r"(.{0,120}(?:qualified|eligible|eligibility).{0,220})", text, re.I)
    geography_match = re.search(r"(.{0,80}(?:united states|u\.s\.|canada|uk|united kingdom).{0,120})", text, re.I)
    expiration_match = re.search(r"(.{0,80}(?:expires?|valid (?:until|through)|offer ends).{0,120})", text, re.I)

    return Candidate(
        discovered_url=url,
        source_domain=domain,
        search_query=query,
        page_title=title,
        company_name=infer_company(title, domain),
        offer_title=title or "Software demo reward offer",
        reward_amount=reward_amount,
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
    payload = candidate.__dict__
    response = requests.post(
        f"{base_url}/rest/v1/offer_candidates?on_conflict=discovered_url",
        headers=supabase_headers(service_key, "resolution=merge-duplicates,return=minimal"),
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def main() -> int:
    supabase_url = required_env("SUPABASE_URL").rstrip("/")
    service_key = required_env("SUPABASE_SERVICE_ROLE_KEY")
    brave_key = required_env("BRAVE_SEARCH_API_KEY")

    query_path = os.path.join(os.path.dirname(__file__), "search_queries.txt")
    queries = [line.strip() for line in open(query_path, encoding="utf-8") if line.strip() and not line.startswith("#")]

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
