# Meta Ads Agent

> **Start here: [TEAM-GUIDE.md](TEAM-GUIDE.md).** The whole workflow runs inside
> Claude Code — media buyers never touch a terminal or a script. The CLI
> commands below are what Claude runs on their behalf, documented for
> maintainers.
>
> The browser UI under `web/` and `api/` is **no longer the way in**. It still
> works if you run it, but the team works in chat.

Claude Code workspace for producing Meta (Facebook / Instagram) ad campaigns at
scale — from a written spec to created, **paused**, verified objects in Ads Manager.

Built for media buyers who are doing the same mechanical work hundreds of times:
uploading creatives, building ad sets, wiring pixels and URLs, applying naming
conventions, switching off creative enhancements, and checking it all landed.

> **Nothing in this repo can spend money.** Every campaign, ad set, and ad is
> created **PAUSED**, by construction — there is no flag to create anything
> active. A human launches, in Ads Manager, always.

---

## 1. Install

```bash
git clone <this-repo-url>
cd meta-ads-agent
```

Open the folder in **Claude Code**. It reads `CLAUDE.md` and `HANDOFF.md`
automatically and will know what this repo is and how to drive it.

Requires **Python 3.9+**. No pip installs needed — the scripts are standard
library only. (`pip3 install pyyaml` only if you prefer YAML specs over JSON.)

---

## 2. Get your Meta access token

You need a token with five permissions. This takes about five minutes.

### 2.1 Create the app

Go to **[developers.facebook.com/apps/create](https://developers.facebook.com/apps/create/)**.

When it asks what you want to do, pick **"Create and manage ads with Marketing
API"**. This matters — choose anything else and the permissions you need are
never offered later. Name it anything, and attach your Business account.

### 2.2 Add a Privacy Policy URL

Your app → **App settings → Basic** → fill in **Privacy Policy URL** →
**Save changes**.

Any working URL will do. The app stays in Development mode, is never reviewed,
and is never public — the field only has to be non-empty before Meta will grant
ads permissions. Your company's page, or [any public
one](https://www.iubenda.com/privacy-policy/7787549). One-off, per app.

### 2.3 Use cases → Customize

In your app's left sidebar, click **Use cases**. On **"Create and manage ads
with Marketing API"**, click **Customize**. Let it load.

> Do **not** use the old Graph API Explorer. The permissions you need are
> granted from inside the use case, not there.

### 2.4 Tools → Get access token

Inside the Customize screen, open the **Tools** tab, then click
**Get access token**.

Direct link — swap in your own app id from the browser address bar:

```
https://developers.facebook.com/apps/YOUR_APP_ID/use_cases/customize/tools/?use_case_enum=MARKETING_API_ADS_MANAGEMENT&selected_tab=tools&product_route=marketing-api
```

**Tick every permission in the list**, including:

- `ads_read`
- `ads_management`
- `business_management`
- `pages_read_engagement`
- `pages_show_list`

Select them all — miss one and the tools fail later with a confusing error.
Click **Get token**, approve the Facebook login prompt, and copy the `EAA...`
string.

### 2.5 Put it into `.env` — never into the chat

```bash
bash scripts/setup.sh
```

It prompts for the token **silently** (nothing is echoed), writes `.env` with
`600` permissions, confirms `.env` is gitignored, and verifies the token works.

> **Do not paste your token into the Claude chat window.** Anything typed in
> chat is stored in the conversation transcript. `setup.sh` keeps the token on
> your machine, in a file the agent reads directly. If you ever do paste one,
> revoke it: Facebook → Settings → Business Integrations → remove the app.

### 2.6 Confirm

```bash
python3 scripts/check_env.py
```

Prints who you are, the token's scopes and expiry, and every ad account you can
reach. Any missing permission is named explicitly.

### For teams: use a System User token instead

Tokens issued this way are tied to **one person** and expire in ~60 days.
For shared use, generate a **System User** token in Business Manager
(**Business Settings → Users → System Users → Add → Generate New Token**). It
never expires, belongs to the business rather than an individual, can be scoped
per ad account, and can be revoked without touching anyone's personal login.
Same permissions. Drop it into `setup.sh` the same way.

---

## 3. Daily use

**Always start here.** One command, checks everything, tells you what's missing:

```bash
python3 scripts/preflight.py
```

Everything below is safe to run — the first three are strictly read-only.

```bash
python3 scripts/discover.py                      # every ad account you can reach
python3 scripts/discover.py act_123456           # pages, IG, pixels, catalogs, campaigns
python3 scripts/audit_enhancements.py act_123456 # which live ads have enhancements ON
```

### The normal workflow: fill in a spreadsheet

1. Open **`spec/CAMPAIGN-TEMPLATE.xlsx`**, read the **START HERE** tab.
2. Fill in the **Campaign**, **Ad Sets**, and **Ads** tabs. Delete the grey
   example rows. Yellow cells are required.
3. Drop your images and videos into `creatives/`.
4. Save it as e.g. `specs/q3-uk.xlsx`, then tell Claude:
   *"Build the campaign in specs/q3-uk.xlsx"*

Claude converts it, validates every row, shows you a preview, and waits for your
go-ahead. Under the hood:

```bash
python3 scripts/xlsx_to_spec.py specs/q3-uk.xlsx --out specs/q3-uk.json
python3 scripts/build_campaign.py --spec specs/q3-uk.json            # preview only
python3 scripts/build_campaign.py --spec specs/q3-uk.json --execute  # create, PAUSED
python3 scripts/verify.py --state outputs/q3-uk-state.json --spec specs/q3-uk.json
```

### Or write the spec directly

Building a campaign is always two steps — validate, then execute:

```bash
# 1. Validate + preview. Makes NO API calls. This is the default.
python3 scripts/build_campaign.py --spec specs/q3-uk.json

# 2. Create everything, PAUSED, after a human has read the preview.
python3 scripts/build_campaign.py --spec specs/q3-uk.json --execute

# 3. Read it all back and diff against the spec.
python3 scripts/verify.py --state outputs/q3-uk-state.json --spec specs/q3-uk.json
```

### Adding to a campaign that already exists

Campaign names must be unique, so `build_campaign.py` refuses to rebuild one
that exists. To add into it instead:

```bash
python3 scripts/add_to_campaign.py --account act_<id> --list                 # which campaign?
python3 scripts/add_to_campaign.py --account act_<id> --campaign <id> --list # which ad set?
python3 scripts/add_to_campaign.py --account act_<id> --adset <id> --ads new-ads.csv
python3 scripts/add_to_campaign.py --account act_<id> --adset <id> --ads new-ads.csv --execute
```

`--ads` accepts a CSV or the **Ads** tab of a workbook. Ads already present in
that ad set are skipped, so re-running is safe. To add a whole new ad set to an
existing campaign, use `--campaign <id> --new-adsets-from <spec.json>`.

Or just describe what you want to Claude — it knows the workflow, will write the
spec with you, and will stop for your approval before step 2.

---

## 4. Web UI

For people who would rather click than type:

```bash
python3 web/server.py          # http://localhost:8770
```

Sign in, pick an ad account, then the same three questions: create a new
campaign, add to an existing one, or audit. Browsing and auditing happen right
in the browser; creating still runs from the CLI so the dry-run preview and
your approval stay in one place.

**Two auth modes**, set with `META_WEB_MODE`:

| Mode | How it works | Trade-off |
|---|---|---|
| `own_token` (default) | Each person pastes their own Meta token. Held in server memory for that session, never written to disk. | Meta's audit log attributes every change to the real person. |
| `access_code` | One shared token from `.env`, unlocked with `META_WEB_ACCESS_CODE`. | Convenient, but every action is attributed to the token owner, and one leaked code exposes every ad account that token reaches. |

```bash
META_WEB_MODE=access_code META_WEB_ACCESS_CODE=<code> python3 web/server.py
```

It binds to `127.0.0.1` only. Putting it on a shared host means adding TLS and
real logins first — see the security note in `web/server.py`.

## 5. Repo layout

| Path | What it is |
|---|---|
| `HANDOFF.md` | Orientation the agent reads first. Start here yourself too. |
| `CLAUDE.md` | The safety rules and workflow, loaded automatically by Claude Code. |
| `spec/CAMPAIGN-TEMPLATE.xlsx` | **The Excel template — start here.** Fill it in, hand it over. |
| `spec/SPEC.md` | The underlying spec format, if you'd rather write JSON. |
| `spec/examples/` | A working example spec + bulk ads CSV. |
| `scripts/preflight.py` | **Run first.** Checks everything, lists your ad accounts. |
| `scripts/add_to_campaign.py` | Add ads / ad sets to a campaign that already exists. |
| `scripts/` | `discover` · `xlsx_to_spec` · `build_campaign` · `verify` · `audit_enhancements` |
| `scripts/lib/meta.py` | The API layer. Safety rules are enforced here, in code. |
| `web/` | Browser UI: `server.py` (stdlib only) + `index.html`. |
| `adapters/` | Map **your team's existing** ad sheets into the spec format. |
| `reference/` | Meta Marketing API cheat sheet + hard-won gotchas. |
| `outputs/` | Run state, IDs, audit CSVs. Gitignored — never committed. |

---

## 6. What this repo will not do

- Create anything in an active state
- Un-pause, launch, or increase spend
- Invent a budget, ad account, Page, pixel, audience, or destination URL
- Claim a setting is applied without reading it back from Meta

Two Meta behaviours you should know about, documented in
[`reference/gotchas.md`](reference/gotchas.md):

- **Multi-advertiser ads cannot be verified.** Meta does not return
  `contextual_multi_ads` on read-back. We set it off; confirm in Ads Manager.
- **Disabling enhancements on a *live* ad is not an edit.** Creatives are
  immutable, so it means a new creative — which resets review, the learning
  phase, and social proof. Audit reports; a human decides per ad.
