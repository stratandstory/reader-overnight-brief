---
name: setup-reader
description: Set Reader up on this Mac from scratch, step by step, for someone new to Terminal and code. Use when the person types /setup-reader, asks to be set up, or asks how to get Reader running.
---

# Set up Reader

Walk the person from a downloaded Reader folder to a working brief. Follow the ground rules in `CLAUDE.md` throughout, above all: **the API key never enters the conversation, and nothing that costs money runs without a clear yes.**

Go one step at a time. Before each step, say what it does and whether it costs anything; after it, say in a sentence what happened. When a check shows a step is already done, say so and move on. If a step fails, use `docs/guide/08-troubleshooting.md`, fix what you can, and explain what the person needs to do.

## 0. Say what's ahead

In a few lines: about nine steps, about 30 minutes. Only the first brief costs money, about $1.50 to $3.50, and you'll ask before it. They'll need the Claude Console open in their browser with credit added (`docs/guide/02-api-key.md`); if they haven't done that yet, you'll walk them through it when you get there. Ask whether they're ready.

## 1. The folder and the Mac

- Run `pwd`. Reader should be directly in the home folder (`$HOME/Reader`). If it's inside Desktop, Documents, Downloads, iCloud Drive or another synced folder, explain why that breaks the overnight schedule (`docs/guide/01-before-you-start.md`, "Where Reader should live"), and ask them to move it into their home folder in Finder, then start a new Claude Code session in the moved folder. Don't move it yourself: this session would lose its folder.
- Run `sw_vers -productVersion` and mention the macOS version. Any Mac running a current macOS has ample headroom (`docs/guide/01-before-you-start.md`, "Reference configuration"). Ask whether it's a desktop Mac or a MacBook: a MacBook needs to stay on power with the lid open for the schedule to keep collecting, which matters in step 9.
- Run `ls -l brief setup.sh schedule.sh set-api-key.sh`. If any lacks the `x` permission, run `chmod +x brief *.sh` and say why (the download dropped the "this is a program" mark).

## 2. Python

Look for Python 3.11 or newer without triggering macOS's offer to install developer tools (don't run a bare `python3`):

```bash
for c in python3.14 python3.13 python3.12 python3.11; do command -v "$c"; done
```

If nothing is found, they need Python from python.org. Guide them: go to https://www.python.org/downloads/, download the latest Python 3 for macOS, open the installer and click through (Continue, Agree, Install); it asks for their Mac password. Wait until they say it's done, then check again.

## 3. Reader's Python environment

Run `./setup.sh` (free, about a minute). It builds a private Python environment in `.venv` and installs three packages; it changes nothing else on the Mac. Success ends with "Setup complete".

## 4. The API key

First see whether a key is already saved, without reading it: `test -f .env && echo saved || echo missing`. If it's saved, go to step 5; if step 5 then shows the key failing, come back here.

Otherwise:

1. Ask whether they've created an API key in the Claude Console. If not, walk them through `docs/guide/02-api-key.md` one step at a time: account, credit ($25 is a sensible start), a monthly spend limit (recommended, $75 covers a month of weekday briefs), optionally a Reader workspace, then **Settings → API keys → Create key**, with a long expiration (or Never), linked to themselves, and scoped to one workspace if the form offers it.
2. Tell them, in these words or close to them: "Click **Copy** next to your key in the console, then come back and tell me you've copied it. Please don't paste it here; I don't need to see it."
3. When they say they've copied it, run `./set-api-key.sh --clipboard`. It saves the key to `.env` (readable only by their Mac user), clears the clipboard, and runs `./brief doctor`. The key is never printed.
4. If it says the clipboard doesn't hold a key, ask them to click Copy again and retry. If the key page has closed, they create a new key; the old one can be deleted.
5. If they paste a key into the chat: don't use it. Tell them it should be treated as exposed, help them disable it in the console (**Settings → API keys → Disable**) and create a new one, then repeat from 2.

## 5. Check the key

Run `./brief doctor` (free). Success: a line for each model starting `ok`, then "API key works and all configured models are available."

- **"works across workspaces":** either they create a single-workspace key (repeat step 4), or they find the workspace ID in **Settings → Workspaces** (it starts `wrkspc_`; it's an identifier, not a secret, so they may paste it here) and you run `printf '%s\n' 'wrkspc_…' | ./set-workspace.sh`.
- **A model "not available to this key":** see `docs/guide/08-troubleshooting.md` ("not available to this key"). Don't swap a cheaper model into the check or audit stage to get past it; say so if they ask.
- **"rejected":** the key was mistyped, disabled, deleted or expired; repeat step 4 with a new key.

## 6. Which sources Reader may read

This is their decision. Explain it neutrally, in a few short paragraphs, from `docs/guide/05-sources-and-terms.md`:

- how Reader reads (publishers' own feeds, robots.txt obeyed, an honest name, every 30 minutes, headlines and summaries only for journalism, links back, nothing republished);
- that most of the major financial press have terms restricting automated access or AI use, some naming AI use outright;
- the three choices, with what each brief is like. Run `./brief choose-sources` to show the real counts and publishers;
- the case for `all` (one person's brief, made this way, is personal use) and the case against (several terms bar AI use or automated access in so many words), as the guide puts them. Which weighs more is their judgment; this is not legal advice. They choose, and can change it any time.

Ask which they want. Then run `./brief choose-sources <official|unrestricted|all>` and confirm what was saved.

## 7. Collect the news

Run `./brief collect` (free, about a minute), then `./brief sources`. Summarise: how many sources answered, any that didn't (one or two is normal), how many items were stored.

## 8. The first brief

1. Run `./brief dry-run` (free) and tell them the projected cost.
2. Ask plainly: "Shall I write your first brief? It will cost about $X from your Anthropic credit and take 5 to 10 minutes." Go ahead only on a clear yes.
3. Run `./brief run` in the background. When it finishes, report the brief's file name, the number of stories, claims checked and passed, and the exact cost. If it stopped, say at which stage and why, from the output or the run report.
4. Run `./brief open`, and offer to walk them through how to read it (`docs/guide/06-every-morning.md`, "Reading the brief").

## 9. Running on a schedule (optional)

Explain the choice (`docs/guide/06-every-morning.md`, "Run it automatically"):

- `./schedule.sh collect`: collects every 30 minutes and saves each weekday morning's news at 6:30 AM; they run the brief when they want one. Free.
- `./schedule.sh on`: the same, plus the brief at 6:30 AM on weekdays with a notification. About $55 to $75 a month: needs a clear yes.
- Neither: they run `./brief run` by hand. The brief is thinner, because feeds only show their latest items.

Run the one they choose, then `./schedule.sh status`. Then guide them through keeping the Mac awake (`docs/guide/06-every-morning.md`, "Keep the Mac awake"): System Settings, search "sleep", turn on the option that prevents automatic sleeping when the display is off; on a MacBook it's under Battery → Options and needs the power adapter and an open lid. They make this change, not you. You may check the result read-only with `pmset -g | grep -E '^ *sleep'` (0 means the Mac won't sleep on its own).

## Finish

Summarise in a short list what is now set up: Python environment, key (working), sources choice, first brief (cost), schedule (which mode) and the sleep setting. Then the daily routine in two lines (`./brief run` and `./brief open`, or the 6:30 notification), and where to go next: `/reader-checkup` for a health check, `docs/guide/` for everything else.
