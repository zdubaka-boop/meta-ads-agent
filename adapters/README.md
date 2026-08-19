# Adapters — your format in, spec format out

You already have a way of tracking ads: a Google Sheet, an Airtable base, a
naming convention, a folder of creatives. Do not rewrite it. Write an adapter
once, keep working the way you work.

An adapter is a small Python script that reads **your** file and emits a spec
JSON plus an ads CSV (`spec/SPEC.md`).

## Creating one

Give Claude a real sample and ask:

> "Here are 20 rows from our ad tracker `<paste or attach>`. Our creative files
> live in `<path>` and are named `<convention>`. Write an adapter."

Include the messy rows — commas inside body copy, blank cells, inconsistent
casing, the ad that broke last month. An adapter built from a tidy sample fails
on the first real export.

Claude will write `adapters/<team>_adapter.py` and a short `MAPPING.md`
recording which of your columns feeds which spec field, and what it does with
anything missing.

## Contract

```bash
python3 adapters/<team>_adapter.py <your-file> --out specs/<campaign>.json
```

Must:
- emit a spec that passes `build_campaign.py` validation
- **fail loudly** on anything it cannot map — never substitute a default for a
  budget, Page, pixel, or destination URL
- resolve creative filenames to real paths and error if a file is missing
- leave the source file untouched

## Why fail loudly

An adapter that quietly defaults a missing budget to 10.00, or falls back to the
first Page it finds, will eventually build a thousand ads pointing at the wrong
identity — and every one will look correct in the preview. Missing data must
stop the run and name the row.
