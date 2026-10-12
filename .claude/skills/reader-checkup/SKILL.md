---
name: reader-checkup
description: Health check for Reader on this Mac (key, models, sources, schedule, last run, calendar, sleep setting), reported in plain words with what to do about anything wrong. Use when the person types /reader-checkup, or asks whether Reader is working, why a brief didn't arrive, or what went wrong.
---

# Reader checkup

Every check here is free and read-only. Follow `CLAUDE.md`: never read `.env`, never run anything that costs money.

Run the checks, then report. Lead each line with the verdict (working, not working, or needs attention), then one sentence on what it means and what to do. Keep it short. If everything works, say so in a line or two.

## Checks

1. **Python environment:** `test -x .venv/bin/python && echo ok || echo missing`. Missing: run `./setup.sh` (free).
2. **Key and models:** `./brief doctor`. It also prints the sources choice.
3. **Sources:** `./brief sources`. Note any source unavailable at the last check, and how long ago that check was. Several unavailable at once usually means the connection; one failing for days means the feed has a problem.
4. **Schedule:** `./schedule.sh status`. If the last collection is more than an hour old while the schedule is on, the Mac was probably asleep, or the folder has moved since the schedule was set up (fix: run `./schedule.sh collect` or `./schedule.sh on` again from this folder).
5. **Last run:** find the newest folder in `data/runs/` (`ls -t data/runs | head -3`) and read the top of its `report.md`: the funnel, the cost table and any "Run stopped" note. Say whether it produced a brief, what it cost, and, if it stopped, why.
6. **Calendar:** read the last date in `config/calendar.toml`. If it's within 30 days of today or already past, say the data-release calendar needs next year's dates (`docs/guide/09-make-it-yours.md`, "The release calendar").
7. **Sleep:** `pmset -g | grep -E '^ *sleep'`. If the schedule is on and the Mac sleeps after some minutes, point them to `docs/guide/06-every-morning.md`, "Keep the Mac awake". They change the setting themselves.
8. **Disk:** `du -sh data briefs`. Mention it only if `data` is over 2 GB.

## If the person described a specific problem

Start with the check that matches it, then look up the message in `docs/guide/08-troubleshooting.md`. Fix what's free and inside the Reader folder after saying what you'll do. For anything that costs money, changes the schedule, or involves their key or System Settings, explain and let them decide.
