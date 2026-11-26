# Claude Usage for Alfred

An [Alfred](https://www.alfredapp.com) workflow that shows your Claude Code and Codex plan limits, a 13-week activity heatmap, and what your usage would cost at API list prices, in an Alfred UI window.

> Unofficial. Not affiliated with or endorsed by Anthropic or OpenAI.

## Features

- **Limits:** how much of your 5-hour session and weekly limits you've used, and when each window resets
- **Activity:** a 13-week heatmap of your usage, with your current streak 🔥
- **Cost:** what the same tokens would cost at API list prices. This is an estimate; your plan is not billed this way. Hover a day to see its cost and request count.
- **Claude and Codex tabs:** the tab you viewed last opens next time

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

Claude Code reports plan limits only to its status line, and nothing else saves them. This workflow ships `statusline.py`, which prints a compact status line and saves the latest limits to `~/.claude/usage-limits.json`.

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
- **Codex folder:** defaults to `~/.codex`. Change it only if you use `CODEX_HOME`.

## Where the numbers come from

**Claude**

- Limits come from the status line (see above). They are as fresh as your last Claude Code message, so usage from claude.ai or the desktop app shows up the next time Claude Code talks to the API. Limits exist only on Pro, Max and Ultra plans.
- Activity and cost are read from Claude Code transcripts in `~/.claude/projects`, where every API response records its model and token counts. Requests are de-duplicated across resumed and forked sessions, and priced with input, output, cache-write (5-minute and 1-hour) and cache-read rates per model, including fast mode and web searches.

**Codex**

- Limits, activity and cost all come from Codex's session files in `~/.codex/sessions`. Each API response records its tokens, and the plan limits come with it. Limits are as of your last Codex request. Costs use OpenAI API rates.

## Privacy

- Everything runs locally. The workflow makes no network requests; ↩ just opens your usage settings page in the browser.
- From transcripts and session files it reads only timestamps, model names, token counts and request IDs, never message content.
- It writes only two things: `~/.claude/usage-limits.json` (from the status line script) and a cache of per-file totals in Alfred's workflow cache folder.

## Updating prices

Prices are hard-coded in the `PRICES` tables in `usage.py` (Claude) and `codex.py` (Codex), in USD per million tokens. When you change a price or how files are parsed, bump `CACHE_VERSION` in the same file so cached totals are recomputed.

## License

[MIT](LICENSE)
