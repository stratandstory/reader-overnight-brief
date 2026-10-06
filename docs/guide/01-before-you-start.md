# 1. Before you start

[← Back to the start](../../README.md) · Next: [2. Your Anthropic API key](02-api-key.md)

This page covers what you need, what Reader costs to run, and one decision to make before you download anything: where Reader will live on your Mac.

## Checklist

- [ ] **A Mac** with a recent version of macOS. Reader was built and tested on macOS 15 (Sequoia). Apple silicon and Intel Macs both work. Windows is not supported: Reader's setup and scheduling are written for macOS.
- [ ] **The Mac can stay on overnight**, plugged in, awake and online, at least on the nights before the mornings you want a brief. See [Why the Mac stays on](#why-the-mac-stays-on) below.
- [ ] **About 1 GB of free disk space.** Reader itself is small. Its private copy of Python takes about 50 MB, and the news it stores grows by about 2 MB a day.
- [ ] **An Anthropic API account with credit.** [Guide 2](02-api-key.md) walks you through it. This is separate from a Claude subscription; see [Two Anthropic accounts](#two-anthropic-accounts).
- [ ] **Python 3.11 or newer.** The setup guides tell you how to check, and how to install it from python.org if you need to. It's free.
- [ ] **For the Claude Code route only:** a paid Claude plan (Pro or above) and the Claude app for Mac.
- [ ] **About an hour**, the first time.

## What it costs

Reader uses Anthropic's AI models for the reading, checking and writing, and Anthropic charges for each use. You prepay credit in Anthropic's console and Reader draws on it.

| What | Cost |
|---|---|
| One brief on a weekday morning | about $2.25 to $3 |
| One brief on a weekend or a quiet morning | about $1.50 |
| A month of weekday briefs | about $50 to $65 |
| Collecting news overnight, checking your setup, a cost estimate (`./brief dry-run`) | free |
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

## Why the Mac stays on

Many news feeds show only their latest 20 or so headlines. On a busy night a feed can turn over completely in an hour, so a single check at 6:30 AM would miss most of the night. Reader checks every feed every 30 minutes through the night and keeps what it finds.

- **A desktop Mac** (iMac, Mac mini, Mac Studio): leave it on. [Guide 6](06-every-morning.md#keep-the-mac-awake-overnight) shows the one setting that stops it sleeping.
- **A laptop:** it must be plugged in, and the lid must stay open (a closed lid puts it to sleep unless it's connected to an external display). Same setting.
- **If the Mac sleeps anyway,** Reader still writes the brief when you run it, from whatever it collected. Gaps are listed in the run report, so you can see what might be missing.

You can also skip the overnight schedule and run Reader by hand in the morning. The brief will be thinner, because it only sees what the feeds still show at that moment.

## Where Reader should live

Put the Reader folder directly in your **home folder** (the one with the house icon in Finder, named after you). The guides assume it is at:

```
~/Reader
```

(`~` is shorthand for your home folder.)

**Not** in Desktop, Documents or Downloads. Two reasons:

1. macOS protects those folders from background programs, and Reader's overnight collector is a background program. It may be blocked without telling you.
2. If iCloud Drive syncs your Desktop and Documents (a common setting), it can move Reader's files to the cloud to save space, and the overnight job fails when it can't find them.

## What Reader is not

- **Not a news service.** It's a program you run for yourself, on your own Mac, with your own accounts.
- **Not investment advice.** The brief states what its sources reported, with links. It adds no opinion unless you turn on the optional "Why it matters" line ([guide 9](09-make-it-yours.md)), which is then labelled as the editor's.
- **Not infallible.** Every factual line is checked against its source, and the checking is strict, but it is done by software. Open the link before you act on anything.

Next: [2. Your Anthropic API key](02-api-key.md)
