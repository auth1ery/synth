# synth.

A fullscreen, keyboard and mouse driven todo list for your terminal, built for the fish shell.
One Python file, no dependencies (stdlib curses). Needs Python 3.8+, and 3.11+ for `config.toml`!

## Install

Clone the repo, cd into the folder and run:

```fish
./install.fish
```

Alternatively, run
```fish
curl -fsSL https://auth1ery.github.io/synth/install.fish | fish
```

Open a new fish session and run `synth`. Also available:

| Shortcut | What |
| --- | --- |
| `st` | abbreviation that expands to `synth` |
| `alt-t` | opens synth from the prompt, returns to your command line on quit |
| `synth_count` | prints the number of open tasks |
| `synth_due` | prints the number due today or overdue (handy in a prompt or greeting) |
| `synth_tracking` | prints the running timer, for example `12:04 write docs`, or nothing |
| `synth_habits` | prints habits done today, for example `3/5` |

Change or disable them before fish loads them, for example in `config.fish`:

```fish
set -g synth_bind \ct   # use ctrl-t
set -g synth_bind ''    # no key binding
set -g synth_abbr todo  # abbreviation name, '' disables
```

Remove with `./install.fish --uninstall` (your todos and config stay).

## Using it

Everything happens inside the fullscreen UI. Press `?` for the full, live key list.

- Left: views (All, Today, Upcoming, Inbox, Done), your custom views, projects and tags with counts.
- Middle: the task list with subtasks, priorities, due dates, tags and projects.
- Right (or bottom): details and notes for the selected task.

### Quick add syntax

```
buy milk #errands @home !2 due:fri every:1w
```

| Token | Meaning |
| --- | --- |
| `#tag` | tag (as many as you like) |
| `@project` | project |
| `!1` `!2` `!3` or `!low` `!med` `!high` | priority |
| `due:DATE` or `^DATE` | due date: `today tom fri +3d +2w 12-25 2026-12-25 eow eom none` |
| `every:N[dwmy]` or `~1w` | repeat, also `daily weekly monthly yearly` |
| `est:90m` or `est:1h30m` | time estimate (a bare number is minutes) |

The same syntax is used to edit a task. A live preview shows what was understood.
Completing a repeating task moves its due date forward instead of closing it.

### Filter syntax (`/`)

`#tag`, `@project`, `!2` (exact), `!2+` (at least), `due:today|overdue|now|week|any|none|DATE`,
`is:done`, `is:open`, `is:blocked`, `is:ready`, `is:snoozed`, `has:notes`, `has:repeat`, `has:deps`, `has:est`, `-` in front negates, plain words match title and notes.
Custom views in the sidebar use the same syntax.

### Default keys

| Key | Action | Key | Action |
| --- | --- | --- | --- |
| `j` `k` / arrows | move | `a` / `A` | add / add at top |
| `g` `G` | top / bottom | `c` | add subtask |
| `x` `space` | toggle done | `e` `enter` | edit with quick-add syntax |
| `E` | write notes (built-in editor) | `d` | delete |
| `p` `P` | priority up / down | `t` | due date |
| `#` | add or remove tags | `@` | project |
| `r` | repeat | `J` `K` | move task down / up |
| `z` `h` `l` | fold / collapse / expand | `v` `V` | select / select all |
| `/` | filter | `esc` | clear filter or selection |
| `s` | cycle sort | `u` `ctrl-r` | undo / redo |
| `tab` | focus sidebar or list | `[` `]` | previous / next view |
| `b` `i` | toggle sidebar / detail | `H` | hide done |
| `T` | theme picker with live preview | `:` | command palette |
| `X` | delete all done | `q` | quit |
| `ctrl-p` | fuzzy find tasks, projects, tags, views | `w` | start or stop time tracking |
| `f` | focus mode | `S` | stats |
| `C` | calendar (then `v` for agenda) | `L` | links and backlinks menu |
| `&` | link this task to another | `ctrl-o` | go back after a jump |
| `n` | quick timestamped note | `ctrl-e` `ctrl-y` | scroll the detail pane |
| `D` | daily journal | `Y` | habit tracker |
| `O` | projects and goals | `B` | dependencies |
| `Z` | snooze | `N` | new from template |
| `=` | custom actions and templates | `I` | switch detail tab (notes, info, links, history) |
| `y` | copy task text | `alt-y` | duplicate task with subtasks |
| `,` | settings panel | `W` | what changed (timeline of edits) |
| `R` | weekly review | `ctrl-g` | git menu (TODOs, branches, commits, GitHub, data sync) |
| `.` | what now? | `m` | dependency graph (map) |
| `M` | bulk edit the selection | `Q` | brain dump |
| `ctrl-t` | time travel through data history | `ctrl-k` | IRC chat (`:irc`) |

Bulk actions (done, delete, priority, due, tags, project, repeat) apply to all selected tasks.
Mouse: click selects, click the checkbox toggles, double click edits, wheel scrolls, click a view in the sidebar.

### Command palette (`:`)

`theme NAME`, `sort KEY`, `view NAME`, `filter QUERY`, `add TEXT`, `export [FILE]` (markdown),
`clear`, `reload`, `config` (opens the config in `$EDITOR`), `set OPTION VALUE`, `stats`, `calendar`, `agenda`,
`focus`, `track`, `find`, `links`, `journal`, `habits`, `projects`, `goals`, `note TEXT`, `snooze`, `deps`, `template`, `run NAME`, `help`, `quit`.
`set` changes are remembered between runs.

## Notes (so future you understands)

The detail pane is split into tabs so it stays calm: a compact header (title and chips), then `notes`, `info` or `links`
(click a tab or press `I`). Choose which tabs exist with `detail_sections`. You can also add a note while capturing a task:
`call dentist // ask about the invoice from March`.

Every task has notes. Press `E` to open the built-in editor: soft wrapping, bullet continuation, `ctrl-t` inserts a
timestamp, `ctrl-s` (or `ctrl-d`) saves, `esc` cancels. Press `n` for a one line note that is appended with a
timestamp, which is perfect for "tried X, did not work" trails. Notes sit right under the task info in the detail pane,
scroll with `ctrl-e` and `ctrl-y`, and `[[links]]` work inside them. `notes_inline = true` shows the first note line
in the list. Prefer `$EDITOR`? Set `notes_editor = "external"`.

## Daily journal (`D`)
One entry per day, searchable and linked to your work. A new entry starts from `journal_template` (default has Done,
Notes and Tomorrow sections already filled with what you finished that day). `h` `l` change day, `H` `L` jump between
entries, `e` writes, `n` appends a timestamped line, `g` goes to a date, `/` searches every entry, `d` deletes.
Each day shows what you completed, time tracked and habits hit. The header shows your journaling streak.

## Habits (`Y`)
Recurring habits that do not belong in a todo list. Add with the same quick syntax everywhere:
`read 3/week`, `run mon,wed,fri`, `water x8`, `stretch weekdays`. Each row shows the last two weeks, current and best
streak, a 30 day rate and weekly progress. `h` `l` pick a day (fix yesterday), `space` logs it, counted habits tick up
until the target. Archive with `z`. The header shows `habits 3/5`, and `synth_habits` prints it for your prompt.

## Projects and goals (`O`)
Projects page: progress bar, health (on track, at risk, stale, overdue, done, paused), due date, an ETA from your
recent completion pace, tracked time, estimate left, blocked and overdue counts. `e` sets status, due and a description,
`enter` opens the project in the list. Goals page: `count` (finish N tasks), `time` (track N hours), `tasks` (finish
everything matching a filter) and `manual` (milestone checklist), each with an optional due date, pace status
(ahead, on pace, behind) and a progress sparkline.

## Dependencies (`B`)
Mark a task as blocked by another, or as blocking one. Blocked tasks are dimmed and marked, the Ready and Blocked views
appear in the sidebar, and `is:blocked` / `is:ready` work in filters. Cycles are refused. Finishing a blocked task asks first
(`blocked_done = "warn"|"allow"|"deny"`), and finishing a blocker tells you what it unblocked.

## Snooze (`Z`)
Hide a task until a date. Snoozed tasks leave every view and count except the Snoozed view, and wake up on their day with a
marker and the `on_wake` hook. `snooze_hide = false` keeps them visible.

## Estimate accuracy
Give tasks `est:` and track time. The stats page (`S`, tab 4) shows your median and mean actual over estimate, how often you land
within 25 percent, accuracy by project and each recent task. When you type an estimate, synth shows what your history suggests.

## Bigger features

### Focus mode (`f`)
A fullscreen pomodoro for the selected task: big clock, progress bar, round dots and an animated synth wave.
Work, short break and long break lengths come from `focus_work`, `focus_break`, `focus_long` and `focus_rounds`.
Work time is logged to the task automatically. Keys: `space` pause, `n` skip phase, `+` `-` change the phase by 5 minutes,
`r` restart the phase, `x` mark the task done and leave, `q` leave. Phases ring the bell and fire the
`on_focus_start` and `on_focus_end` hooks.

### Time tracking (`w`)
Start or stop a running timer on the selected task. The header shows the live clock and the task, and the timer
keeps running if you quit synth. Add `time` to `columns` to show tracked time in the list, and use `est:` to compare
against an estimate (the detail pane turns red when you go over). `synth --tracking` prints the active timer for
prompts and status bars.

### Stats (`S`)
Five pages (`tab` or `1`-`5`, `r` changes the range between 7, 14 and 30 days):
overview (done today, streak, per day average, open and overdue, completions per day, open by priority),
time (tracked per day, by project, top tasks), a 26 week completion heatmap with a weekday breakdown, estimate accuracy, and momentum (current and best streak, last 7 days against the 7 before, weekly bars).
The header shows a compact `5d ▲ 12` segment: your completion streak, the trend arrow and tasks done in the last 7 days
(turn it off with `header_momentum = false`).

### Task history (`I` to the history tab, `W` for everything)
Every change to a task (created, completed, reopened, renamed, priority, due date, project, tags, snooze, dependencies,
notes, estimate, repeat) is recorded with a timestamp. The `history` tab of the detail pane shows one task's timeline,
and `W` (or `:changes`) lists everything that changed in the last day, 7, 14 or 30 days (`r` switches the range).
Undo also rolls the history back. Turn recording off with `history = false`.

### Calendar and agenda (`C`)
A month grid with a dot per open task (colored by priority, red when overdue) and a day panel.
`h j k l` move by day and week, `[` `]` change month, `enter` focuses the day's tasks, `x` toggles done,
`<` `>` shift the due date by a day, `m` moves it to any date (`fri`, `+3d`, `12-25`), `a` adds a task for that day,
`enter` on a task jumps to it in the main list. `v` flips to the agenda: overdue, then each upcoming day, then undated tasks.
On narrow terminals the agenda opens by default. `week_start = "sun"` changes the first weekday.

### Fuzzy finder (`ctrl-p`)
Type part of a name to jump to any task, project, tag or view. The same picker powers project assignment
(`@`): pick an existing project or create a new one by typing it, and linking tasks (`&`).

### Task links (`L`, `&`, `ctrl-o`)
Write `[[title]]` or `[[id]]` in a task title or notes to link another task, or paste a url.
The list shows an arrow marker, the detail pane lists links and backlinks, and `L` opens a menu to jump to a task
(`ctrl-o` returns) or open a url with `xdg-open` (set `open_cmd` to change it). `&` picks a task and inserts the link for you.

### Animations
A sweep and filling checkbox when you complete a task, a typewriter reveal for new tasks, an eased progress bar,
a spinner on the tracked task and the focus wave. Turn them off with `animations = false`
(or `:set animations off`) and change the pace with `anim_speed`.

## Settings panel (`,`)

Everything below can be changed from inside synth, no file editing needed. Press `,` (or run `:settings`, or `:set` with no arguments).
The layout is a category tree on the left and a card per setting on the right, each with its control and a description.

- `up` `down` move, `tab` jumps between tree, cards and the buttons, `enter` edits, `/` searches every setting, `esc` closes.
- Toggles flip, choices open a list that previews live (try the theme), numbers and text open a prompt, lists such as columns
  and sidebar sections open a checklist you can reorder with `J` and `K`.
- Colors: edit any theme role with a live swatch. Built-in themes are copied into a custom theme so they are never damaged.
- Keybindings: every action, comma separated keys, chords like `g g`, conflicts are resolved for you.
- Views, sorts, styling rules, templates, shell actions, hooks, tag and project colors all have small editors with add, edit,
  reorder and delete.
- `Reset` (or `r`) removes your change for one setting, `Save` (or `ctrl-s`) writes it, `Cancel` reverts everything unsaved.
  The mouse works too: click a section, click a card twice to edit, click the buttons.

Changes are saved to `settings.json` next to your config and take priority over `config.toml`, which keeps working for hand editing.
With `--profile NAME` the file is `settings-NAME.json`.

### Top bar widgets
The top bar is built from widgets you order yourself (settings panel, Header category): `header_left` and `header_right`.
Widgets: `app`, `view`, `sort`, `query`, `selection`, `timer`, `progress`, `momentum`, `habits`, `clock`, `date`, `open`,
`overdue`, `due_today`, `greeting`, `week`, `sync`, `event`, `irc` and `text` (your own text from `header_text`). Widgets that have nothing to show
hide themselves, and ones that do not fit are skipped. `header_style` is `plain`, `divided` or `pills`.
For the clock, `clock_12h` gives `3:07 PM` and `clock_seconds` adds seconds. `clock_format` (strftime) overrides both.

## Weekly review (`R`)
A five step screen (`tab` moves on, `1`-`5` jump): wins (done count against the week before, time tracked, by project),
slipped (overdue), stale (open 3 weeks with no due date and no changes), ahead (due in the next 7 days, with the planned
estimate) and reflect. On the list steps: `r` reschedule, `t` tomorrow, `w` next week, `s` snooze a week, `x` done, `D` drop.
The last step writes the review into today's journal (`e`). synth reminds you on start when the last review is a week old
(`review_nudge`).

## Git
Open the git menu with `ctrl-g` (or `:git`, `:todos`, `:sync`).

**Project folders.** Give a project a folder with `path:` in the projects screen (`O`, then `e`) or from the git menu.

**Find TODOs.** Scans a project folder (`git grep` inside a repo) for `TODO`, `FIXME`, `HACK` and `XXX` comments and lets you
import them as tasks tagged `#todo`, with `file:line` in the notes. Already imported comments show as tracked. When a comment
disappears from the code, `c` completes its task. Change the markers with `todo_markers`.

**Link tasks to git.** From the git menu, link a branch (or create `synth/12-fix-thing` from the task title) or a commit. Linked
tasks show a branch marker in the list and the branch, state and commits on the info tab. When the branch has new commits and
is merged into the default branch, the task is completed (`git_auto_done`). Commit messages containing `synth:12` link the
commit to task 12, and `closes synth:12`, `fixes synth:12` or `done synth:12` also complete it. Branches are checked in the
background every `git_refresh` minutes.

**Data in git.** With `git_sync = true` (or "Track data folder" in the git menu) the data folder becomes a git repository.
Every change is committed a few seconds after the last edit with a message that lists what happened, for example
`synth: 3 changes` followed by `- done #12 fix cutscenes`. `state.json` is ignored. Add a remote named `origin` in the data folder
and turn on `git_push` to pull when synth starts and push after each commit. A rebase conflict is aborted and shown in the
`sync` header widget instead of touching your data. Commit history is a full audit log you can browse with `git log`.

## Flicker
Each frame is sent to the terminal as one synchronized update (terminals that support it, such as kitty, foot, alacritty,
wezterm and ghostty, never show half a frame), and keys that arrive together (a held `j`) are applied before a single redraw.
If your terminal prints stray characters, set `sync_output = false`.

## Command-line capture
Add tasks without opening the app, from fish or any script:

```fish
synth add "buy milk !2 tomorrow #home"
synth add -p work -t inbox "write report by friday"
pbpaste | synth add            # one task per line, indent for subtasks
git log --oneline -5 | synth add -p ops
```
The usual quick-add syntax works, plus trailing phrases like `tomorrow`, `by friday`, `next week` and `in 3 days`. Piped text
is read like a brain dump (below). Changes go into the history and, with `git_sync`, are committed right away.

## Brain dump (`Q`)
Paste notes, a meeting summary or a chat log. synth splits it into tasks, understands bullets, `[ ]` and `[x]` checkboxes,
indentation for subtasks and `# Heading` lines (which set the project), then shows a checklist to review before anything is
imported.

## Bulk edit (`M`)
Select tasks with `v` (or "select tasks matching a filter" inside the menu) and change their project, tags, due date, priority,
snooze state, done state, or delete them in one go.

## What now? (`.`)
Tell it how much time you have and your energy (`m`, `e`) and it ranks what to do next from due dates, priority, what it
unblocks, whether the estimate fits (scaled by your own estimate accuracy) and the project you are working in. With a
calendar loaded, the time until your next event is filled in for you. `enter` starts tracking, `f` starts focus mode, `x`
completes, `z` snoozes. Tag tasks `#quick`, `#easy` or `#admin` for low energy and `#deep` or `#focus` for high energy.

## Dependency graph (`m`)
A map of what blocks what, prerequisites on the left. The critical path (longest chain by estimate) is highlighted, `+N` shows
how many tasks finishing a task eventually unblocks, and the biggest bottleneck is named at the top. `j`/`k` move within a
column, `h`/`l` follow prerequisites and dependents, `enter` shows the task in the list, `d` includes finished tasks.

## Time travel (`ctrl-t`)
With the data folder tracked in git (`git_sync`), browse every saved version of your list. For the chosen version, see what was
deleted since, what changed and what was added. `enter` restores a deleted task or puts a changed one back how it was,
`a` restores every deleted task, and `R` replaces your whole list with that version (undo with `u`).

## GitHub (git menu, `:issues`, `:prs`)
Needs the GitHub CLI (`gh auth login`). Import your assigned issues or your open pull requests from a project folder, or link
any issue or PR to an existing task. Linked tasks are completed automatically when the issue is closed or the PR is merged
(`git_auto_done`). The issue or PR link is placed at the top of the notes so `L` opens it.

## Calendar events
Set `ics_sources` to the paths or URLs of `.ics` files (Google, Outlook and Apple calendars all export them, and `webcal://`
works). Recurring events, all day events and time zones are understood. Events show in the calendar (`~` marks days) and the
agenda, the `event` header widget shows what is next, and `i` in the calendar turns an event into a task with its duration as the
estimate. Web calendars are cached in the data folder and refreshed every `ics_refresh` minutes.

## IRC chat (`ctrl-k`, `:irc`)
Talk to people (or ask for help) without leaving your list. Add a network in the settings panel (IRC category), or press `ctrl-k`
the first time and answer a few questions; "Add Libera.Chat" in settings does the same.

**Logging in.** Set the network's login method to `sasl` (default when you give an account) or `nickserv`, and the NickServ
account name. SASL PLAIN is used when the server offers it, with a NickServ `IDENTIFY` as the fallback. The password is **never
written to disk**: not in `settings.json`, `config.toml`, the state file or the git tracked data folder. synth finds it in this order:

1. the network's `password_cmd`, a shell command that prints it, for example `pass show irc/libera` (use a GUI pinentry, since
   the command cannot ask on the terminal synth is using)
2. the environment variable `SYNTH_IRC_PASSWORD_<NAME>`, with the network name uppercased, for example `SYNTH_IRC_PASSWORD_LIBERA`
3. a masked prompt when you connect (kept in memory until you quit)

Connections use TLS with certificate checking by default (port 6697). Passwords are refused on a network set to "No TLS", so they
can never cross the network in the clear. Networks with `autoconnect` start with synth, but only when a password can be found
without asking.

**The screen.** Buffers on the left (unread count, `!` for mentions), the conversation in the middle with the topic above it, the
nick list on the right when the terminal is wide, and an input line at the bottom. `esc` goes back to your tasks and the
connection stays up. Mentions and private messages show in the status line (and ring the bell if `irc_bell` is on), and the `irc`
top bar widget shows the unread or mention count.

| key | action |
| --- | --- |
| `enter` | send the line, `/commands` as below |
| `tab` | complete a nick, press again for the next match |
| `ctrl-n` / `ctrl-p`, `alt-1` to `alt-9` | next or previous buffer, jump to a buffer |
| `pgup` / `pgdn` | scroll back |
| `up` / `down` | input history |
| `esc` | back to the task list |

Commands: `/join #chan`, `/part`, `/msg nick text`, `/me`, `/nick`, `/topic`, `/names`, `/whois`, `/away`, `/ns`, `/cs`,
`/identify`, `/raw`, `/connect [network]`, `/disconnect`, `/close`, `/next`, `/prev`, `/clear`, `/exit`, `/help`. Lines to NickServ
and ChanServ are never echoed into a buffer or saved in input history. `//text` sends a line that starts with a slash.

Task integration: `/share` sends the selected task (title, due, priority, project, tags, never notes) to the current buffer,
`/todo [nick]` turns the last message (from that nick, if given) into a task with a note saying who said it and where, and
`/task TEXT` adds a task with the usual quick add syntax.

Chat is kept in memory only (the last 500 lines per buffer), nothing is logged to disk. Set `irc_dock = true` for a small live
strip of the current buffer under the task list (`irc_dock_lines` tall). Options: `irc_show_joins`, `irc_nick_colors`, `irc_time`
(strftime), `irc_bell`. Network fields: `name host port nick auth account password_cmd channels autoconnect insecure noverify
noreconnect user realname`.

## Parking lot
In focus mode press `p` to jot down whatever just came to mind. It lands in the inbox tagged `#parked`, with a note of what you
were focusing on, and the focus screen counts what you parked so the thought cannot nag you.

## Customizing in a file

Almost everything is configurable, see the template for the full list. Highlights beyond keys, themes and views:

| What | How |
| --- | --- |
| style tasks by filter | `[[rules]]` with `when`, `fg`, `bg`, `bold`, `dim`, `prefix`, `suffix` |
| colors for tags and projects | `[tag_colors]`, `[project_colors]`, `priority_colors`, `priority_symbols` |
| columns | `columns` plus `column_widths`; `est`, `id`, `deps`, `snooze`, `created` are available |
| your own sorts | `[sorts] focus = "done,blocked,-prio,due"`, cycle with `s` |
| per view options | `sort`, `columns`, `show_done`, `icon` inside any `[[views]]` |
| task templates | `[[templates]]` with `{variables}`, subtasks, tags, project, due |
| shell actions | `[[actions]]` with a key, run in background, foreground or captured |
| key chords | `quit = ["g q"]` style multi key sequences in `[keys]` |
| wording | `[strings]` for the app name and prompts |
| layout | `indent`, `border_style`, `header_*`, `sync_output`, `sidebar_sections`, `sidebar_builtin`, `hints`, `mouse` |
| theme inheritance | `inherit = "nord"` inside a custom theme |
| start somewhere else | `start_screen = "journal"` (or habits, projects, stats, calendar, agenda) |
| split configs | `include = ["work.toml"]` and `synth --profile work` (loads `config-work.toml`) |

A commented config is created at `~/.config/synth/config.toml` on first run (`synth --print-config` prints it).
Everything is optional.

```toml
theme = "cherry"
sort = "priority"
detail = "bottom"                 # right, bottom, off
columns = ["check", "title", "due", "tags"]   # order and visibility
ascii = false                     # plain ascii symbols
date_format = "%d/%m"

[keys]                            # remap any action, [] unbinds
quit = ["Q"]
add = ["a", "o"]
toggle = ["x", "space", "enter"]

[symbols]
check_off = "[ ]"
check_on = "[x]"
cursor = ">"

[[views]]                         # custom sidebar views
name = "Work, urgent"
query = "@work !2+ is:open"

[themes.cherry]                   # custom themes, missing roles fall back to tokyonight
bg = "#1a0a10"
accent = "#ff3366"
sel_bg = "#3a1220"

[hooks]                           # shell commands, env: SYNTH_EVENT SYNTH_TITLE SYNTH_ID
# also: on_add on_delete on_note on_snooze on_wake on_habit on_journal on_focus_start
on_done = "notify-send 'done' \"$SYNTH_TITLE\""
on_focus_end = "notify-send 'focus' \"$SYNTH_TITLE\""
```

Built-in themes: `tokyonight` (default), `tokyonight-storm`, `tokyonight-day`, `synth`, `nord`, `gruvbox`, `mono`, `daylight`.
Hex colors are applied as exact palette slots, so they look the same even when your terminal remaps its 256 colors. Set `exact_colors = false` if your terminal dislikes that.
Colors can be `"#rrggbb"`, a number 0 to 255, a basic color name, or `"default"`.
Set `transparent = true` to keep your terminal background.
Action names for `[keys]` are listed in `?` inside the app.

## Files

| Path | What |
| --- | --- |
| `~/.local/share/synth/todos.json` | tasks, completion history, time log, journal, habits, goals and project info (plain JSON, edits from other instances are picked up live) |
| `~/.local/share/synth/state.json` | remembered theme, sort, view, toggles |
| `~/.config/synth/config.toml` | config you edit by hand |
| `~/.config/synth/settings.json` | everything saved from the settings panel, wins over `config.toml` |

Environment overrides: `SYNTH_DATA`, `SYNTH_CONFIG`. Flags: `--data`, `--config`, `--profile`, `--theme`, `--view`, `--habits`, `--count`, `--due-count`, `--tracking`.

## Tests

```fish
python3 -I tests/test_core.py
```