# Gotchas — verified against the live API

Findings from our own testing, in addition to the upstream cheat sheet. Each one
cost a failed call or a wrong assumption.

## Campaign creation fails without `is_adset_budget_sharing_enabled`

Creating a campaign with **no campaign-level budget** (ABO) returns:

```
code 100 / subcode 4834011
"Must specify True or False in is_adset_budget_sharing_enabled field"
```

Set it explicitly to `"false"` for normal ABO. Only relevant when the campaign
itself carries no budget. `lib/meta.py` handles this.

## EU targeting requires DSA advertiser fields

Any ad set that can reach the EU fails with:

```
code 100 / subcode 3858081 / blame_field_specs: [["dsa_beneficiary"]]
"No advertiser indicated"
```

Supply `dsa_beneficiary` (and usually `dsa_payor`) — the legal name of the
entity being promoted. This is a **legal disclosure**, not a cosmetic field. It
must be correct before the campaign is ever un-paused. The builder validates for
it whenever an EU country is targeted.

## ABO → CBO conversion works in place

Contrary to the common assumption that campaign budget can only be set at
creation, this succeeded on a live (paused) campaign:

```
POST /{campaign_id}  daily_budget=200  bid_strategy=LOWEST_COST_WITHOUT_CAP
```

Meta **automatically cleared both ad set budgets** — no separate call needed,
no partial state. Verified by read-back. Re-test before relying on this for a
campaign with delivery history; Meta's restrictions tighten once money has moved.

## Enhancement opt-outs expand

Sending ~17 explicit `OPT_OUT` entries in
`degrees_of_freedom_spec.creative_features_spec` caused Meta to store **82
features, all OPT_OUT, zero OPT_IN**. Confirmed by read-back. You do not need to
enumerate all 82 — send the known list and Meta fills in the rest.

## `contextual_multi_ads` is invisible on read-back

Multi-advertiser ads shows as **ON** in Ads Manager by account/objective default
when the field is unset. Requesting it explicitly:

```
GET /{creative_id}?fields=contextual_multi_ads
```

returns the field **absent** — no value at all. So:

- You cannot verify its state through the API.
- Any claim that it is off is unprovable; report it as unverified.
- It **is** a documented, writable parameter (including inside
  `creative_parameters` on `/copies`), so we set it OPT_OUT on creation as
  best-effort — but confirm visually in Ads Manager.

This is the clearest example of why read-back verification has to distinguish
"confirmed off" from "we asked for off".

## Creatives are immutable

`object_story_spec`, `degrees_of_freedom_spec`, and `contextual_multi_ads`
cannot be patched on a creative already attached to an ad. Only `name` and
`status` are editable. To change any of them: create a new creative, then
`POST /{ad_id}` with `creative: {"creative_id": ...}`.

On a **live** ad this resets review, resets the learning phase, and loses social
proof unless `effective_object_story_id` is deliberately reused. It is closer to
relaunching the ad than editing it.

## `status_option` on `/copies` defaults dangerously

Object copies accept `status_option`, and reference examples in the wild use
`"ACTIVE"`. A copied campaign with `ACTIVE` **starts spending immediately**,
inheriting real budgets, with no review step. `lib/meta.copy_object()` forces
`PAUSED` and offers no override.

## User-level endpoints hide business-owned assets

`/me/accounts` and `/me/businesses` return only what is attached to the
**personal** account. Pages owned by Business Managers where you are an assigned
user will not appear — in our testing, 3 Pages via `/me/accounts` versus ad
accounts spanning 7 different businesses.

Always discover per ad account instead:

```
GET /act_<id>/promote_pages
GET /act_<id>/instagram_accounts
```

Using the user-level list would hand a buyer the wrong Page identity silently.

## Catalogs are not on the ad account

There is no `/act_<id>/product_catalogs` edge — that request fails with
"Tried accessing nonexisting field". Product catalogs belong to the **business**:

```
GET /act_<id>?fields=business{id}
GET /{business_id}/owned_product_catalogs?fields=id,name
```

This also needs the **`catalog_management`** permission, which is not in our
standard five scopes. Without it the call returns "This application has not been
approved for this capability". Catalog discovery therefore degrades gracefully
and is not required for normal campaign production — add the scope only if you
run catalog / Advantage+ shopping campaigns.
