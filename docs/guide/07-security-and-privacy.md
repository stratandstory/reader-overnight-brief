# 7. Security and privacy

[← 6. Every morning](06-every-morning.md) · Next: [8. Troubleshooting](08-troubleshooting.md)

Reader runs entirely on your Mac, with your accounts. This page covers the one secret it holds (your API key), what leaves your Mac and where it goes, what Claude Code can and can't see, and how to remove Reader completely.

## Your API key

**What it is.** A password that lets a program spend your Anthropic credit. Whoever has it can run up charges until the key is disabled or your spending limit is reached.

**Where Reader keeps it.** In one file, `~/Reader/.env`, which only your Mac user account can read (`./set-api-key.sh` sets that permission). Reader sends the key to one place only: Anthropic's API, `api.anthropic.com`. It is never shown on screen, written to a log or included in a run report.

**Rules of thumb:**

- Give the key to Reader with `./set-api-key.sh` and nowhere else. Never paste it into a chat (including Claude), an email, a message, a document, a note or a screenshot.
- Never share or upload the `.env` file. If you copy the Reader folder to share with someone, leave `.env` out. (Reader's `.gitignore` already keeps it out of git, in case you use git.)
- Set a monthly spending limit in the console ([guide 2, step 3](02-api-key.md#step-3-set-a-monthly-spending-limit-recommended)). It caps the damage if the key ever leaks.
- Use a key just for Reader, so you can disable it without affecting anything else.

### If your key leaks

If the key was pasted somewhere it shouldn't be, or you're simply not sure:

1. In the Claude Console, open **Settings → API keys**.
2. Find the key and **Disable** it (reversible) or **Delete** it (permanent). Either one stops it working straight away.
3. **Create key** to make a new one, and save it with `./set-api-key.sh` ([guide 4, step 4](04-setup-in-terminal.md#step-4-save-your-api-key)) or by asking Claude Code.
4. Look at the console's **Usage** page for anything you don't recognise.

It takes two minutes. When in doubt, do it.

## What leaves your Mac

| Where it goes | What's sent | Why |
|---|---|---|
| The publishers and agencies Reader reads | An ordinary web request for their feed or page, with Reader's name (`ReaderBrief/0.1 (personal morning news brief)`) and, like every web request, your internet address | To read the news |
| Anthropic's API | Headlines, summaries and official pages from the night's news; Reader's drafts of claims and of the brief | To screen, check, write and audit the brief |
| Nowhere else | | |

Reader sends nothing about you to Anthropic: no name, no email, no files from your Mac. The only personal things in its requests are what you put in its settings yourself: the themes in your watchlist go to the AI as part of its instructions, and if you add a contact email so Reader can read SEC filings ([guide 9](09-make-it-yours.md#sec-company-filings)), that email is added to Reader's name on **every** request it makes, to every site.

**What Anthropic does with it.** Anthropic's documentation says data sent to its API is never used to train its models without your express permission. Claude Fable 5.1, the model Reader uses to check and audit, requires the account's standard 30-day data retention, so Anthropic keeps those requests and responses for up to 30 days. See Anthropic's [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) page for the details.

## What stays on your Mac

Everything else stays in the Reader folder:

| Where | What |
|---|---|
| `briefs/` | Your briefs |
| `data/reader.db` | The headlines and summaries Reader has collected, and its memory of which stories earlier briefs covered |
| `data/runs/` | A full report for every run |
| `data/packages/` | Each weekday morning's saved news, if the schedule is collecting |
| `config/local.toml` | Your own settings: which sources to read, anything you've changed |
| `.env` | Your API key |

None of it is uploaded anywhere. If you set Reader to copy each brief to a folder ([guide 9](09-make-it-yours.md#copy-each-brief-to-another-folder)), such as a synced drive, the copy goes wherever that folder syncs.

## Claude Code

If you set Reader up with Claude Code:

- Claude can read the files in the Reader folder and run commands there **that you approve**. What it reads becomes part of your conversation, which is handled under your Claude plan's terms and your account's privacy settings.
- Reader's folder includes Claude Code settings (`.claude/settings.json`) that stop Claude reading `.env`, stop it reading your clipboard directly, and make it ask you before any command that costs money or changes your Mac's schedule. Reader's instructions for Claude (`CLAUDE.md`) tell it never to ask for, read or repeat your key.
- These are safeguards, not guarantees. The one that matters most is yours: **never type or paste the key into the conversation**, and decline any request to read `.env`.

## The schedule

`./schedule.sh` adds small job files to your user account's own `~/Library/LaunchAgents` folder (they're named `com.reader.collect`, `com.reader.package` and `com.reader.brief`). They run as you, need no administrator password, and change no system settings. `./schedule.sh off` removes them. The one setting you change yourself, keeping the Mac awake, you can turn off again in System Settings.

## Updates

Only update Reader from the link you were originally given. If you use Claude Code, it can download the update, show you what changed in plain words before applying it, and keep your settings, key and briefs. Ask it: "Is there a newer version of Reader?"

## Removing Reader

1. Stop the schedule. In Terminal:
   ```bash
   cd ~/Reader
   ./schedule.sh off
   ```
2. In the Claude Console, **Settings → API keys**: delete Reader's key. If you made a Reader workspace, you can archive it too.
3. Drag the `~/Reader` folder to the Trash. That removes the program, its Python environment, your key file, the collected news and your briefs (keep a copy of `briefs/` first if you want them).
4. If you changed the sleep setting only for Reader, turn it back off in System Settings.

Python from python.org, if you installed it for Reader, can stay; it does no harm. The Claude app is uninstalled like any other app.

Next: [8. Troubleshooting](08-troubleshooting.md)
