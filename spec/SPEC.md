# Campaign spec format

One JSON (or YAML) file describes a whole campaign. Bulk ads live in a CSV so
they can be authored in a spreadsheet — that scales to thousands of rows.

The spec is the **contract**. `build_campaign.py` validates it, builds from it,
and `verify.py` diffs the created objects back against it. If it isn't in the
spec, it does not get created.

---

## Structure

```jsonc
{
  "account_id": "act_1234567890",

  "campaign": {
    "name": "Q3 Prospecting — UK",       // must be unique in the account
    "objective": "OUTCOME_SALES",        // see cheatsheet §13
    "budget_mode": "CBO",                // "CBO" = campaign budget, "ABO" = ad set budgets
    "daily_budget_minor": 20000,         // CBO only. MINOR units: 20000 = 200.00
    "special_ad_categories": []          // ["HOUSING"] etc. — changes targeting rules
  },

  "defaults": {                          // any ad may override any of these
    "page_id": "100000000000001",
    "instagram_user_id": "17841400000000000",
    "pixel_id": "200000000000002",
    "link": "https://example.com/lp",
    "cta": "SHOP_NOW",
    "url_tags": "utm_source=facebook&utm_medium=paid&utm_campaign=q3_prospecting",
    "dsa_beneficiary": "Example Ltd"     // REQUIRED when targeting the EU
  },

  "ads_csv": "spec/examples/example-ads.csv",   // optional bulk ads file

  "adsets": [
    {
      "name": "Q3 — UK — Broad 18-45",
      "daily_budget_minor": null,        // ABO only; must be null/absent for CBO
      "optimization_goal": "OFFSITE_CONVERSIONS",
      "billing_event": "IMPRESSIONS",
      "promoted_object": { "pixel_id": "200000000000002", "custom_event_type": "PURCHASE" },
      "targeting": {
        "geo_locations": { "countries": ["GB"] },
        "age_min": 18,
        "age_max": 45
      },
      "ads": [
        {
          "name": "Q3-UK-01-hook-price",
          "creative": "creatives/hook_price.jpg",
          "body": "Primary text that appears above the creative.",
          "headline": "Headline under the image",
          "description": "Optional link description.",
          "cta": "SHOP_NOW",
          "link": "https://example.com/lp?variant=a"
        }
      ]
    }
  ]
}
```

## Bulk ads CSV

Referenced by `ads_csv`, or passed with `--ads`. One row per ad. The `adset`
column must match an ad set `name` in the spec exactly.

```csv
adset,ad_name,creative,body,headline,description,cta,link
Q3 — UK — Broad 18-45,Q3-UK-01,creatives/a.jpg,"Body copy here.",Headline A,Free shipping,SHOP_NOW,https://example.com/lp
Q3 — UK — Broad 18-45,Q3-UK-02,creatives/b.mp4,"Different hook.",Headline B,,SHOP_NOW,https://example.com/lp
```

`creative` may be an image (`.jpg .png`), a local video (`.mp4 .mov`), or a
public direct HTTPS video URL. For a URL (for example a Dropbox link ending in
`?dl=1`), Meta fetches the video itself with `file_url`, so no video bytes cross
the machine running the builder. Google Drive share pages are not direct file
links and are unsuitable for large videos.

Local files are uploaded concurrently before ad creation (`--lanes 4` by
default). Videos over 40 MB use Meta's resumable chunk protocol. Identical
files—and repeated uses of the exact same URL—are uploaded **once** and reused
across every ad that references them and later resumptions.

---

## Rules the builder enforces

| Rule | Behaviour |
|---|---|
| Everything is created **PAUSED** | No flag exists to create anything active. |
| **Budgets are never defaulted** | ABO without `daily_budget_minor` → validation error. |
| **No identity is inferred** | Missing `page_id` or `link` → validation error. |
| Budgets are in **minor units** | `5000` = 50.00 in the account currency. |
| **EU targeting requires `dsa_beneficiary`** | Meta rejects the ad set otherwise. |
| CBO and ad set budgets are **mutually exclusive** | Setting both → validation error. |
| Ad names must be **globally unique** in the spec | They are the idempotency key. |
| Creative enhancements are **OPT_OUT** by default | Override per ad with `"enhancements": true`. |

## Idempotency

Every created object is written to `outputs/<campaign>-state.json` immediately.
Re-running `--execute` skips anything already in that file, so a run that dies
half way through resumes instead of duplicating. The builder also refuses to
start if a campaign of the same name already exists and no state file is given.


---

# Workbook column reference

`spec/CAMPAIGN-TEMPLATE.xlsx` has seven tabs. Yellow cells and dark-blue column
headers are required; everything else is optional and falls back to the Campaign
tab default, or to Meta's own default when left blank.

## Ad Sets tab

| Column | Meaning |
|---|---|
| `adset_name` | Unique within the spec. The join key used by the Ads tab. |
| `daily_budget_minor` / `lifetime_budget_minor` | ABO only. One or the other, never both. Minor units. |
| `optimization_goal` · `billing_event` · `bid_strategy` · `bid_amount_minor` | Delivery and bidding. |
| `countries` | ISO codes, comma separated: `GB,IE`. **Required.** |
| `excluded_countries` | ISO codes to exclude. |
| `cities` · `regions` | Plain names: `London,Manchester`. Resolved to Meta IDs and echoed back so you can check the match. Cities get a 10-mile radius. |
| `location_types` | `home+recent` (default) · `home` · `recent` · `travel_in` |
| `languages` | Names exactly as on the **Languages** tab: `English (UK),Polish`. Blank targets all languages. |
| `genders` | `All` · `Men` · `Women` |
| `age_min` · `age_max` | Defaults 18 and 65. |
| `interests` · `excluded_interests` | Plain names. Resolved to IDs, with audience reach printed for each. |
| `custom_audiences` · `excluded_custom_audiences` | Names of audiences that already exist in the ad account. |
| `advantage_audience` | `yes` lets Meta expand beyond your targeting. |
| `device_platforms` | `All` · `mobile` · `desktop` |
| `publisher_platforms` | `facebook,instagram,audience_network,messenger,threads`. Blank = Advantage+ placements. |
| `facebook_positions` · `instagram_positions` | Only valid alongside `publisher_platforms`. |
| `custom_event_type` | Conversion event, e.g. `PURCHASE`. |
| `start_time` · `end_time` | `2026-09-01T00:00:00+0300` |
| `dsa_beneficiary` | **Required for EU targeting.** Legal advertiser name. |

## Ads tab

`adset_name` · `ad_name` · `creative_file` · `body` · `headline` · `description` ·
`cta` · `link` · `display_link` · `url_tags` · `page_id` · `instagram_user_id`

The last six inherit from the Campaign tab when blank.

## Name resolution

Cities, regions, interests, and custom audiences are written as names and
resolved against Meta at conversion time. Every match is printed:

```
interest 'Skin care' -> Skin care (id 664130153728886, reach ~257137942)
city 'London'        -> London, England GB (key 812057)
```

**Read those lines.** A name that matches the wrong thing is the one failure
mode this design has — "Cosmetics" is unambiguous, "Apple" is not. A name that
matches nothing stops the run rather than being silently dropped.

Languages resolve offline from `reference/data/locales.json` (92 locales pulled
from Meta), so a typo is caught instantly with a "did you mean" suggestion.
