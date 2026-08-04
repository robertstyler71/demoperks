# DemoPerks

Automated directory of incentivized SaaS demo offers.

## What is included

- `site/` — static public website connected to Supabase
- `crawler/` — daily Brave Search discovery crawler
- `.github/workflows/discover-offers.yml` — manual and daily GitHub Action

## Before publishing the website

Open `site/demoperks-config.js` and replace the placeholder with your Supabase **publishable** key. The publishable key is intended for browser use. Never place a secret or service-role key in this file.

## Required GitHub Actions secrets

In GitHub, open **Settings → Secrets and variables → Actions** and add:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `BRAVE_SEARCH_API_KEY`

The service-role key is backend-only. Store it only as a GitHub Actions secret.

## Run the crawler manually

Open **Actions → Discover demo offers → Run workflow**.

The crawler first writes discovered pages into `offer_candidates`. It does not automatically publish them to the public `offers` table yet. This safety step prevents weak or inaccurate search results from appearing publicly.

## Hosting

For Cloudflare Pages, connect this repository and set the build output directory to `site`. No build command is required.
