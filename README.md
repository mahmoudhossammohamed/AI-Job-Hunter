# Job Hunter (free, local, no AI tokens)

A personal tool for Mahmoud. It finds jobs, scores them against your verified CV, and builds a tailored
CV (DOCX and PDF), an ATS-alignment report and a cover letter for each good match. You review and apply yourself.

**Cost: zero.** No paid API, no tokens. The core loop is plain Python. Gemini free tier is optional and off by default.

## What works today (v0.1)

| Part | Status |
|---|---|
| Verified master profile (`profile.json`) | Done. You must confirm it in the dashboard first |
| Discovery: Greenhouse and Lever public endpoints | Done, tested on mock data only (see Limits) |
| Discovery: alert emails (LinkedIn, Wuzzuf, Indeed, Bayt) in `storage/inbox` | Done |
| Add any job by hand (paste link and description) | Done |
| Deduplication across sources | Done |
| Scoring 0-100 with explanations, seniority and eligibility rules | Done |
| 6 CV variants, DOCX + PDF, ATS report, template cover letter | Done |
| Dashboard, status tracking, notes, audit log, backups | Done |
| Optional Gemini cover-letter draft | Done, untested against the live API |
| Auto-fill and submit forms (Playwright) | **Not built yet.** See CLAUDE.md stages 8 and 9 |

Nothing is ever sent to an employer by this version.

## Install (Windows, one time)

1. Double-click `setup.bat`. It creates `.venv`, installs the packages and prepares the database.
2. If it says Python is missing, install Python from python.org and tick **Add python.exe to PATH**.
   You use `py -m pip` on your machine because `pip` alone is not on your PATH. `setup.bat` already handles that.

## Daily use

1. Double-click `start.bat`. The dashboard opens in your browser. Close the black window to stop it.
2. First time only: open **Profile**, check every date, employer and skill against your real CV, then tick the confirmation box.
3. **Overview > Run search now**, or let Task Scheduler do it (below).
4. **Jobs**: sorted by score. Open one to see why it scored that way, what you are missing, then **Prepare CV and letter**.
5. Download the PDF, apply on the employer's site, then click **I applied (manually)** so it is tracked.

## Getting jobs in

**Greenhouse and Lever (automatic).** In **Settings**, add company tokens. Token = last part of the company's board URL
(`boards.greenhouse.io/<token>` or `jobs.lever.co/<slug>`). Only companies that use those systems appear.
Search Google for `site:boards.greenhouse.io cairo` or `site:jobs.lever.co egypt` to find some.

**Wuzzuf, LinkedIn, Indeed, Bayt (alert emails).** These sites are not scraped. Create a job alert on each site, then when
the email arrives, save it as `.eml` (or paste the text into a `.txt`) into `storage\inbox`. The next search picks it up.
Alert emails only contain a title and a link, so open the job in **Jobs** and paste the description to get a real score.

**Anything else.** **Add job** page.

## Run the search every day automatically

1. Press Win+R, type `taskschd.msc`, Enter.
2. **Create Basic Task**, name it Job Hunter, trigger **Daily**, pick a time your PC is on.
3. Action **Start a program**. Program: the full path to `run_search.bat`. **Start in**: the project folder.
4. Results are logged in `logs\search.log` and a database backup is made each run.

A search takes seconds per configured company (2 second polite delay each), so a list of 20 boards is under a minute. Zero tokens.

## How scoring works (so you can trust or change it)

Weights: skills 30, seniority 20, responsibilities 15, education 10, role relevance 10, location 10, other 5.
Bands: 85+ excellent, 70-84 good, 55-69 possible, below 55 archive. All editable in `config/scoring.json` and `config/settings.json`.

Hard rules that cap the score no matter what else matches:

- Senior, lead, principal, architect, manager title, or 4+ years asked: max 54.
- 3 years asked, or no description to verify: max 69.
- Less than half the required skills matched: max 69. Less than 90 percent matched: max 84 (never excellent).
- Remote job whose eligibility from Egypt is unknown: max 84. Remote job restricted to other countries: max 54.

Missing a nice-to-have skill never rejects a job. Required versus nice-to-have is detected line by line from headings like "Preferred" or "Nice to have".
This is a heuristic: always read the posting yourself.

Skill detection uses `config/skills.json`. If a posting uses a technology that is not in that file, it is invisible to the scorer. Add it there.

## What the CV tailoring does and does not do

It reorders your skill groups, picks which projects come first, and chooses one of six pre-written summaries.
It cannot invent anything: every line comes from `profile.json`, and a test checks that no skill is added or dropped and that dates are unchanged.
The ATS report is an estimate of keyword overlap, not the employer's real ATS.

## Gemini (optional, free)

Only for cover-letter drafts. Get a free key at aistudio.google.com, put it in `.env`, then enable it in **Settings**.
Only job text, your skills and project lines are sent, never phone, email or links (a test enforces it).
Google's free tier may use inputs for product improvement, which is why contact data is never included.
The model name is editable in Settings because Google renames models. If you see an HTTP 404, change it.

## Privacy

`profile.json`, `.env`, `storage/` and `logs/` are in `.gitignore`. Do not commit them. Everything runs on your PC.

## Limits you should know

- Greenhouse and Lever adapters were tested with realistic mock payloads, not live endpoints (the build environment blocked those hosts). Test one real token first.
- Wuzzuf has no public API and its rules were not verified, so there is no Wuzzuf scraper. Use alert emails.
- Two postings with the same company and title are treated as one job, even in different cities.
- Skills are matched by keyword, so a posting that describes a skill in other words will not match.

## Commands

```
.venv\Scripts\python -m pytest          run the 36 tests
.venv\Scripts\python -m jobhunter.search  one search from the command line
backup.bat                              copy the database to storage\backups
```
