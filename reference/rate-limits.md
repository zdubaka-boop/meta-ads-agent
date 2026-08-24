# Why a build crawls, and what to do about it

If a build sits there printing waiting messages, it is almost never the tool and
never your computer. It is Meta refusing calls on that ad account.

## The one thing that actually fixes it

Meta puts every app on an **access tier**. Ours is on `development_access`,
which gets a small fraction of the normal allowance. Everything below is
working around that; this is the fix.

The published hourly allowance for `ads_management`:

| Tier | Calls per hour |
|---|---|
| Development (where we are) | **300** + 40 × active ads |
| Full Access | **100,000** + 40 × active ads |

The account-level score cap also goes 60 → 9000, and a block drops from **300
seconds to 60**. That second number is most of what a slow build feels like.

**Getting to Full Access.** Meta relaxed this on 4 May 2026 — the screen
recording and written use-case are gone. Two gates remain:

1. **500+ Marketing API calls in the past 15 days**, with an **error rate under
   15%** over the last 500 calls. This happens by using the tool: one 144-ad
   build is roughly 300 calls. Live progress is shown at developers.facebook.com
   → the app → **App Review** → **Permissions and Features**.
2. **Business Verification** on the business that owns the app. Business
   Manager → **Security Centre** → **Start Verification**. One document from:
   Certificate/Articles of Incorporation, business registration or licence,
   government business tax document, business bank statement, or a utility bill
   under 12 months old. The legal name and the address must appear **on the same
   page** — that is what fails most submissions. Takes 1–5 working days.

The 15% error ceiling is why retrying a throttled build is worse than waiting:
the failures count against the thing you are trying to qualify for.

Check the app's own dashboard rather than trusting this page. Meta changes them.

**Shortcut worth trying first:** if any *other* app in the business already has
Advanced Access, issue the token from that app instead. The tier follows the
app, not the ad account, so this can fix it the same afternoon.

Until then the ceiling is the tier, not the tool. No code change gets around it.

## How to tell that is what is happening

Every Meta response carries a usage header. The tool reads it and will tell you:

```
NOTE: this app is on Meta's development_access tier — a small fraction of the
      normal rate allowance.
```

The three numbers Meta reports (`call_count`, `total_cputime`, `total_time`) are
**percentages of your allowance, not counts**. Any one of them hitting 100
blocks everything on that ad account until the window rolls. It is a rolling
window, not a quota you spend down for the day.

**Which one is actually binding matters.** A real reading from this account:

```
call_count: 1    total_cputime: 8    total_time: 51
```

1% of the call budget, 51% of the processing-time budget. The limit here is not
how many requests we send, it is how much work each one asks Meta to do. That
rules out the obvious fix — batching many calls into one changes nothing,
because the same work still happens server-side.

What does help is asking for less: fewer nested fields, one request per ad set
instead of one per ad, and never running insights during a build. Insights are
the most CPU-expensive thing in the API and can throttle an account on their
own while `call_count` sits in single digits.

## What the tool does about it now

- **Reads the header on every response.** Past 70% used it pauses briefly
  between calls, more as it climbs. A few seconds of pacing costs far less than
  the multi-minute block it prevents.
- **When Meta says how long you are blocked, it waits exactly that.** Meta
  returns `estimated_time_to_regain_access` in minutes. It used to guess
  45s → 90s → 180s → 300s, which either overshot or retried too early.
- **Does not fetch things nobody asked for.** Listing ad sets used to count the
  ads in each one, which meant paginating over every existing ad in the
  campaign before creating anything.

Turn pacing off with `META_PACE=0` if you want the old behaviour. You will hit
blocks sooner.

## What you can do without waiting for Meta

- **Split big builds across ad accounts.** The budget is per ad account, so two
  accounts is genuinely twice the headroom.
- **Build into campaigns that do not already hold hundreds of ads.** Every pass
  reads what is already there; a campaign with 100+ ads is expensive to touch
  before a single new ad exists.
- **Do not re-run a finished build to "check".** Use Ads Manager to look.
- **Spread it out.** The window rolls. 150 ads over an afternoon goes through;
  150 ads in ten minutes does not.

## What it is not

- Not your computer, your connection, or the size of your files.
- Not a per-person limit — it is per ad account, shared by everyone using it.
- Not something Ads Manager shows you. Ads Manager is Meta's own app on Meta's
  own tier and does not touch our allowance, which is why the same work by hand
  never hits this.
