# 8. Troubleshooting

[← 7. Security and privacy](07-security-and-privacy.md) · Next: [9. Make it yours](09-make-it-yours.md)

Find the message you saw, or the symptom. If you use Claude Code, you can also paste the message (never your key) and ask what it means, or type `/reader-checkup` for a full health check.

Two commands answer most questions, and both are free:

```bash
./brief doctor      # is the key working, can it reach every model, which sources are chosen
./brief sources     # did each source answer at the last check
```

## Terminal and setup

**`no such file or directory: ./brief`** (or `./setup.sh`)
Terminal isn't in the Reader folder. Run `cd ~/Reader` and try again. If that fails too, the folder isn't in your home folder or isn't named `Reader`; see [guide 3, step 3](03-setup-with-claude-code.md#step-3-put-reader-in-your-home-folder).

**`permission denied: ./brief`**
The download lost the "this is a program" mark on Reader's scripts. Restore it:
```bash
chmod +x brief *.sh
```

**`Python 3.11 or newer is required`**
Install Python from [python.org/downloads](https://www.python.org/downloads/), quit and reopen Terminal, then run `./setup.sh` again.

**A window offers to install "command line developer tools"**
macOS offers this when a program looks for its own older Python. You don't need it for Reader: click **Cancel**, install Python from python.org, and run `./setup.sh` again.

**`First-time setup needed. Run: ./setup.sh`**
Reader's Python environment isn't built yet. Run `./setup.sh`.

**macOS says a script "cannot be opened" or is from an unidentified developer**
That warning is meant for downloaded apps. Reader's scripts are run from Terminal, which normally avoids it. If it appears anyway, this clears the download flag on the Reader folder:
```bash
xattr -dr com.apple.quarantine ~/Reader
```

## The key

**`No Anthropic API key found. Run ./set-api-key.sh first.`**
Save your key: `./set-api-key.sh` ([guide 4, step 4](04-setup-in-terminal.md#step-4-save-your-api-key)).

**`That doesn't look like an Anthropic API key`** or **`The clipboard does not hold an Anthropic API key`**
What was pasted or copied doesn't start with `sk-ant-`. Copy the key again from the console. If you've closed the page that showed it, create a new key ([guide 2, step 5](02-api-key.md#step-5-create-the-key)).

**`The API key was rejected.`**
The key was mistyped, disabled, deleted or has expired. In the console's **Settings → API keys**, check its status. Create a new one if needed and save it with `./set-api-key.sh`.

### The key works across workspaces

**`This API key works across workspaces, so Reader needs to know which workspace to use.`**
Your key isn't tied to one workspace. Either create a new key for a single workspace ([guide 2, step 5](02-api-key.md#step-5-create-the-key)), or tell Reader which workspace to use: in the console's **Settings → Workspaces**, copy the ID of the workspace (it starts with `wrkspc_`), then run `./set-workspace.sh` and paste it.

**`-- claude-fable-5-1 not available to this key`** (or another model)
`./brief doctor` lists each model Reader uses. If one is unavailable:
- Fable 5.1 needs the account's standard 30-day data retention. A personal account has it unless you arranged otherwise; an account through an employer may not. Use a personal account, or ask your account's administrator.
- If a model has been retired since Reader was written, its stage needs a new model in `config/settings.toml`. Ask Claude Code, or whoever gave you Reader. Don't simply swap in a cheaper model for the checking stages: they are what make the brief trustworthy.

## Running a brief

**`Reader has not been told which sources it may read on this Mac, so it has fetched nothing.`**
Choose your sources: `./brief choose-sources` ([guide 5](05-sources-and-terms.md)).

**`Stopped: API error … credit balance is too low`**
Add credit in the console (**Settings → Billing**).

**`Stopped: API error … You have reached your specified API usage limits`**
Your own monthly spending limit has been reached. Raise it in **Settings → Billing → Spend limits** (or the workspace's **Spend limits** tab), or wait for the new month.

**`Stopped: Rate limited during the … stage; try again in a few minutes.`**
Your account hit Anthropic's per-minute limit. New accounts start with lower limits that rise as you use the API. Wait a few minutes and run again. If it happens every time, check **Rate limits** in the console.

**`Stopped: … would exceed the $4.00 run budget`**
Reader's own per-brief ceiling. It's rare; a very busy news night can approach it. Run again later, or raise `max_run_usd` in `config/settings.toml`.

**`Nothing in the window to brief.`**
No news was collected for the period the brief covers. Run `./brief collect`, check `./brief sources`, then run again.

**Many sources say `robots.txt disallows or is unreachable`, or every source fails**
Reader couldn't reach the internet properly: no connection, a VPN or firewall blocking it, or a captive Wi-Fi page (hotel, airport). Check you can open a website in your browser, then run `./brief collect` again. If every source fails with a certificate or SSL error, run `./setup.sh` again to reinstall Reader's packages.

**One or two sources `unavailable`**
Normal: sites have bad moments. Reader skips them and tries again next time, and the brief's footer names any it couldn't reach. A source that fails every time for days may have moved its feed; tell whoever gave you Reader.

**`possible gap` in the collector log or the run report**
A feed published more headlines between two checks than it shows at once, so some may have been missed. After the Mac has been asleep this is expected. If one feed shows gaps on ordinary nights, it needs a fuller source.

## The schedule

**The 6:30 brief didn't appear**
1. `./schedule.sh status`: is the brief job on? `./schedule.sh collect` doesn't write briefs; `./schedule.sh on` does.
2. Was the Mac asleep? A job that was due runs when the Mac wakes, so the brief may simply be late.
3. The job's log is `~/Reader/data/com.reader.brief.log`, and each run's report is in `data/runs/`.
4. No briefs on weekends: the automatic brief runs Monday to Friday.

**No notification when the brief is ready**
Notifications come from macOS's script runner. In **System Settings → Notifications**, look for **Script Editor** and allow its notifications.

**The collector stopped**
`./schedule.sh status` shows the last collection. If it's hours old while the Mac was awake, run `./schedule.sh collect` (or `on`) again to reinstall the jobs. If you moved or renamed the Reader folder, that's the cause: the jobs point to the old location.

## Still stuck

- Every run's report (`data/runs/<date-time>/report.md`) records the stage, the error and the cost so far.
- With Claude Code: type `/reader-checkup`, or describe what happened.
- Otherwise, send whoever gave you Reader the message you saw and the last part of the run report. Never send `.env` or your key.

Next: [9. Make it yours](09-make-it-yours.md)
