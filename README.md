# Reader: an overnight markets brief

Reader goes through the overnight news on your Mac and writes a short brief for the New York morning: the stories that matter to markets, what happened in Asia and Europe while the U.S. slept, and the week's scheduled data releases. It reads about 60 publisher and official feeds. A separate AI model checks every factual sentence against its source, and every item links to the original publisher with its publication time.

It is built to say less rather than say something unsupported. On a quiet night the brief is short.

![How Reader works: feeds are collected overnight, screened, grouped into stories, checked against their sources, written up and audited before the brief is saved](docs/images/how-it-works.svg)

## Is it for you?

You need three things:

1. **A Mac that can stay on overnight**, plugged in and online. Reader checks the feeds every 30 minutes so nothing scrolls past before morning. Windows is not supported.
2. **An Anthropic API account with credit.** Reader pays Anthropic for the AI it uses: about **$1.50 to $3 a brief**, or roughly **$50 to $65 for a month of weekday briefs**. You can cap your spending.
3. **About an hour for setup**, the first time. You don't need to know how to code. Every step is written out, with pictures of what you should see.

## Two ways to set it up

| | **With Claude Code** (recommended) | **In Terminal, by yourself** |
|---|---|---|
| How it works | Claude, Anthropic's coding assistant, runs the setup with you in plain conversation and explains each step | You type a short series of commands, following the guide |
| You need | A paid Claude plan (Pro or above) for the Claude app | Nothing extra |
| Guide | [Set up with Claude Code](docs/guide/03-setup-with-claude-code.md) | [Set up in Terminal](docs/guide/04-setup-in-terminal.md) |

Whichever you choose, start with the first two guides.

![The setup path: check your Mac, create an Anthropic account and key, get Reader, run setup, choose sources, write a first brief, then schedule it](docs/images/setup-roadmap.svg)

## The guides

| | Guide | Time |
|---|---|---|
| 1 | [Before you start](docs/guide/01-before-you-start.md): what you need, what it costs, where Reader should live | 5 min |
| 2 | [Your Anthropic API key](docs/guide/02-api-key.md): account, credit, a spending cap, the key | 15 min |
| 3 | [Set up with Claude Code](docs/guide/03-setup-with-claude-code.md) | 30 min |
| 4 | [Set up in Terminal](docs/guide/04-setup-in-terminal.md) (instead of 3) | 30 min |
| 5 | [Sources and their terms](docs/guide/05-sources-and-terms.md): what Reader reads, what publishers allow, and your choice | 10 min |
| 6 | [Every morning](docs/guide/06-every-morning.md): reading the brief, running it automatically | 10 min |
| 7 | [Security and privacy](docs/guide/07-security-and-privacy.md): your key, what leaves your Mac, how to remove Reader | 10 min |
| 8 | [Troubleshooting](docs/guide/08-troubleshooting.md) | as needed |
| 9 | [Make it yours](docs/guide/09-make-it-yours.md): your companies, your audience, the brief's length | as needed |

Also: [How it works](docs/how-it-works.md) · [Every command](docs/commands.md) · [Every source and its terms](docs/sources-table.md)

## Read this before you rely on a brief

- **It is for your own reading.** Reader reads publishers' feeds for one person. Don't publish, post or resell the briefs, and don't run Reader as a service for others. [Sources and their terms](docs/guide/05-sources-and-terms.md) explains why, and asks you to choose which sources Reader may read.
- **It can still be wrong.** Every line is checked against its source, and code enforces rules no model can talk its way around, but no checking is perfect. Before you act on anything, open the link.
- **It is not investment advice.** It reports what its sources reported.
- **It is independent.** Reader is not affiliated with Anthropic or with any publisher it reads.

## License

The code is released under the [MIT License](LICENSE): use it, change it and share it, keeping the copyright notice. The guides and illustrations are under [Creative Commons Attribution 4.0](LICENSE-docs.md). Publishers' content is theirs; this license covers none of it.

© 2026 Strat & Story
