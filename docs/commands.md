# Every command

[Back to the start](../README.md)

Run these in Terminal from the Reader folder (`cd ~/Reader` first), or ask Claude Code to run them. Commands marked **free** make no AI calls.

## Everyday

| Command | What it does | Cost |
|---|---|---|
| `./brief run` | Collects the latest news and writes the brief. 5 to 10 minutes. | about $1.50 to $3.50 |
| `./brief open` | Opens the newest brief. | free |
| `./brief doctor` | Checks that your key works and reaches every model, and shows your sources choice. | free |
| `./brief sources` | Each source's terms label and whether it answered at the last check, with possible gaps in the last 24 hours. | free |
| `./brief collect` | Fetches the feeds and stores new items. No brief. | free |
| `./brief dry-run` | Everything except the AI calls; shows what a brief would cost. | free |

## Setup and settings

| Command | What it does | Cost |
|---|---|---|
| `./setup.sh` | Builds Reader's private Python environment. Safe to run again. | free |
| `./set-api-key.sh` | Saves your API key (you paste it; nothing shows). | free |
| `./set-api-key.sh --clipboard` | Saves the key you've just copied, then clears the clipboard. Used by Claude Code so the key never enters the chat. | free |
| `./set-workspace.sh` | Saves a workspace ID, for a key that works across several workspaces. | free |
| `./brief choose-sources` | Shows the three choices of sources and saves yours. Add `official`, `unrestricted` or `all` to choose directly. | free |

## Schedule

| Command | What it does | Cost |
|---|---|---|
| `./schedule.sh collect` | Collect every 30 minutes; save each weekday morning's news at 6:30 AM. You run the brief yourself. | free |
| `./schedule.sh on` | The same, plus the brief at 6:30 AM Monday to Friday, with a notification. | each brief as usual |
| `./schedule.sh status` | What's scheduled, and the last thing each job did. | free |
| `./schedule.sh off` | Removes every scheduled job. | free |

## Mornings you missed, and comparisons

| Command | What it does | Cost |
|---|---|---|
| `./brief package` | Saves this morning's news window (previous close to 6:30 AM) to `data/packages/<date>/`, with `headlines.md`, a plain list of every headline and link. The schedule does this on weekdays. | free |
| `./brief run --package 2026-10-06` | Writes a missed morning's brief late, from its saved package, marked as written late. | as a brief |
| `./brief since 09:30` | Runs every stage over today's news since a time (New York), into its own run folder, without touching the brief or its memory. | about $1 to $2 |
| `./brief since close` | The same over the whole overnight window. Add `--resume <run-id>` to rewrite from a past run's checked claims for about $0.50. | about $1 to $2 |

## Testing

| Command | What it does | Cost |
|---|---|---|
| `./brief eval-check` | Re-runs the checker on real past errors (`tests/fixtures/checker.json`) and shows whether it still catches them. | a few cents |
| `./brief replay-find <run-id>` | Re-runs the analyst on a past morning's exact items, to judge a change to its instructions or model. | about $0.35 |
| `.venv/bin/python -m unittest discover -s tests -t .` | Reader's offline tests. | free |

[Back to the start](../README.md)
