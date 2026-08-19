---
name: meta-account-audit
description: >-
  Read-only audit of a Meta ad account — inventory of Pages, Instagram accounts,
  pixels, catalogs and campaigns, plus which live ads have creative enhancements
  switched on. Use when the user asks what's in an account, what's running, which
  ads have Advantage+ or automatic enhancements enabled, or wants a pre-flight
  check before building. Never modifies anything.
---

# Meta account audit

Strictly read-only. This skill reports; it never changes an ad.

## Inventory

```bash
python3 scripts/discover.py                 # every reachable ad account
python3 scripts/discover.py act_<id>        # assets + campaigns for one account
```

Reports Pages, Instagram accounts, pixels, catalogs, custom audiences, and every
campaign with its budget mode (CBO vs ABO).

## Enhancement audit

```bash
python3 scripts/audit_enhancements.py act_<id> --csv outputs/audit.csv
python3 scripts/audit_enhancements.py act_<id> --campaign <campaign_id>
```

Lists every ad with at least one creative feature set to `OPT_IN`.

## Reporting the result

Two things to be straight about with the user:

**Fixing a live ad is not an edit.** Creatives are immutable, so switching
enhancements off means a new creative and repointing the ad — which resets
review, resets the learning phase, and loses social proof. Present it as a
per-ad decision with that cost attached. Do not offer to bulk-fix.

**Multi-advertiser ads is not in this report.** Meta does not return
`contextual_multi_ads`, so it cannot be audited programmatically. Say so
explicitly and point the user at Ads Manager, rather than letting a clean audit
imply it was checked.
