from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


TIMEOUT = 20
MIN_CONFIDENCE = 90
USER_AGENT = "DemoPerksBot/0.7 (+https://github.com/robertstyler71/demoperks)"
MAX_TERM_DISTANCE = 1200
MAX_SHORT_DESCRIPTION = 260
MAX_FULL_DESCRIPTION = 650
MAX_ELIGIBILITY_DETAILS = 500
MAX_OFFER_TITLE = 180

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
    r"once (?:an|the|your) appointment is completed",
    r"after (?:an|the|your) appointment is completed",
    r"complete (?:an|the|your) appointment",
)

# These require the page to describe an incentive, not merely mention gift cards.
INCENTIVE_PATTERNS = (
    r"(?:receive|get|earn|claim|qualify for|be sent|we(?:'|’)ll send|we will send)"
    r".{0,140}(?:amazon|visa|mastercard|digital|e-?gift|gift|prepaid)"
    r"(?:\s+gift)?\s+card",
    r"(?:receive|get|earn|claim|qualify for|be sent|we(?:'|’)ll send|we will send)"
    r".{0,140}\$\s?\d{2,4}(?:\.\d{1,2})?"
    r".{0,100}(?:gift card|prepaid card|cash reward|reward)",
    r"(?:gift card|prepaid card|cash reward|reward)"
    r".{0,140}(?:after|upon|following|when|for completing|in exchange for)"
    r".{0,120}(?:demo|demonstration|appointment)",
    r"(?:demo|demonstration|appointment)"
    r".{0,180}(?:receive|get|earn|claim|be sent|we(?:'|’)ll send|we will send)"
    r".{0,140}(?:gift card|prepaid card|cash reward|reward)",
    r"\$\s?\d{2,4}(?:\.\d{1,2})?"
    r".{0,100}(?:gift card|prepaid card|cash reward)"
    r".{0,180}(?:demo|demonstration|appointment)",
)

DISCONTINUED_PATTERNS = (
    r"offer (?:has )?(?:ended|expired|been discontinued)",
    r"promotion (?:has )?(?:ended|expired|been discontinued)",
    r"incentive (?:has )?(?:ended|expired|been discontinued)",
    r"no longer (?:available|valid|active|offered)",
    r"is no longer being offered",
    r"has been discontinued",
    r"this offer is closed",
    r"this promotion is closed",
    r"offer unavailable",
    r"promotion unavailable",
)


@dataclass
class LandingPageCheck:
    valid: bool
    reason: str
    final_url: str
    title: str | None
    text: str


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


def slugify(value: str) -> str:
    slug = value.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "software-company"


def company_website(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def format_reward_amount(amount: float | int | None) -> str:
    if amount is None:
        return ""
    numeric = float(amount)
    if numeric.is_integer():
        return f"${int(numeric)}"
    return f"${numeric:,.2f}"


def clean_display_text(value: str | None, max_length: int) -> str | None:
    if not value:
        return None

    text = str(value)
    replacements = {
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "â€“": "-",
        "â€”": "-",
        "Â": "",
        " ": " ",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)

    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_length:
        return text

    shortened = text[: max_length - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{shortened}."


def build_full_description(candidate: dict) -> str:
    short_description = build_short_description(candidate)
    company = candidate.get("company_name") or "the vendor"
    return clean_display_text(
        (
            f"{short_description} "
            f"Review the official {company} offer page for current qualification "
            "requirements, participation details, and reward terms."
        ),
        MAX_FULL_DESCRIPTION,
    ) or short_description


def build_offer_title(candidate: dict, check: LandingPageCheck, company_name: str) -> str:
    raw_title = (
        candidate.get("offer_title")
        or check.title
        or candidate.get("page_title")
        or f"{company_name} Demo Reward"
    )
    return clean_display_text(raw_title, MAX_OFFER_TITLE) or f"{company_name} Demo Reward"


def build_short_description(candidate: dict) -> str:
    company = candidate.get("company_name") or "This software company"
    amount = format_reward_amount(candidate.get("reward_amount"))
    reward_type = candidate.get("reward_type") or "gift card"
    extracted_text = candidate.get("extracted_text") or ""
    variable_reward = extracted_text.startswith("Variable reward: up to stated amount.")

    if variable_reward:
        return (
            f"Qualified participants may receive up to a {amount} {reward_type} "
            f"after completing a {company} product demonstration."
        )

    return (
        f"Qualified participants may receive a {amount} {reward_type} "
        f"after completing a {company} product demonstration."
    )


def clean_page_text(html: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None

    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return text[:50000], title


def match_positions(patterns: tuple[str, ...], text: str) -> list[int]:
    positions: list[int] = []
    for pattern in patterns:
        positions.extend(
            match.start()
            for match in re.finditer(pattern, text, re.I | re.S)
        )
    return positions


def terms_are_close(text: str, max_distance: int = MAX_TERM_DISTANCE) -> bool:
    demo_positions = match_positions(DEMO_PATTERNS, text)
    incentive_positions = match_positions(INCENTIVE_PATTERNS, text)
    return any(
        abs(demo_position - incentive_position) <= max_distance
        for demo_position in demo_positions
        for incentive_position in incentive_positions
    )


def verify_landing_page(url: str) -> LandingPageCheck:
    try:
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
    except requests.RequestException as exc:
        return LandingPageCheck(
            valid=False,
            reason=f"Landing page could not be verified: {exc}",
            final_url=url,
            title=None,
            text="",
        )

    final_url = response.url
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        return LandingPageCheck(
            valid=False,
            reason="Landing page is not an HTML page.",
            final_url=final_url,
            title=None,
            text="",
        )

    text, title = clean_page_text(response.text)
    page_text = f"{title or ''} {text}"

    if any(re.search(pattern, page_text, re.I | re.S) for pattern in DISCONTINUED_PATTERNS):
        return LandingPageCheck(
            valid=False,
            reason="Landing page says the offer is ended, expired, discontinued, or unavailable.",
            final_url=final_url,
            title=title,
            text=text,
        )

    demo_match = any(re.search(pattern, page_text, re.I | re.S) for pattern in DEMO_PATTERNS)
    if not demo_match:
        return LandingPageCheck(
            valid=False,
            reason="Exact landing page does not explicitly mention a demo or qualifying appointment.",
            final_url=final_url,
            title=title,
            text=text,
        )

    incentive_match = any(
        re.search(pattern, page_text, re.I | re.S)
        for pattern in INCENTIVE_PATTERNS
    )
    if not incentive_match:
        return LandingPageCheck(
            valid=False,
            reason="Exact landing page does not explicitly mention a gift-card or reward incentive.",
            final_url=final_url,
            title=title,
            text=text,
        )

    if not terms_are_close(page_text):
        return LandingPageCheck(
            valid=False,
            reason="Demo and incentive language are not close enough to clearly describe the same offer.",
            final_url=final_url,
            title=title,
            text=text,
        )

    return LandingPageCheck(
        valid=True,
        reason="Landing page explicitly mentions both the demo and the incentive.",
        final_url=final_url,
        title=title,
        text=text,
    )


def fetch_publishable_candidates(base_url: str, service_key: str) -> list[dict]:
    params = {
        "processing_status": "eq.approved",
        "confidence_score": f"gte.{MIN_CONFIDENCE}",
        "reward_amount": "not.is.null",
        "reward_type": "not.is.null",
        "page_title": "not.is.null",
        "select": (
            "id,discovered_url,source_domain,page_title,"
            "company_name,offer_title,reward_amount,"
            "reward_type,category,extracted_text,"
            "eligibility_details,geographic_restrictions,"
            "expiration_text,confidence_score"
        ),
        "order": "confidence_score.desc",
    }

    response = requests.get(
        f"{base_url}/rest/v1/offer_candidates",
        headers=supabase_headers(service_key),
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def fetch_active_offers(base_url: str, service_key: str) -> list[dict]:
    response = requests.get(
        f"{base_url}/rest/v1/offers",
        headers=supabase_headers(service_key),
        params={
            "status": "eq.active",
            "select": "id,claim_url,company_name,status",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def publish_offer(
    base_url: str,
    service_key: str,
    candidate: dict,
    check: LandingPageCheck,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    company_name = (
        candidate.get("company_name")
        or candidate.get("source_domain")
        or "Software Company"
    )

    claim_url = check.final_url
    short_description = clean_display_text(
        build_short_description(candidate),
        MAX_SHORT_DESCRIPTION,
    )
    full_description = build_full_description(candidate)
    eligibility_details = clean_display_text(
        candidate.get("eligibility_details"),
        MAX_ELIGIBILITY_DETAILS,
    ) or "Eligibility is determined by the vendor."

    payload = {
        "company_name": company_name,
        "company_slug": slugify(company_name),
        "company_website": company_website(claim_url),
        "company_logo_url": None,
        "offer_title": build_offer_title(candidate, check, company_name),
        "short_description": short_description,
        "full_description": full_description,
        "reward_amount": candidate.get("reward_amount"),
        "reward_currency": "USD",
        "reward_type": candidate.get("reward_type"),
        "category": candidate.get("category"),
        "audience_tags": [],
        "eligibility_details": eligibility_details,
        "geographic_restrictions": candidate.get("geographic_restrictions"),
        "claim_url": claim_url,
        "source_url": claim_url,
        "status": "active",
        "confidence_score": candidate.get("confidence_score"),
        "verified_at": now,
        "expires_at": None,
        "last_checked_at": now,
        "featured": False,
        "sponsored": False,
        "failed_check_count": 0,
    }

    response = requests.post(
        f"{base_url}/rest/v1/offers?on_conflict=company_slug,claim_url",
        headers=supabase_headers(
            service_key,
            "resolution=merge-duplicates,return=minimal",
        ),
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def mark_candidate_status(
    base_url: str,
    service_key: str,
    candidate_id: str,
    status: str,
    reason: str | None = None,
) -> None:
    payload = {
        "processing_status": status,
        "rejection_reason": reason,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    response = requests.patch(
        f"{base_url}/rest/v1/offer_candidates",
        headers=supabase_headers(service_key, "return=minimal"),
        params={"id": f"eq.{candidate_id}"},
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def deactivate_offer_by_url(
    base_url: str,
    service_key: str,
    claim_url: str,
    reason: str,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    response = requests.patch(
        f"{base_url}/rest/v1/offers",
        headers=supabase_headers(service_key, "return=representation"),
        params={"claim_url": f"eq.{claim_url}"},
        json={
            "status": "inactive",
            "last_checked_at": now,
            "failed_check_count": 1,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return len(response.json())


def deactivate_offer_by_id(
    base_url: str,
    service_key: str,
    offer_id: str,
    reason: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = requests.patch(
        f"{base_url}/rest/v1/offers",
        headers=supabase_headers(service_key, "return=minimal"),
        params={"id": f"eq.{offer_id}"},
        json={
            "status": "inactive",
            "last_checked_at": now,
            "failed_check_count": 1,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def audit_existing_offers(base_url: str, service_key: str) -> tuple[int, int]:
    checked = 0
    deactivated = 0

    for offer in fetch_active_offers(base_url, service_key):
        checked += 1
        check = verify_landing_page(offer["claim_url"])

        if check.valid:
            print(f"Verified active offer: {offer['claim_url']}")
            continue

        deactivate_offer_by_id(
            base_url,
            service_key,
            offer["id"],
            check.reason,
        )
        deactivated += 1
        print(f"Deactivated: {offer['claim_url']} - {check.reason}")

    return checked, deactivated


def main() -> int:
    supabase_url = required_env("SUPABASE_URL").rstrip("/")
    service_key = required_env("SUPABASE_SERVICE_ROLE_KEY")

    stats = {
        "active_offers_checked": 0,
        "active_offers_deactivated": 0,
        "qualified_candidates": 0,
        "offers_published": 0,
        "candidates_rejected": 0,
        "candidates_needing_review": 0,
        "errors": 0,
    }

    try:
        checked, deactivated = audit_existing_offers(
            supabase_url,
            service_key,
        )
        stats["active_offers_checked"] = checked
        stats["active_offers_deactivated"] = deactivated
    except Exception as exc:
        stats["errors"] += 1
        print(f"Failed to audit existing offers: {exc}")

    candidates = fetch_publishable_candidates(
        supabase_url,
        service_key,
    )
    stats["qualified_candidates"] = len(candidates)

    for candidate in candidates:
        candidate_url = candidate["discovered_url"]

        try:
            check = verify_landing_page(candidate_url)

            if not check.valid:
                transient_failure = check.reason.startswith(
                    "Landing page could not be verified:"
                )
                new_status = "needs_review" if transient_failure else "rejected"

                mark_candidate_status(
                    supabase_url,
                    service_key,
                    candidate["id"],
                    new_status,
                    check.reason,
                )

                deactivate_offer_by_url(
                    supabase_url,
                    service_key,
                    candidate_url,
                    check.reason,
                )

                if check.final_url != candidate_url:
                    deactivate_offer_by_url(
                        supabase_url,
                        service_key,
                        check.final_url,
                        check.reason,
                    )

                if transient_failure:
                    stats["candidates_needing_review"] += 1
                else:
                    stats["candidates_rejected"] += 1

                print(f"Not published: {candidate_url} - {check.reason}")
                continue

            publish_offer(
                supabase_url,
                service_key,
                candidate,
                check,
            )

            mark_candidate_status(
                supabase_url,
                service_key,
                candidate["id"],
                "approved",
                None,
            )

            stats["offers_published"] += 1
            print(
                f"Published: {candidate.get('company_name')} - {check.final_url}"
            )

        except Exception as exc:
            stats["errors"] += 1
            print(f"Failed to process {candidate_url}: {exc}")

    print(json.dumps(stats, indent=2))
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
