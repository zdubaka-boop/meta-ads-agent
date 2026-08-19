#!/usr/bin/env bash
# Captures your Meta credentials into .env without ever echoing them.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Meta Ads Agent — setup"
echo "Your token is read silently and written to .env (gitignored)."
echo "Never paste a token into the chat window. See README.md §2."
echo

read -rsp "Paste Meta access token: " TOKEN; echo
[ -z "$TOKEN" ] && { echo "No token entered. Aborted."; exit 1; }
read -rp  "Default ad account ID (e.g. act_123456 — optional): " ACCT
read -rp  "Default Page ID (optional): " PAGE
read -rp  "Default Instagram user ID (optional): " IG
read -rp  "Default Pixel ID (optional): " PIXEL

umask 077
{
  echo "META_ACCESS_TOKEN=$TOKEN"
  [ -n "${ACCT:-}"  ] && echo "META_AD_ACCOUNT_ID=$ACCT"
  [ -n "${PAGE:-}"  ] && echo "META_PAGE_ID=$PAGE"
  [ -n "${IG:-}"    ] && echo "META_IG_USER_ID=$IG"
  [ -n "${PIXEL:-}" ] && echo "META_PIXEL_ID=$PIXEL"
  echo "META_API_VERSION=v23.0"
} > .env
chmod 600 .env
unset TOKEN

echo
echo "Saved to .env (permissions 600)."
git check-ignore -q .env && echo ".env is gitignored." || echo "WARNING: .env is NOT gitignored!"
echo
echo "Verifying..."
python3 scripts/check_env.py
