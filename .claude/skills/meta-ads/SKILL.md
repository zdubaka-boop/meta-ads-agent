---
name: meta-ads
description: >-
  Run Meta ad work end to end in chat — check the token, pick an ad account,
  create a campaign from a filled template, or add ads and ad sets to a campaign
  that already exists without rebuilding it. Also turns a chat dump of copy, ad
  set names, links and creative filenames into a populated campaign workbook.
  Use for anything involving Meta / Facebook / Instagram ads in this repo:
  launching, adding ads, adding ad sets, auditing, pausing, or filling in the
  template. Everything is created PAUSED.
---

# Meta ads, run from chat

The people using this are media buyers, not engineers. They will never open a
terminal or read a script. You run everything; they answer questions.

## THE OPENING MOVE — every new conversation

Do not ask "how can I help". Diagnose, then present one short checklist.

```bash
python3 scripts/preflight.py
```

**No token → walk them through it.** preflight prints a complete 7-step
walkthrough. Relay it in your own words, in their language, calling out the two
steps people miss: the **Privacy Policy URL** in App settings → Basic, and
ticking **all five** permissions. Then stop. `setup.sh` prompts silently in
their terminal, so you cannot run it for them — tell them to run it and say
"done", then rerun preflight yourself.

**Token present → list their ad accounts and ask which one.** Never make them
type an ID; show the list and let them point at a row.

Then ask exactly this:

```
  1  Create a NEW campaign
  2  Add to a campaign that already exists
  3  See what's running / audit
```

## 1 — Create a new campaign

**Ask this FIRST, before anything else. Do not start interviewing them about
objectives and budgets — most of the time the answer makes those questions
unnecessary.**

```
  How do you want to start?

  a  I already have the filled-in template   → drop it in
  b  Copy the settings from a campaign that already exists
  c  From scratch — ask me the questions
```

**(a) They have a template.** Skip to the build steps below.

**(b) Copy an existing campaign — the fast path, and usually the right one.**
List the account's campaigns and ask which one is closest to what they want.
Then:

```bash
# structure, targeting AND the existing ads (creatives come out as image
# hashes, so no image files are needed to rebuild it)
python3 scripts/export_campaign.py <campaign_id> --out ~/Desktop/NEW.xlsx

# or: keep the structure and targeting, drop the ads, because the ads are new
python3 scripts/export_campaign.py <campaign_id> --out ~/Desktop/NEW.xlsx --settings-only
```

Ask which of those two they want — "same ads too" or "same setup, new ads".
Then tell them what came out (how many ad sets, which countries, what budget),
and ask only what actually changes: the campaign name, and whatever else
differs. Edit the workbook for them with `fill_template.py` or by editing the
cells directly — **do not make them open Excel** unless they want to.

**(c) From scratch.** Only now ask the full set: name, objective, budget and
mode, targeting, destination URL, creatives and copy. Run `discover.py` first
so you can offer the account's real Pages and pixels instead of asking them to
find IDs.

### Do they need to send image files at all?

Only for creatives Meta has never seen. Anything already in the ad account can
be named in `creative_file` and needs no file — that is how a campaign becomes
a single .xlsx, and it is the only route that works for video.

If they are sending the same creatives repeatedly, push the folder into the
account's library once:

```bash
python3 scripts/upload_creatives.py act_<id> ~/path/to/creatives --dry-run
python3 scripts/upload_creatives.py act_<id> ~/path/to/creatives
```

After that every future sheet is one file. Offer this the first time someone
attaches a folder of images.

There is never a README or any other file to send — only the workbook, plus
images if they are new.

### Then, for all three paths

```bash
python3 scripts/xlsx_to_spec.py <file>.xlsx --out specs/<name>.json
python3 scripts/build_campaign.py --spec specs/<name>.json              # preview
python3 scripts/build_campaign.py --spec specs/<name>.json --execute    # creates, PAUSED
python3 scripts/verify.py --state outputs/<name>-state.json --spec specs/<name>.json
```

Show them the preview in plain language — campaign name, budget, how many ad
sets and ads, which countries — and **wait for a yes** before `--execute`.
Afterwards show the verify diff and every ID.

If a creative file is missing, say which filenames you need and stop. Do not
substitute anything.

## 2 — Add to a campaign that already exists

**Never rebuild the campaign.** Rebuilding restarts the learning phase on
everything that is already delivering. Create only what is new.

List the campaigns and ask which one:

```bash
python3 scripts/add_to_campaign.py --account act_<id> --list
python3 scripts/add_to_campaign.py --account act_<id> --campaign <id> --list
```

Then ask what they want:

**(a) Add ads to one of these ad sets** — the common case.

```bash
python3 scripts/add_to_campaign.py --account act_<id> --adset <id> --ads new.csv
python3 scripts/add_to_campaign.py --account act_<id> --adset <id> --ads new.csv --execute
```

They usually will not have a CSV. That is fine — collect the details in chat
(images, copy, headline, link) and write the CSV yourself, then run the above.
Ads whose name already exists in that ad set are skipped automatically, so a
re-run is always safe.

**(b) Add a new ad set to the campaign.**

```bash
python3 scripts/add_to_campaign.py --account act_<id> --campaign <id> \
    --new-adsets-from specs/extra.json --execute
```

Build `extra.json` yourself from what they tell you. Read the campaign's
CBO/ABO mode off the live campaign — a budget on an ad set under a CBO
campaign is rejected, and a missing one under ABO is rejected. Never guess it.

## 3 — See what's running

```bash
python3 scripts/discover.py act_<id>
python3 scripts/audit_enhancements.py act_<id> --csv outputs/audit.csv
```

Report which ads still have creative enhancements on. Say plainly that turning
them off on a **live** ad means a new creative, which restarts review, resets
learning and loses social proof — a per-ad decision, not a bulk fix.

## Filling the template from a chat dump

Someone will paste a pile of copy, ad set names, links and creative filenames.
Turn it into JSON and run:

```bash
python3 scripts/fill_template.py brief.json --out ~/Desktop/CAMPAIGN.xlsx
```

The JSON shape is documented at the top of that script. Then send them the file.

**Ask about anything missing rather than filling it in.** Budget, Page, pixel,
destination URL and ad account are never inferred — a plausible guess is a real
mistake in a real account. Leave a field blank and say what is still needed
rather than inventing it.

## Verify properly, and fix what you find

`verify.py` is not optional and passing it is not the same as being correct.
It now checks two things that are true of a correct ad **regardless of what
the spec says**, because a spec parsed wrongly still matches whatever it built:

- **no literal `|` in the stored copy** — a pipe surviving into live ad text
  means the variant split never happened,
- **variant counts match** what the sheet asked for.

That distinction is not theoretical. A 20-ad campaign once passed 134/134
checks while every multi-variant ad had shipped with its three primary texts
concatenated into one string with the pipes visible. Spec equality did not
catch it; reading an actual ad back did.

So after any build, on top of `verify.py`, **fetch one real ad and look at it**:

```bash
python3 scripts/verify.py --state outputs/<name>-state.json --spec specs/<name>.json
```

If anything is wrong: **fix the code, delete what was built, and rebuild.** Do
not hand over a campaign with known-bad ads and a note about it. They are
PAUSED, so deleting and rebuilding costs nothing.

Before changing anything in the parsing path, and after fixing any bug:

```bash
python3 scripts/selftest.py     # offline, no API, no cost
```

Every test in there exists because that exact bug shipped once. Add a new one
whenever you fix a new one.

## Rules that do not bend

- **Everything is created PAUSED.** There is no path that creates a live ad.
  "Upload these" is never permission to launch.
- **Never infer a budget, ad account, Page, Instagram account, pixel,
  conversion event, audience or destination URL.** Missing means ask.
- **Show the full config and wait for a yes before any write.**
- **Verify by read-back.** Never say a setting was applied unless the object you
  fetched from Meta says so. Where Meta returns nothing — notably
  `contextual_multi_ads` — say it is unverifiable rather than claiming success.
- **Report every ID** created: campaign, ad set, creative, ad.
- **On failure, report the exact operation and the IDs already created.** State
  files prevent duplicates on a retry; use them rather than starting over.
- **Never ask for a token in chat.** It goes in `.env` via `scripts/setup.sh`.

## How to talk to them

Short. Concrete. Name the campaign, the count, the money. No jargon they did not
use first. When something is not possible, say so in one sentence and give the
nearest thing that is.
