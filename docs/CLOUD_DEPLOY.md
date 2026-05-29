# Cloud Deployment

Use GitHub Actions if you want the radar to run even when your Mac is asleep or off.

## What Runs In The Cloud

- Daily schedule: `08:00 America/Toronto` during daylight saving time (`12:00 UTC`)
- Opportunity Radar schedule: `08:15 America/Toronto` during daylight saving time (`12:15 UTC`)
- Manual trigger: GitHub Actions `workflow_dispatch`
- Command: `python run_and_notify.py --days 7 --max-items 25 --per-query 12 --hn-per-query 15 --readme-limit 6 --require-email`
- Opportunity command: `python run_opportunity_notify.py --hours 48 --max-items 25 --hn-per-query 12 --feed-limit 10 --github-limit 10 --require-email`
- Output: Gmail digest plus downloadable `radar-reports` artifact
- State: `data/seen_repos.json` is restored/saved with GitHub Actions cache so new-on-radar detection can continue across runs

## Required GitHub Secrets

Add these under:

`Repo -> Settings -> Secrets and variables -> Actions -> New repository secret`

- `RADAR_EMAIL_TO`: `caishixun123@gmail.com`
- `SMTP_USER`: Gmail sender address
- `SMTP_PASSWORD`: Gmail 16-character App Password. Spaces are okay; the script removes whitespace before SMTP login.

Optional:

- `GH_SEARCH_TOKEN`: a GitHub personal access token to raise API rate limits. The built-in `GITHUB_TOKEN` is used if this is absent.

## Push To GitHub

This workspace does not currently have the `gh` CLI available, so create a private GitHub repository in the browser, then push this folder:

```bash
git init
git add .
git commit -m "Add AI OSS radar daily digest"
git branch -M main
git remote add origin git@github.com:<your-user>/<your-private-repo>.git
git push -u origin main
```

Important: `config/email.env` is ignored by `.gitignore`; do not force-add it.

## Test The Cloud Run

After pushing:

1. Open the GitHub repository.
2. Go to `Actions`.
3. Select `AI OSS Radar Daily Digest`.
4. Click `Run workflow`.
5. Confirm the Gmail digest arrives.
6. Check the `radar-reports` artifact if you want the full Markdown report.

Repeat the same for `Opportunity Radar Daily Digest` to verify the second daily email.

If the run exits with code `3`, the digest email was not sent. Check the `Check required secrets` step first; if all secrets are present, open the `Run radar and send Gmail digest` step and look for the Gmail SMTP error.

Reddit RSS may occasionally return HTTP 403 because Reddit blocks unauthenticated feed scraping. The Opportunity Radar treats this as a source warning and still sends the digest from HN, Product Hunt, GitHub Trending, YC, and newsletter feeds. For fully reliable Reddit coverage, add a future Reddit OAuth integration.

## Notes

GitHub cron schedules are UTC and can drift by a few minutes. The workflow is currently set to `12:00 UTC`, which is `08:00` in Toronto during daylight saving time. During standard time, change the cron to `13:00 UTC` if you want to keep exactly 08:00 local time.
