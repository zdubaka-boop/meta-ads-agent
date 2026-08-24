# Campaign Brief Builder (artifact)

**Live:** https://claude.ai/code/artifact/bd85642c-869b-42dc-ba80-884564b36299

A form for specifying a campaign — countries, languages, ad sets, ads, multiple
primary texts and headlines — that outputs a brief you paste into Claude.

## What it is for

Filling in the spreadsheet is the slowest part of the job, and the part where
mistakes get made: a mistyped country code, a language name Meta does not
recognise, a budget on the wrong level. This removes all three. The country and
language pickers are built from Meta's own lists
(`reference/data/countries.json`, `reference/data/locales.json`), so a value
picked here is always a value Meta accepts.

It also flags what is still missing as you go — an ad set with no countries, two
ads sharing a name, an EU country without an advertiser name — before any of it
reaches an ad account.

## What it is NOT

**It cannot talk to Meta.** Artifacts run in a sandbox that blocks every
external network request, and cannot read your `.env`. So this builds the brief;
Claude builds the campaign.

The flow is: fill this in → copy the brief → paste into Claude with your images
→ Claude writes the workbook, previews it, and creates everything paused.

## Updating it

Edit `campaign-builder.html` and republish it to the same URL. The embedded
country and language lists are generated from the JSON in `reference/data/` — if
Meta ever changes them, regenerate those first and re-embed.
