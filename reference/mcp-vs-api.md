# Meta MCP vs. this repo — what to use when

Meta ships an official MCP server at `https://mcp.facebook.com/ads`, connected
with Meta OAuth (no token pasting). This repo talks to the Marketing API
directly with a token. They are complementary, not competing — use both.

Capabilities below were **tested by us**, not taken from documentation.

## What the Meta MCP does well

| Task | Verdict |
|---|---|
| Create new ads | Works |
| Upload creatives | Works |
| Edit ad text and Pages (at creation) | Works |
| Create custom audiences | Works |
| Turn off creative enhancements | Works |
| **Duplicate a campaign** | **Works very well** |
| **Edit while duplicating** | **Works — this is the big time-saver** |

Duplicate-and-modify is the standout. Copying a proven campaign and changing
copy, links, or creative in the same operation removes most of the repetitive
build work. If you have a winner and need fifteen variants, this is the fastest
path that exists.

## Where the MCP stops

**Editing ads that are already created and running is very limited.** Once an ad
exists and is delivering, most changes cannot be made through the MCP. That work
stays manual, in Ads Manager.

This is not a bug in the MCP so much as how Meta works: ad creatives are
immutable. Changing an existing ad's creative or its settings means minting a
new creative and repointing the ad — which resets review, resets the learning
phase, and loses accumulated social proof. It is closer to relaunching the ad
than editing it, which is why no tool makes it easy.

**Practical consequence: get it right at creation.** Enhancements, naming, URLs,
tracking, and identity are cheap to set correctly up front and expensive to
change later. That is the whole argument for building from a spec.

## Where this repo adds something

| Need | Use |
|---|---|
| Build 1–20 ads conversationally | **MCP** — fastest, no setup |
| Duplicate a campaign and tweak it | **MCP** — its strongest feature |
| Build hundreds/thousands from a sheet | **This repo** — spec-driven, resumable |
| Guaranteed-paused, budget-never-inferred | **This repo** — enforced in code |
| Read-back verification against a spec | **This repo** — `verify.py` |
| Audit which live ads have enhancements on | **This repo** — `audit_enhancements.py` |
| Repeatable, reviewable, versioned campaigns | **This repo** — the spec is a file |

Rough rule: **conversation for a handful, spec file for a spreadsheet's worth.**
The moment the ad list lives in a sheet rather than in your head, the spec
workflow wins — it validates every row before a single API call, and it resumes
instead of duplicating when something fails at ad 400 of 900.

## Neither can do this

**Multi-advertiser ads (`contextual_multi_ads`) cannot be verified.** Meta does
not return the field on read-back through any interface. It shows as ON by
account default. Set it off, then confirm visually in Ads Manager — no tool can
prove it for you. See [gotchas.md](gotchas.md).
