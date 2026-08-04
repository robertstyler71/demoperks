from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


TIMEOUT = 20
MIN_CONFIDENCE = 90


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


def build_short_description(candidate: dict) -> str:
    company = candidate.get("company_name") or "This software company"
    amount = format_reward_amount(candidate.get("reward_amount"))
    reward_type = candidate.get("reward_type") or "gift card"

    extracted_text = candidate.get("extracted_text") or ""
    variable_reward = extracted_text.startswith(
        "Variable reward: up to stated amount."
    )

    if variable_reward:
        return (
            f"Qualified participants may receive up to a "
            f"{amount} {reward_type} after completing a "
            f"{company} product demonstration."
        )

    return (
        f"Qualified participants may receive a "
        f"{amount} {reward_type} after completing a "
        f"{company} product demonstration."
    )


def fetch_publishable_candidates(
    base_url: str,
    service_key: str,
) -> list[dict]:
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


def publish_offer(
    base_url: str,
    service_key: str,
    candidate: dict,
) -> None:
    now = datetime.now(timezone.utc).isoformat()

    company_name = (
        candidate.get("company_name")
        or candidate.get("source_domain")
        or "Software Company"
    )

    claim_url = candidate["discovered_url"]
    extracted_text = candidate.get("extracted_text") or ""

    if extracted_text.startswith(
        "Variable reward: up to stated amount."
    ):
        full_description = extracted_text
    else:
        full_description = extracted_text[:5000]

    payload = {
        "company_name": company_name,
        "company_slug": slugify(company_name),
        "company_website": company_website(claim_url),
        "company_logo_url": None,
        "offer_title": (
            candidate.get("offer_title")
            or candidate.get("page_title")
            or f"{company_name} Demo Reward"
        ),
        "short_description": build_short_description(candidate),
        "full_description": full_description,
        "reward_amount": candidate.get("reward_amount"),
        "reward_currency": "USD",
        "reward_type": candidate.get("reward_type"),
        "category": candidate.get("category"),
        "audience_tags": [],
        "eligibility_details": candidate.get(
            "eligibility_details"
        ),
        "geographic_restrictions": candidate.get(
            "geographic_restrictions"
        ),
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
        (
            f"{base_url}/rest/v1/offers"
            "?on_conflict=company_slug,claim_url"
        ),
        headers=supabase_headers(
            service_key,
            "resolution=merge-duplicates,return=minimal",
        ),
        json=payload,
        timeout=TIMEOUT,
    )

    response.raise_for_status()


def mark_candidate_published(
    base_url: str,
    service_key: str,
    candidate_id: str,
) -> None:
    response = requests.patch(
        (
            f"{base_url}/rest/v1/offer_candidates"
            f"?id=eq.{candidate_id}"
        ),
        headers=supabase_headers(
            service_key,
            "return=minimal",
        ),
        json={
            "processing_status": "approved",
            "processed_at": datetime.now(
                timezone.utc
            ).isoformat(),
        },
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

    candidates = fetch_publishable_candidates(
        supabase_url,
        service_key,
    )

    stats = {
        "qualified_candidates": len(candidates),
        "offers_published": 0,
        "errors": 0,
    }

    for candidate in candidates:
        try:
            publish_offer(
                supabase_url,
                service_key,
                candidate,
            )

            mark_candidate_published(
                supabase_url,
                service_key,
                candidate["id"],
            )

            stats["offers_published"] += 1

            print(
                f"Published: "
                f"{candidate.get('company_name')} - "
                f"{candidate.get('discovered_url')}"
            )

        except Exception as exc:
            stats["errors"] += 1

            print(
                f"Failed to publish "
                f"{candidate.get('discovered_url')}: {exc}"
            )

    print(
        json.dumps(
            stats,
            indent=2,
        )
    )

    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
