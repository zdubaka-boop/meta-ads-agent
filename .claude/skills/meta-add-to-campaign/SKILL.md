---
name: meta-add-to-campaign
description: >-
  Add ads or a new ad set to a Meta campaign that already exists, without
  creating a duplicate campaign. Use when the user wants to add ads to a running
  or existing campaign, put new creatives into an existing ad set, add an ad set
  to a campaign, or when build_campaign.py has aborted because the campaign name
  is already taken. Everything is created PAUSED.
---

# Add to an existing campaign

`build_campaign.py` deliberately refuses to create a campaign whose name is
already taken — that guard is what prevents duplicate campaigns. This is the
route for working *into* what already exists.

## Walk the tree, don't ask for IDs

Media buyers do not know object IDs. Show them the list and let them point.

**1. Which campaign?**

```bash
python3 scripts/add_to_campaign.py --account act_<id> --list
```

Campaigns, newest first, with objective, status and CBO/ABO.

**2. Which ad set?**

```bash
python3 scripts/add_to_campaign.py --account act_<id> --campaign <id> --list
```

Ad sets with status, current ad count, budget and countries.

**3. Then ask what they want:**

```
  a  Add ads into one of these ad sets
  b  Add a NEW ad set (with its ads) to this campaign
```

## (a) Add ads to an existing ad set

```bash
python3 scripts/add_to_campaign.py --account act_<id> --adset <id> --ads new-ads.csv
python3 scripts/add_to_campaign.py --account act_<id> --adset <id> --ads new-ads.csv --execute
```

`--ads` takes a CSV, or an `.xlsx` — it reads the **Ads** tab, so the same
workbook works for both routes. Columns: `ad_name`, `creative_file`, `body`,
`headline`, `description`, `cta`, `link`, `url_tags`, `page_id`,
`instagram_user_id`. Blank fields fall back to `.env` defaults; a missing link
or page_id is an error, never a guess.

Dry run is the default. Show the preview, get a yes, then `--execute`.

**Ads whose name already exists in that ad set are skipped**, and a state file
records what was created, so re-running after a failure never duplicates.

## (b) Add a new ad set to an existing campaign

```bash
python3 scripts/add_to_campaign.py --account act_<id> --campaign <id> \
    --new-adsets-from specs/extra.json --execute
```

The spec needs only an `adsets[]` array (same shape as `spec/SPEC.md`). The
script reads whether the campaign is CBO or ABO and **rejects a mismatched
budget** rather than guessing: a budget on an ad set under a CBO campaign is an
error, and a missing budget under ABO is an error.

## Rules

- Everything is created **PAUSED**. Adding ads to a live campaign does not make
  them live — a human un-pauses each one.
- Adding an ad to an ad set with delivery history does **not** reset that ad
  set's learning. The new ad starts its own learning; the existing ones are
  untouched.
- Never infer a Page, link, pixel, or budget. Missing means stop and ask.
- `--json` on any command returns machine-readable output, for the web UI.
