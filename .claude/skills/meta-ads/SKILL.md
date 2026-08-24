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
ticking **all five** permissions.

**These people do not use a terminal and will not learn to for this.** Never
show them a shell command, never say "run this", never mention scripts, paths
or `bash`. You run everything.

Walk them through steps 1-5 on Meta's site, then say something like *"when you
have the token, tell me and a box will open for you to paste it into"* — and
**run this yourself the moment they say they have it**:

```bash
python3 scripts/save_token.py
```

If `scripts/save_token.py` is missing, their clone is out of date — pull first
(see "Keeping the tool up to date"), then run it.

A password box opens on their screen. They paste, press Save, done. It is
validated against Meta and its five scopes checked before anything is written.
Then rerun preflight yourself and show them their ad accounts.

A native password box opens on their screen; they paste the token in and press
Save. It is checked against Meta and its five scopes verified before anything
is written, then stored in `.env` at 0600. **The token never passes through the
chat**, so it never lands in a saved transcript.

If someone pastes a token into the chat anyway: tell them to revoke it at
facebook.com/settings?tab=business_tools, issue a new one, and use
`save_token.py`. Do not write a chat-pasted token to disk and carry on as if
nothing happened — it is in the transcript from that moment.

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
  c  I have a folder of creatives and the copy — you build it
  d  From scratch — ask me the questions
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

**(c) A folder of creatives plus a pile of copy.** See "The bulk drop" below.
This is the normal shape of a real brief — 100+ files and a wall of text.

**(d) From scratch.** Only now ask the full set: name, objective, budget and
mode, targeting, destination URL, creatives and copy. Run `discover.py` first
so you can offer the account's real Pages and pixels instead of asking them to
find IDs.

### The bulk drop — a folder of creatives and a wall of copy

Someone points at a folder of 200 images and pastes their copy underneath.
They are not going to fill in 200 rows, and neither are you by hand.

**Step 1 — read the filenames. Never guess the grouping.**

```bash
python3 scripts/scan_creatives.py ~/path/to/folder
```

It reports what the filenames look like and proposes a grouping — sub-folders
if there are any, otherwise the part of the name that varies like a market or
an angle. **Show them what it found and ask if the grouping is right.** One
group becomes one ad set. If it guessed wrong, they rename or re-nest and you
scan again; do not override it silently.

**Step 2 — turn their pasted copy into `copy.json` yourself.** They will paste
something like "LT: <three lines> PL: <four lines>". Read it, key it by the
group names the scan printed, and split their text into `bodies` and
`headlines`. Ask about anything genuinely ambiguous — never invent a line.

```json
{
  "lt": {"bodies": ["one", "two"], "headlines": ["A"]},
  "pl": {"price":    {"bodies": ["..."], "headlines": ["..."]},
         "_default": {"bodies": ["..."], "headlines": ["..."]}}
}
```

Angle keys are optional and only worth it when their filenames carry an angle
(`pl-price.png`, `pl-ugc.png`). `_default` covers every creative in that group
with no angle-specific copy. Several `bodies` rotate inside one ad — they do
not make extra ads.

**Step 3 — build the workbook.**

```bash
python3 scripts/bulk_build.py --creatives ~/path/to/folder --copy copy.json \
  --account act_<id> --name "<campaign name>" --budget 50 \
  --page <page_id> --link "https://..." --out ~/Desktop/CAMPAIGN.xlsx

# or, when they said "same settings as <campaign>":
python3 scripts/bulk_build.py --creatives ~/path/to/folder --copy copy.json \
  --like <campaign_id> --name "<campaign name>" --out ~/Desktop/CAMPAIGN.xlsx
```

`--like` reads objective, budget mode and amount, optimisation goal, billing
event, age range, Page, link, CTA, URL tags and DSA beneficiary off a real
campaign. It never copies its name or its ads.

Add `--dry-run` to show the pairing without writing anything — do that first
when the folder is large.

**Step 4 — read what it printed.** It lists every field it could not fill and
every creative it has no copy for. Those are blank on purpose. Take them back
to the user; do not fill them in yourself. Then convert and build as normal.

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

## Day-to-day management

Launching is the small part. Most of the job is looking at numbers and turning
things off.

**See performance** — read-only, run it freely:

```bash
python3 scripts/report.py act_<id> --days 7
python3 scripts/report.py act_<id> --level ad --campaign <id> --days 30
python3 scripts/report.py act_<id> --level ad --sort cpa --worst 10 --min-spend 20
```

`--worst` with `--min-spend` is the kill list: the worst performers that have
spent enough for the number to mean anything.

**Turn things off** — never costs anything, always reversible:

```bash
python3 scripts/set_status.py --off --ads <id>,<id>
python3 scripts/set_status.py --off --adset <id> --execute
```

**Change a budget** — the figure always comes from the user, never from you:

```bash
python3 scripts/set_budget.py <campaign_or_adset_id> --daily 25.00
python3 scripts/set_budget.py <campaign_or_adset_id> --daily 25.00 --execute
```

It warns when a change over ±30% would reset the learning phase, and refuses
anything below the account minimum.

**Duplicate an ad set** — "same thing, different country":

```bash
python3 scripts/duplicate_adset.py <adset_id> --name "..." --countries CZ,SK --execute
```

## Launching — the only thing here that spends money

Everything this repo creates is PAUSED. Going live means switching on the
campaign, its ad sets AND its ads, because Meta only delivers when all three
are active.

```bash
python3 scripts/set_status.py --launch --campaign <id>          # shows the tree + daily cost
python3 scripts/set_status.py --launch --campaign <id> --execute --authorise-daily 50.00
```

**Never run the second command on your own initiative.** The user must ask to
launch, in those words, in that turn. "Build it" and "add these ads" are not
permission to launch, and neither is having approved a build earlier.

The `--authorise-daily` figure must match what the campaign actually holds, or
Meta is never called. Show the user the dry run first — it prints the daily,
weekly and monthly spend — and let **them** tell you the number to authorise.
Do not read it off the dry run and pass it back yourself; the whole point is
that a human states the amount independently.

If anything fails partway, ads are switched on before ad sets and the campaign
last, so a failure leaves the campaign off and nothing delivering.

To stop everything immediately:

```bash
python3 scripts/set_status.py --off --campaign <id> --execute
```

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
