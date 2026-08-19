# Handoff — read this first

## What this is

A Claude Code workspace that turns a written campaign spec into created, paused,
verified Meta ad objects. It replaces the manual clicking: creative upload, ad
set construction, pixel and URL wiring, naming conventions, enhancement
switches, and the check that it all landed correctly.

It does **not** generate creative. Bring your own images and videos.

## Ten-minute onboarding

0. **`python3 scripts/preflight.py`** — run this first, always. It checks every
   prerequisite and tells you exactly what (if anything) is missing. Safe to run
   before setup: it degrades gracefully and names the one command to fix things.
1. **Get a token** — `README.md` §2. Five permissions, one privacy policy URL.
2. **`bash scripts/setup.sh`** — token goes into `.env`, never into chat.
3. **`python3 scripts/preflight.py`** again — should now say READY and list every
   ad account you can reach.
4. **`python3 scripts/discover.py act_<id>`** — see that account's Pages,
   Instagram accounts, pixels, catalogs, and existing campaigns.
5. **Open `spec/CAMPAIGN-TEMPLATE.xlsx`** — the Excel template. Read its START HERE
   tab, then fill in Campaign / Ad Sets / Ads. This is how most work will arrive.
6. **Read `reference/mcp-vs-api.md`** — when to use the Meta MCP instead of this repo.

Then just talk to Claude: *"Build me a prospecting campaign in act_X, two ad
sets, these 40 creatives, this landing page, €200/day CBO."* It will write the
spec, tell you what's missing, preview, and wait for your go-ahead.

## Bringing your existing ads across

You almost certainly already track ads in a sheet — a naming convention, a
column layout, a folder structure for creatives. You do **not** need to rewrite
any of it.

Instead, do this once:

> "Here is how our team tracks ads: `<paste a few rows / attach the sheet /
> point at the folder>`. Write an adapter that maps it to the spec format."

Claude will write a converter into `adapters/`, document the column mapping, and
from then on you work in **your** format. The adapter turns it into a spec, the
builder builds it. See `adapters/README.md`.

Give it a real sample — 10–20 rows including the messy edge cases. Mapping
guessed from a clean example breaks on the first ad with a comma in the body.

## Auditing what is already running

For accounts with ads already live:

```bash
python3 scripts/audit_enhancements.py act_<id> --csv outputs/audit.csv
```

Lists every ad with creative enhancements switched on. **Read-only** — it does
not change anything, deliberately. Disabling enhancements on a live ad requires
minting a new creative and repointing the ad, which resets review, the learning
phase, and accumulated social proof. That is a per-ad judgement call for a
media buyer, not something to bulk-apply.

## The safety model in one line

**Automate freely toward "off"** — audit, report, pause, reduce.
**Gate everything toward "on"** — create paused, launch by hand, never infer a budget.

Everything in `scripts/lib/meta.py` is built that way: there is no code path
that creates an active object, and no code path that invents a budget.

## Known limits

| Limit | Consequence |
|---|---|
| `contextual_multi_ads` is absent from API read-back | Multi-advertiser ads cannot be verified programmatically. Check in Ads Manager. |
| Ad creatives are immutable | Changing creative or its settings means a new creative + repointing the ad. |
| EU targeting requires `dsa_beneficiary` | Ad set creation fails without it. The builder validates for this. |
| Video processing is asynchronous | Large video uploads block for minutes before the ad can be created. |
| Campaign budget mode | ABO→CBO conversion in place worked in our testing on a paused campaign. Re-verify before relying on it for a campaign with spend history. |
