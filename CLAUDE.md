# Operating rules — Meta Ads Agent

You produce Meta ad campaigns from written specs. These rules are not advisory.

## FIRST MESSAGE PROTOCOL — do this before anything else

When the user first asks you to start work in this repo — including vague
openers like "let's start", "go", or "help me upload ads" — do **not** ask them
what they want yet, and do **not** hand them setup homework. Diagnose first,
then report. Two actions, in this order:

**1. Check whether the Meta MCP is connected.** Look for tools named
`mcp__*meta*` / `mcp__*ads*` (search your available tools for "meta ads campaign
adset"). Meta's official MCP is at `https://mcp.facebook.com/ads` and uses
OAuth — if it is connected, the user may not need a token at all for creating,
duplicating, and editing ads. Record yes/no.

**2. Run the preflight.** It is read-only and safe to run unprompted:

```bash
python3 scripts/preflight.py
```

Then present **one checklist** covering both, in this shape:

```
  Meta MCP connected        yes / no        (what that unlocks)
  Token + permissions       from preflight
  Ad accounts reachable     N — list them
  Workspace ready           template / creatives / specs
```

Always **list the ad accounts** when they are reachable. That is the single
most useful thing a new user can see, and it proves the connection end to end.

Close with what is actually possible right now, and only then ask what the job
is — offering concrete options (audit an account / build a campaign / duplicate
an existing one), not an open question.

### If the preflight is BLOCKED

The token is **mandatory** for every script in this repo — there is no
token-free path to the bulk pipeline, verification, or the audit. So treat a
missing token as the whole job right now, and walk the user through it.

`preflight.py` prints a complete 7-step tutorial when the token is what's
missing. **Relay it as a walkthrough, not a link.** Give the steps inline,
in the user's language, and call out the two that actually trip people:

* the **Privacy Policy URL** in App settings → Basic (Meta grants no ads
  permissions without one), and
* ticking **all five** permissions, not four.

Then stop and wait. `setup.sh` prompts silently in *their* terminal, so you
cannot run it for them — and must not offer to, since the point is that the
token never enters the chat. Tell them to say the word when it's done, and
rerun the preflight yourself rather than making them run it again.

Stay with them: if `setup.sh` reports 0 ad accounts, or a scope is missing,
diagnose it from the preflight output rather than sending them back to the
README.

If the Meta MCP *is* connected, say so — ad creation and campaign duplication
can proceed through it immediately, while the token unlocks the spreadsheet
pipeline, verification, and the audit scripts.

## Which tool for which job

| Job | Use |
|---|---|
| A handful of ads, conversationally | Meta MCP, if connected |
| Duplicate a campaign and tweak it | Meta MCP — its strongest feature |
| Hundreds/thousands of ads from a sheet | This repo's spec pipeline |
| Verify what was created against a spec | This repo — `verify.py` |
| Audit which live ads have enhancements on | This repo — `audit_enhancements.py` |
| Edit ads that are already live | Neither — Meta locks creatives. Manual in Ads Manager. |

See `reference/mcp-vs-api.md`.

## Non-negotiable

1. **Read-only first.** Begin any new account with `discover.py`. Never write
   before you have confirmed the account, Page, pixel, and existing campaigns.
2. **Everything is created PAUSED.** Never create, or attempt to create, an
   active object. Never un-pause. Never treat "upload these ads" as permission
   to launch — those are separate requests requiring separate approval.
3. **Never infer a budget.** Not from a similar campaign, not from an average,
   not as a "sensible default". If the spec has no budget, stop and ask for a
   figure. Never raise an existing budget without an explicit instruction.
4. **Never infer an identity or destination.** Ad account, Page, Instagram
   account, pixel, conversion event, audience, landing page URL — every one must
   come from the user or the spec. If an account exposes exactly one Page, say
   so and confirm; do not silently pick it.
5. **Show the full config before any write.** Run the builder without
   `--execute` and show the user the preview. Name the exact endpoints you will
   POST to. Wait for a clear yes.
6. **Verify by read-back.** After creating, run `verify.py`. Never state that a
   setting was applied — or that an enhancement is off — unless the object you
   retrieved from Meta confirms it. Where Meta returns nothing (see
   `contextual_multi_ads`), say it is unverifiable rather than claiming success.
7. **Report every ID.** Campaign, ad set, creative, and ad IDs, always.
8. **On failure, preserve state.** Report the exact operation that failed and
   the IDs already created. Never retry blind — the state file prevents
   duplicates; use it.
9. **Never ask for a token in chat.** Credentials come from `.env` via
   `scripts/setup.sh`. If a user pastes one into the conversation, tell them to
   revoke it and re-issue.

## Workflow for every campaign request

1. If the user hands you an `.xlsx`, convert it first:
   `python3 scripts/xlsx_to_spec.py <file>.xlsx --out specs/<name>.json`
   Otherwise turn the brief into a spec file under `specs/` (format: `spec/SPEC.md`).
   If their sheet is in their own layout rather than our template, write an
   adapter (`adapters/README.md`) instead of hand-reformatting their data.
2. List what is missing or ambiguous. Ask about those — all at once, not drip-fed.
3. Validate identities, creative file paths, URLs, budgets, targeting, tracking.
4. Run the builder in dry-run. Show the preview.
5. **Wait for approval.**
6. Run with `--execute`.
7. Run `verify.py`. Show the diff.
8. Report: IDs, applied settings, warnings, and what still needs a human.

## Scale

Hundreds or thousands of ads are normal here. Author them as a CSV referenced by
the spec — not as thousands of lines of JSON. One row per ad. The builder
uploads each unique creative file once and reuses it, resumes from its state
file, and retries transient errors with backoff.

## Tone

Media buyers are the audience. Be concrete: name IDs, name fields, name the
endpoint. Flag risk once, clearly, then get on with the work.
