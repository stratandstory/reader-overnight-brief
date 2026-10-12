# 1. Before you start

[← Back to the start](../../README.md) · Next: [2. Your Anthropic API key](02-api-key.md)

This page covers what Reader needs, what it costs to run, which Mac to run it on, and one decision to make before you download anything: where Reader will live.

## Checklist

- [ ] **A Mac running a current version of macOS.** Any recent Mac has ample headroom: Reader's AI runs on Anthropic's servers, so the Mac itself does little work (see [Reference configuration](#reference-configuration)). Windows is not supported; Reader's setup and scheduling are built on macOS's own tools.
- [ ] **A Mac that can stay awake and online through the week:** a desktop Mac or Mac mini, or a MacBook kept on its power adapter. See [Why collection runs continuously](#why-collection-runs-continuously).
- [ ] **About 1 GB of free disk space.** Reader itself is small. Its private copy of Python takes about 50 MB, and the news it stores grows by about 2 MB a day.
- [ ] **An Anthropic API account with credit.** [Guide 2](02-api-key.md) walks you through it. This is separate from a Claude subscription; see [Two Anthropic accounts](#two-anthropic-accounts).
- [ ] **Python 3.11 or newer.** The setup guides tell you how to check, and how to install it from python.org if you need to. It's free.
- [ ] **For the Claude Code route only:** a paid Claude plan (Pro or above) and the Claude app for Mac.
- [ ] **About an hour**, the first time.

## Reference configuration

Reader was developed, and runs, on a MacBook Air (Apple M2, 16 GB memory), macOS 15 Sequoia, Python 3.14. On that Mac:

| | |
|---|---|
| A collection pass (every 30 minutes) | about 35 seconds, mostly waiting on the network; 2 seconds of CPU; 65 MB of memory |
| A brief's local work (measured with `./brief dry-run`, which does everything except the model calls) | about 110 MB of memory at its peak |
| A full brief | 5 to 10 minutes, nearly all of it waiting for the models |
| Disk | about 50 MB for Reader's Python environment; stored news grows by 1.5 to 2 MB a day |

Any Mac that runs a current macOS handles this comfortably. What matters is that the Mac stays awake, not how fast it is.

## What it costs

Reader uses Anthropic's AI models for the reading, checking and writing, and Anthropic charges for each use. You prepay credit in Anthropic's console and Reader draws on it.

| What | Cost |
|---|---|
| One brief on a weekday morning | about $2.50 to $3.50 |
| One brief on a weekend or a quiet morning | about $1.50 |
| A month of weekday briefs | about $55 to $75 |
| Collecting news, checking your setup, a cost estimate (`./brief dry-run`) | free |
| The most a single brief can cost | $4, Reader's own ceiling (you can change it) |

These figures come from real runs in September and October 2026 with Reader's standard models. If you choose to read fewer sources ([guide 5](05-sources-and-terms.md)), there is less to read and a brief usually costs less; that hasn't been measured.

You can also set a **monthly spending limit** in Anthropic's console, so a mistake can never cost more than you decide. [Guide 2](02-api-key.md) shows how. We recommend it.

The Claude app plan, if you use the Claude Code route, is priced separately; see [claude.com/pricing](https://claude.com/pricing).

## Two Anthropic accounts

People often mix these up:

| | **Claude plan** (Pro, Max) | **Anthropic API account** (Claude Console) |
|---|---|---|
| What it is | A subscription for the Claude app, including Claude Code | Prepaid credit that programs spend through an API key |
| Who uses it | You, chatting with Claude | Reader, every morning |
| Where | claude.ai | platform.claude.com |
| Needed for Reader? | Only for the Claude Code setup route | Yes, always |

A Claude subscription does not pay for Reader's briefs. The briefs are paid from the API account's credit.

## Why collection runs continuously

Reader runs as scheduled background jobs on your Mac: it checks every source every 30 minutes and, if you choose, writes the brief at 6:30 AM New York time on weekdays. Many news feeds list only their latest 20 or so headlines, and a busy feed can turn over completely in an hour, so a single check at 6:30 AM would miss most of what was published. Checking every 30 minutes keeps everything.

The brief covers the previous trading day from that morning's brief to the 4 PM close, then the night to 6:30 AM. So on weekdays collection matters around the clock, and over the weekend it carries Friday's close through to Monday morning.

### Choosing the Mac

- **A desktop Mac or Mac mini** is the natural host: leave it running. [Guide 6](06-every-morning.md#keep-the-mac-awake) shows the one setting that stops it sleeping when the display turns off. The display itself can sleep.
- **A MacBook** works when it stays on its power adapter with the lid open (a closed lid puts it to sleep unless an external display is connected), with the same setting.
- **If the Mac sleeps,** Reader detects the checks it missed and lists them in the run report. The brief still runs on what was collected; you can see what might be missing.
- **Running by hand only** is possible too: skip the schedule and run Reader in the morning. The brief will be thinner, because it sees only what the feeds still list at that moment.

## Where Reader should live

Put the Reader folder directly in your **home folder** (the one with the house icon in Finder, named after you). The guides assume it is at:

```
~/Reader
```

(`~` is shorthand for your home folder.)

**Not** in Desktop, Documents or Downloads. Two reasons:

1. macOS protects those folders from background programs, and Reader's collector is a background program. It may be blocked without telling you.
2. If iCloud Drive syncs your Desktop and Documents (a common setting), it can move Reader's files to the cloud to save space, and the scheduled jobs fail when they can't find them.

## What Reader is not

- **Not a news service.** It's a program you run for yourself, on your own Mac, with your own accounts.
- **Not investment advice.** The brief states what its sources reported, with links. It adds no opinion unless you turn on the optional "Why it matters" line ([guide 9](09-make-it-yours.md)), which is then labelled as the editor's.
- **Not infallible.** Every factual line is checked against its source, and the checking is strict, but it is done by software. Open the link before you act on anything.

Next: [2. Your Anthropic API key](02-api-key.md)
