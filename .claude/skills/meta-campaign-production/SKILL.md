---
name: meta-campaign-production
description: >-
  Build Meta (Facebook/Instagram) ad campaigns from a brief or a spreadsheet —
  campaigns, ad sets, creative upload, and ads — all created PAUSED and verified
  against Meta by read-back. Use when the user wants to build, produce, upload,
  or bulk-create Meta ads, convert an ad tracker or CSV into a campaign, or
  duplicate and modify an existing campaign. Not for generating creative assets,
  and not for launching or un-pausing ads.
---

# Meta campaign production

Turn a brief or a spreadsheet into created, paused, verified Meta ad objects.

## Read order

1. `CLAUDE.md` — the non-negotiable rules. They override anything here.
2. `spec/SPEC.md` — the campaign spec format.
3. `reference/gotchas.md` — API behaviours that will bite you.
4. `reference/meta-api-cheatsheet.md` — full API reference. Consult, don't read through.

## Workflow

**1 — Discover.** Never write into an account you haven't looked at.

```bash
python3 scripts/discover.py act_<id>
```

Confirm the Page, Instagram account, and pixel with the user. If the account
exposes exactly one Page, still confirm it — do not silently adopt it. Pages
owned by a Business Manager do not appear on user-level endpoints; always use
the per-account discovery above.

**2 — Write the spec.** Put it in `specs/<campaign>.json`. Bulk ads go in a CSV
referenced by `ads_csv` — one row per ad. For hundreds of ads, always CSV.

If the user has their own tracker format, write an adapter instead of
reformatting their data by hand. See `adapters/README.md`.

**3 — Name what's missing.** Ask for everything ambiguous in one message:
budget figure, destination URL, Page, pixel and conversion event, targeting,
DSA beneficiary if the EU is targeted. Never fill any of these in yourself.

**4 — Dry run.** This is the default, and makes no API calls.

```bash
python3 scripts/build_campaign.py --spec specs/<campaign>.json
```

Show the user the preview and the endpoints you will POST to.

**5 — Wait for approval.** An explicit yes. Approval to build is never approval
to launch.

**6 — Execute.**

```bash
python3 scripts/build_campaign.py --spec specs/<campaign>.json --execute
```

Everything is created PAUSED. State is written after every object, so a run that
fails part way resumes rather than duplicating.

**7 — Verify.**

```bash
python3 scripts/verify.py --state outputs/<campaign>-state.json --spec specs/<campaign>.json
```

Show the user the diff. Report every ID. Where Meta returns nothing — notably
`contextual_multi_ads` — say it is unverifiable, never that it is applied.

## Duplicating a campaign

`POST /{id}/copies` works at campaign, ad set, and ad level. Ad copies accept
`creative_parameters`, so "duplicate the winner, new hook, new UTM" is one call
with no re-upload. `meta.copy_object()` forces `status_option=PAUSED`; never
override it — copies inherit real budgets and would spend immediately.

## Failure handling

Report the exact operation that failed and every ID already created. Never
re-run blind: the state file is the duplicate guard, so pass it back in.
