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

`creative` may be an image (`.jpg .png`) or a video (`.mp4 .mov`) — the builder
detects the type, uploads it, and waits for video processing. Identical files
are uploaded **once** and reused across every ad that references them.

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
