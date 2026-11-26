# Claude Usage for Alfred

An [Alfred](https://www.alfredapp.com) workflow that shows your Claude Code and Codex plan limits, a 13-week activity heatmap, and what your usage would cost at API list prices, in an Alfred UI window.

> Unofficial. Not affiliated with or endorsed by Anthropic or OpenAI.

## Features

- **Limits:** usage and reset times for the windows your account reports, including weekly-only accounts
- **Activity:** a 13-week heatmap of your usage, with your current streak 🔥
- **Cost:** what the same tokens would cost at API list prices. This is an estimate; your plan is not billed this way. Hover a day to see its cost and request count.
- **Period totals:** request count and estimated cost for this week, this month and an optional subscription cycle. A + marks a subtotal with unpriced requests.
- **Claude and Codex tabs:** switch immediately while usage loads in the background. Reopen the last tab, choose a fixed order or show just one provider

## Requirements

- macOS with Alfred and the Powerpack
- `/usr/bin/python3`, which ships with the Command Line Tools (`xcode-select --install`)
- Optional: `zstd` (`brew install zstd`) to count compressed Codex sessions

## Install

Clone this repository into Alfred's workflows folder:

```sh
cd ~/"Library/Application Support/Alfred/Alfred.alfredpreferences/workflows"
git clone <this repository's URL> claude-code-usage
```

If you sync your Alfred preferences, use the `workflows` folder inside your synced `Alfred.alfredpreferences` instead.

Or build a package and double-click it to import:

```sh
git archive --format=zip -o Claude-Usage.alfredworkflow HEAD
```

### Set up the status line (Claude limits)

The workflow reads Claude plan limits from the status line cache by default. This workflow ships `statusline.py`, which prints a compact status line and saves the latest limits to `~/.claude/usage-limits.json`.

```sh
cp statusline.py ~/.claude/statusline-usage.py
```

Then add this to `~/.claude/settings.json`:

```json
"statusLine": {"type": "command", "command": "/usr/bin/python3 ~/.claude/statusline-usage.py"}
```

To keep a status line you already have, pass its command in `CLAUDE_USAGE_STATUSLINE_CMD`. The script still saves your limits, then hands the same input to your command and prints its output:

```json
"statusLine": {"type": "command", "command": "CLAUDE_USAGE_STATUSLINE_CMD='~/.claude/my-statusline.sh' /usr/bin/python3 ~/.claude/statusline-usage.py"}
```

Codex needs no setup.

## Usage

| Action | What it does |
| --- | --- |
| `usage` | Open the window (the keyword can be changed in the workflow's configuration) |
| `usage claude` / `usage codex` | Open on that tab |
| ⌘1 / ⌘2 or ⇥ | Switch tabs |
| ↩ | Open the usage settings page on claude.ai or chatgpt.com |
| ⌘R | Refresh (the window also refreshes every 30 seconds while open) |

You can also set a hotkey on the workflow's Hotkey trigger, or open the window with the External Trigger `show`.

## Configuration

Open the workflow in Alfred and click **Configure Workflow**:

- **Keyword:** defaults to `usage`
- **Claude config folder:** defaults to `~/.claude`. Change it only if you use `CLAUDE_CONFIG_DIR`.
- **Show providers:** defaults to both providers with the last viewed tab selected. Choose a fixed first tab or enable one provider. A keyword argument selects an enabled tab for that launch.
- **Subscription dates:** enter each provider’s start and renewal dates as YYYY-MM-DD. The renewal date belongs to the next cycle.
- **Live account limits:** optionally query the signed-in Codex and Claude Code CLIs for quota data. If a CLI is unavailable or cannot report limits, the workflow uses local data.
- **Codex folder:** defaults to `~/.codex`. Change it only if you use `CODEX_HOME`.

## Where the numbers come from

**Claude**

- Limits come from the status line (see above). They are as fresh as your last Claude Code message, so usage from claude.ai or the desktop app shows up the next time Claude Code talks to the API. Limits exist only on Pro, Max and Ultra plans.
- Activity and cost are read from Claude Code transcripts in `~/.claude/projects`, where every API response records its model and token counts. Requests are de-duplicated across resumed and forked sessions, and priced with input, output, cache-write (5-minute and 1-hour) and cache-read rates per model, including fast mode and web searches.

**Codex**

- Limits, activity and cost are read by default from Codex’s `sessions` and `archived_sessions` folders. Each API response records its tokens, and the plan limits come with it. Limits are as of your last Codex request. Costs use OpenAI API rates.

## Privacy

- The default configuration reads local files. Enabling **Live account limits** lets the installed CLIs contact their providers to check your quota. Pressing ↩ opens the selected provider’s usage settings in your browser.
- From transcripts and session files it reads only timestamps, model names, token counts and request IDs, never message content.
- Usage data is written to `~/.claude/usage-limits.json` (from the status line script) and a cache of per-file totals in Alfred's workflow cache folder.

## Updating prices

Prices are hard-coded in the `PRICES` tables in `usage.py` (Claude) and `codex.py` (Codex), in USD per million tokens. When you change a price or how files are parsed, bump `CACHE_VERSION` in the same file so cached totals are recomputed.

## License

[MIT](LICENSE)
