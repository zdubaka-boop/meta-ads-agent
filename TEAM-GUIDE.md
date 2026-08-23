# Meta Ads in Claude — team guide

We are moving Meta ad production into **Claude Code**. Everything below runs in
a chat window: launching campaigns, adding ads, checking performance, killing
what is not working, and going live.

Why: launching a 20-ad campaign by hand takes an afternoon of clicking. Here it
is one file and one sentence. Adding five creatives to a running ad set takes
about ten seconds instead of ten minutes. And once you are working in Claude,
the same window handles the rest of your day too.

This is version one. It works, it is safe, and it will get better as you tell
us what annoys you.

---

## Part 1 — Setup (once, ~10 minutes)

### 1.1 Install Claude Code

Download the desktop app and sign in.

### 1.2 Get the repo

```bash
git clone https://github.com/zdubaka-boop/meta-ads-agent.git
```

Open that folder in Claude Code.

### 1.3 Type `start`

Claude checks everything and tells you what is missing. If you have no Meta
token yet it walks you through getting one — about five minutes on Facebook's
developer site.

Two steps in that process trip up everyone, and Claude will flag both:

- **Add a Privacy Policy URL** in App settings → Basic. Any working URL. The app
  stays private and nobody reviews it, but Meta will not grant ads permissions
  while the field is empty.
- **Tick all five permissions**, not four: `ads_read`, `ads_management`,
  `business_management`, `pages_read_engagement`, `pages_show_list`.

### 1.4 Store the token

```bash
bash scripts/setup.sh
```

Paste the token when it asks. **Nothing appears on screen while you paste** —
that is deliberate, not frozen.

> **Never paste your token into the chat.** Chat is saved in the transcript.
> Claude will refuse it and tell you to revoke it if you do.

Type `start` again. You should see **READY** and a list of your ad accounts.

---

## Part 2 — The two jobs

### Job A — you write the ads

You never open Excel. You paste into the chat:

> Campaign: Spring Sale, traffic, 30 EUR a day
> Two ad sets — Lithuania 18-65 and Latvia 25-54
> Ads: spring1.jpg, spring2.jpg, spring3.jpg
> Primary text: "Big spring sale is on." and "Everything 30% off this week."
> Headline: "Shop the sale"
> Link: https://example.com/spring

Claude turns that into a filled workbook and hands you the file. Send it to the
buyer with your images.

**Claude will ask you questions.** If you have not said which Page to run from,
what the budget is, or where the link goes, it stops and asks instead of
guessing. A guess in a live ad account is a real mistake. Expect the questions.

### Job B — you launch and manage

Type `start`, pick your ad account, and Claude offers three things:

```
  1  Create a NEW campaign
  2  Add to a campaign that already exists
  3  See what's running
```

---

## Part 3 — Creating a campaign

Claude asks how you want to start. There are three ways and the middle one is
usually fastest.

**a — You have the filled-in template.** Drag the workbook into the chat along
with the images. Done.

**b — Copy a campaign that already exists.** Claude lists your campaigns, you
pick the closest one, and it comes back as a workbook with the targeting,
budgets, copy and creatives already in it. Change what differs and upload. Two
flavours:

- *same setup and same ads* — nothing to upload, creatives come across as Meta
  image IDs
- *same setup, new ads* — keeps the ad sets and targeting, leaves the ads blank

**c — From scratch.** Claude asks the full set of questions, offering your
account's real Pages and pixels so you never hunt for an ID.

Then it **shows you a preview** — campaign name, budget, how many ad sets and
ads, which countries — and waits for your yes. Nothing is created before that.

Everything lands **PAUSED**.

---

## Part 4 — Adding to a campaign that is already running

This never rebuilds anything. Rebuilding would restart the learning phase on
ads that are already delivering, so it only ever creates what is new.

**Adding ads to an ad set** — the everyday case:

> add these 5 images to the Polish ad set, same copy as the others

Drop the images in and that is enough. If an ad name already exists it is
skipped, so re-running is always safe.

**Adding a whole ad set** — usually a new market:

> duplicate the Polish ad set for Czechia

Claude copies it — with its ads if you want — and changes only the country,
name and budget you name. The original is untouched.

---

## Part 5 — Watching performance

> how is the Spring campaign doing?
> show me the 10 worst ads by CPA that have spent over 20 EUR

You get spend, results, CPA, CTR and clicks at campaign, ad set or ad level,
over any period from today to the last 90 days. All read-only.

---

## Part 6 — Turning things off

> turn off SPR26-PL-05 and SPR26-PL-07
> pause the whole Latvian ad set

Immediate and reversible. Pausing never costs anything, so Claude just does it.

---

## Part 7 — Going live

This is the only thing here that spends money, so it is deliberately harder
than everything else.

Meta only delivers when the campaign, its ad sets **and** its ads are all
switched on. Claude does all three at once, but first it shows you this:

```
  >>> THIS WILL START SPENDING 50.00 EUR PER DAY <<<
      about 350.00 EUR a week, 1500.00 EUR a month
```

**To actually launch, you have to state the daily budget yourself.** If you say
5.00 and the campaign holds 50.00, nothing happens and Claude tells you the
numbers disagree.

That guard exists for one reason: a yes/no prompt cannot catch "I thought this
was 5 a day and it is 500 a day". A number can.

Claude will never launch on its own. Asking it to build a campaign, or approving
a build, is not permission to go live — you have to ask, in that turn.

To stop everything instantly:

> turn off the whole Spring campaign

---

## Part 8 — Changing budgets

> put the Lithuanian ad set on 25 EUR a day

In your account's own currency. Claude warns you when a change is big enough to
reset Meta's learning phase (roughly ±30%), and refuses anything below the
account minimum.

**Claude never picks a budget.** The number comes from you, every time.

---

## What Claude will not do

- Create anything live. Everything is PAUSED until you launch it.
- Guess a budget, ad account, Page, pixel, audience or destination URL. If it
  was not told, it asks.
- Launch, raise a budget, or spend anything without you saying so in that turn.
- Claim something worked without checking. After every build it reads the ads
  back from Meta and shows you the result.

---

## Two honest limitations

**Ads that are already live cannot really be edited.** Meta locks creatives once
they exist, so changing a live ad means building a new one — which restarts its
review and its learning phase. Get it right at creation; that is what the
preview step is for.

**Multi-advertiser ads cannot be verified.** Meta will not report that setting
back through its API. Claude switches it off when creating, but nobody can
confirm it programmatically. Check it by eye in Ads Manager.

---

## When something breaks

Say so in the chat. Claude reports exactly which step failed and what was
already created, so retrying never duplicates anything.

**Tell us what annoyed you.** This is version one and it is built around what we
guessed the work looks like. The parts that feel slow or confusing are the parts
we fix next — that feedback is worth more than a bug report.
