# Meta Ads — how the team works

Everything happens in **Claude Code**. Nobody opens a terminal, writes a
formula, or touches Ads Manager until it is time to launch.

There are two jobs. Most people only ever do one of them.

---

## Setup — once, about 10 minutes

1. Install **Claude Code** (desktop app).
2. Clone the repo and open the folder in it:

```bash
git clone https://github.com/zdubaka-boop/meta-ads-agent.git
```

3. Type **`start`**. Claude checks everything and tells you what is missing.

If you have no Meta token yet, Claude walks you through getting one — about
five minutes in Facebook's developer site. Two steps trip everyone up and
Claude will flag both: adding a **Privacy Policy URL**, and ticking **all five**
permissions rather than four.

Your token goes into a local file, never into the chat. Claude will refuse it
if you paste it into a message, and tell you to revoke it.

---

## Job A — you write the ads (copy + creative)

You do not open Excel. You paste into the chat.

> Campaign: Spring Sale, traffic, €30/day
> Two ad sets — Lithuania 18-65, and Latvia 25-54
> Ads: spring1.jpg, spring2.jpg, spring3.jpg
> Primary text: "Big spring sale is on." and "Everything 30% off this week."
> Headline: "Shop the sale"
> Link: https://example.com/spring

Claude turns that into a filled-in workbook and gives you the file. Send it to
the buyer along with your images.

**Claude will ask you questions.** If you have not said which Page to run from,
what the budget is, or where the link goes, it stops and asks rather than
guessing. A guess in a live ad account is a real mistake, so expect the
questions and answer them.

---

## Job B — you launch and manage (media buyer)

Type **`start`**. Claude shows your ad accounts, you pick one, then it asks:

```
  1  Create a NEW campaign
  2  Add to a campaign that already exists
  3  See what's running
```

**1 — New campaign.** Drag the workbook into the chat with the images. Claude
checks every row, shows you what it is about to build, and waits for your yes.
Everything is created **paused**.

**2 — Add to an existing campaign.** Claude lists your campaigns, you pick one,
then say what you want:

> add these 4 images to the Lithuania ad set, same copy as the others

That is enough. Claude writes what it needs and adds **only the new ads**. The
campaign and everything already running are untouched, so nothing loses its
learning phase. You never need a spreadsheet for this.

**3 — See what's running.** Spend, results, CPA per campaign, ad set and ad,
plus which live ads still have Meta's creative enhancements switched on.

---

## Three things to know

**Nothing ever goes live by itself.** Everything is created **paused**. You
launch it in Ads Manager when you are ready. Ask Claude to turn ads *off* and
it does it immediately; ask it to turn them *on* and it asks you to confirm,
because that spends money.

**Claude never guesses.** Budget, ad account, Page, pixel, audience,
destination URL — if it was not told, it asks. If a creative file is missing it
says which one and stops.

**Ads that are already live cannot really be edited.** Meta locks creatives
once they exist, so changing a live ad means building a new one, which restarts
its review and its learning phase. Get it right at creation — that is what the
preview step before every build is for.

---

## When something goes wrong

Just say so in the chat. Claude reports exactly which step failed and what was
already created, so a retry never duplicates anything.

One honest gap: **multi-advertiser ads**. Meta will not report that setting back
through its API, so nobody can confirm it programmatically. Claude switches it
off when creating; check it by eye in Ads Manager.
