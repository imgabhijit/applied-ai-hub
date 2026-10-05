# Refresh schedule: GitHub Actions `schedule`

The `Refresh Data` workflow (`.github/workflows/refresh.yml`) runs on GitHub's
own `schedule` trigger **four times a day** (00:17, 06:17, 12:17 and 18:17 UTC,
which is 05:47, 11:47, 17:47 and 23:47 IST). No external service is needed. You
can also run it by hand from the Actions tab (**Run workflow**).

## Why four ticks a day

GitHub documents `schedule` as best-effort: under load it delays or silently
drops ticks, with no retry. The sibling `news-hub` project measured roughly a
44-50% hit rate. For a news site that was too unreliable; for this one it is
fine, because applied-AI channels upload a few times a week and nobody needs
sensational freshness. Four ticks a day means about two land on average and at
least one almost always does, so the data is refreshed once or twice a day.

The ticks are at minute 17, not :00, because the top of the hour is when GitHub's
scheduler is busiest.

## Extra ticks are cheap

`scripts/fetch.py` does not re-scan everything on every tick. A channel is scanned
only when it is overdue (`DEFAULT_CADENCE_HOURS = 11`), so a tick shortly after a
successful one does almost nothing and uses almost no YouTube quota. If a tick is
dropped, the next one finds the channels overdue and scans them. Quota stays at
roughly 300 units per real scan, so about 600 a day.

## One-time setup

1. Add the `YOUTUBE_API_KEY` repository secret: Settings -> Secrets and variables
   -> Actions -> New repository secret.
2. Settings -> Actions -> General -> Workflow permissions: **Read and write**
   (the workflow commits the updated data files).
3. Scheduled workflows only run from the default branch (`main`), so merge/push
   there. Run **Refresh Data** once manually to confirm it works.

## Troubleshooting

- **Schedule seems to have stopped**: GitHub pauses scheduled workflows in public
  repositories after about 60 days with no repository activity. The data commits
  from the workflow should keep it active, but if it ever stops, open the Actions
  tab and re-enable the workflow.
- **Workflow runs but data does not change**: look at the `Fetch YouTube videos`
  step for `[quota]` messages. The written-feed step runs independently.
- **Fewer runs than expected**: normal; see "Why four ticks a day". If the hit rate
  turns out too low in practice, you can add a second trigger source later (an
  external cron such as cron-job.org calling `workflow_dispatch`) without changing
  any code.
