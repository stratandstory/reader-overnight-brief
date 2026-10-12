# 9. Make it yours

[← 8. Troubleshooting](08-troubleshooting.md) · [Back to the start](../../README.md)

Reader was written for one reader: a senior executive at a large U.S. bank, getting ready for the first pre-market meeting in New York. Most of that is easy to change. With Claude Code, describe what you want in plain words and it makes the change, explains it, and runs the free checks. Without it, the settings are text files in `~/Reader/config/` that any text editor can open (TextEdit works; keep the file as plain text).

After any change, `./brief dry-run` (free) confirms Reader still starts cleanly, and the next brief shows the effect.

## Your companies and themes

`config/watchlist.toml` has two lists.

- **themes**: the subjects the reader follows closely, in plain English. The AI uses them to judge what matters. Example: `"Semiconductors and AI hardware"`.
- **companies**: about a hundred large U.S. companies, each with its ticker and any other names headlines use for it. Company press releases are kept only if they name one of these, and the AI treats them as the big stocks when judging what matters.

Ask Claude: *"Add Arm Holdings to my watchlist"* or *"Replace the themes with ones for a European equity investor"*.

## Who the brief is for

The description of the reader, and the test for what's important, is a paragraph near the top of `reader/stages/common.py` (it begins `AUDIENCE =`). Every stage reads it. Changing it changes what the brief considers news, so make one change, run a brief, and read the result before changing more.

Ask Claude: *"Rewrite the audience for a wealth adviser whose clients hold mostly U.S. large caps and municipal bonds"*.

The brief always covers the period since the previous U.S. market close (4 PM New York) and is laid out for the New York morning. Moving it to another market is a larger change to the code; Claude can take it on, but expect to test it over several mornings.

## How long the brief is

In `config/settings.toml`, under `[brief]`:

| Setting | Default | What it is |
|---|---|---|
| `top_max` | 5 | most items in Top stories |
| `second_max` | 10 | most items in Also worth knowing |
| `developing_max` | 5 | most items in Developing |
| `calendar_trading_days` | 5 | trading days in the calendar section |

These are ceilings. A quiet night still gets a short brief; Reader never pads.

Under `[session]`, the previous trading day's highlights: news reported between that day's brief and the close, which no overnight window covers.

| Setting | Default | What it is |
|---|---|---|
| `enabled` | true | `false` leaves the section out, and the brief covers only the time since the close |
| `max_stories` | 3 | most stories in the section |
| `min_materiality` | 3 | the analyst's 1-to-5 rating a story needs (3 = moves a sector or a major stock) |
| `analyst_items` | 60 | most of the day's items shown to the analyst, besides the night's |

## A "Why it matters" line

Off by default. With `analysis = "labelled"` under `[brief]`, each item gets one line of the editor's own interpretation, in italics, marked **Why it matters**. It's the only text in the brief that no source states, which is why it's off by default and always labelled when on.

## SEC company filings

Reader can read the SEC's feed of company 8-K filings, but the SEC answers automated requests only when they include a contact email. To turn it on, add yours in `config/local.toml`:

```toml
[network]
contact_email = "you@example.com"
```

Privacy note: Reader then adds that email to its name on **every** request it makes, to every site it reads, not only the SEC.

## Copy each brief to another folder

To have each brief copied to a folder you can reach from other devices (a synced drive such as Google Drive, Dropbox or iCloud Drive), add to `config/local.toml`:

```toml
[brief]
workbench = "/Users/you/path/to/the/folder"
```

Each copy is named like `2026-10-06-reader-overnight-markets-brief.md`, starts with a short provenance block (produced by Reader, the date, the version, where the run's audit trail is), and is never overwritten (a second brief the same day becomes `-v2`). If the folder can't be found, the brief is still written and the run says so.

## The release calendar

The government's data releases (jobs, inflation, GDP) and the Fed's minutes come from `config/calendar.toml`, typed in by hand from the agencies' published schedules, with the page each date came from. It covers **October to December 2026**. The agencies post the next year's dates around December; until those are added, the calendar section shows only Fed meetings and dates from the night's news. Ask Claude to add them, giving it the agencies' schedule pages, or take the update when it's published.

## Models and the cost ceiling

`config/settings.toml` assigns a model to each stage. The assignment follows one rule: the stages that draft get a good model, the two stages that verify (check and audit) get the strongest, and a verifying stage never uses the same model as the stage it verifies. The models were chosen by testing them against real past mornings and real past errors, not by impression.

You can change them, but think before saving money on the checking stages: they are what make the brief trustworthy. `./brief eval-check` (a few cents) re-runs the checker on a set of real past errors and shows whether it still catches them.

`max_run_usd` under `[budget]` is the most a single brief may cost ($4). If a run approaches it, Reader checks fewer of the lower-priority stories rather than overspending.

## Settings that belong to your Mac

`config/local.toml` holds settings that are yours alone: your choice of sources, the `off` list, your contact email, your copy folder. Anything set there overrides `config/settings.toml`, and updates to Reader never touch it. When you're unsure where a change goes, put it in `local.toml`.

[Back to the start](../../README.md)
