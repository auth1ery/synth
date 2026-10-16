#!/usr/bin/env python3
"""synth: a fullscreen, hackable terminal todo list.

Run `synth` to open the TUI. Press ? inside for every key binding.
Config lives in ~/.config/synth/config.toml, data in ~/.local/share/synth.
"""

import argparse
import collections
import contextlib
import copy
import curses
import datetime as dt
import functools
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unicodedata

try:
    import tomllib
except ImportError:  # python older than 3.11
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

VERSION = "1.2.0"


def _xdg(env, default):
    return os.environ.get(env) or os.path.expanduser(default)


CONFIG_DIR = os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), "synth")
DATA_DIR = os.path.join(_xdg("XDG_DATA_HOME", "~/.local/share"), "synth")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.toml")
DATA_PATH = os.path.join(DATA_DIR, "todos.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------

DEFAULT_KEYS = {
    "up": ["k", "up"],
    "down": ["j", "down"],
    "top": ["g", "home"],
    "bottom": ["G", "end"],
    "pgup": ["ctrl-u", "pgup"],
    "pgdn": ["ctrl-d", "pgdn"],
    "toggle": ["x", "space"],
    "add": ["a"],
    "add_top": ["A"],
    "add_child": ["c"],
    "edit": ["e", "enter"],
    "notes": ["E"],
    "delete": ["d", "delete"],
    "prio_up": ["p", "+"],
    "prio_down": ["P", "-"],
    "due": ["t"],
    "tags": ["#"],
    "project": ["@"],
    "repeat": ["r"],
    "move_up": ["K", "alt-k"],
    "move_down": ["J", "alt-j"],
    "fold": ["z"],
    "collapse": ["h", "left"],
    "expand": ["l", "right"],
    "search": ["/"],
    "clear_filter": ["esc"],
    "sort": ["s"],
    "undo": ["u"],
    "redo": ["ctrl-r"],
    "select": ["v"],
    "select_all": ["V"],
    "focus": ["tab"],
    "theme": ["T"],
    "palette": [":"],
    "help": ["?", "f1"],
    "quit": ["q", "ctrl-c"],
    "clear_done": ["X"],
    "hide_done": ["H"],
    "toggle_sidebar": ["b"],
    "toggle_detail": ["i"],
    "view_next": ["]"],
    "view_prev": ["["],
    "redraw": ["ctrl-l"],
    "find": ["ctrl-p"],
    "links": ["L"],
    "link_add": ["&"],
    "back": ["ctrl-o"],
    "track": ["w"],
    "focus_mode": ["f"],
    "stats": ["S"],
    "calendar": ["C"],
    "note_add": ["n"],
    "deps": ["B"],
    "snooze": ["Z"],
    "journal": ["D"],
    "habits": ["Y"],
    "projects": ["O"],
    "template": ["N"],
    "actions_menu": ["="],
    "detail_down": ["ctrl-e"],
    "detail_up": ["ctrl-y"],
    "detail_tab": ["I"],
    "duplicate": ["alt-y"],
    "yank": ["y"],
    "settings": [","],
}

ACTION_DOC = {
    "up": "move up",
    "down": "move down",
    "top": "jump to top",
    "bottom": "jump to bottom",
    "pgup": "page up",
    "pgdn": "page down",
    "toggle": "toggle done",
    "add": "add task",
    "add_top": "add task at the top",
    "add_child": "add subtask",
    "edit": "edit task (quick-add syntax)",
    "notes": "edit notes in $EDITOR",
    "delete": "delete task",
    "prio_up": "raise priority",
    "prio_down": "lower priority",
    "due": "set due date",
    "tags": "add or remove tags",
    "project": "set project",
    "repeat": "set repeat interval",
    "move_up": "move task up",
    "move_down": "move task down",
    "fold": "fold or unfold subtasks",
    "collapse": "collapse subtasks",
    "expand": "expand subtasks",
    "search": "filter with a query",
    "clear_filter": "clear filter or selection",
    "sort": "cycle sort order",
    "undo": "undo",
    "redo": "redo",
    "select": "select task (bulk actions)",
    "select_all": "select all visible",
    "focus": "switch sidebar or list focus",
    "theme": "pick a theme",
    "palette": "command palette",
    "help": "this help",
    "quit": "quit",
    "clear_done": "delete all done tasks",
    "hide_done": "show or hide done tasks",
    "toggle_sidebar": "show or hide sidebar",
    "toggle_detail": "cycle detail pane",
    "view_next": "next view",
    "view_prev": "previous view",
    "redraw": "redraw screen",
    "find": "fuzzy find tasks, projects, tags, views",
    "links": "open links and backlinks of a task",
    "link_add": "link this task to another",
    "back": "go back after a jump",
    "track": "start or stop time tracking",
    "focus_mode": "focus mode (pomodoro)",
    "stats": "stats and charts",
    "calendar": "calendar and agenda",
    "note_add": "add a quick timestamped note to the task",
    "deps": "dependencies (blocked by, blocks)",
    "snooze": "snooze task until a date",
    "journal": "daily journal",
    "habits": "habit tracker",
    "projects": "projects and goals",
    "template": "new task from a template",
    "actions_menu": "custom actions and templates",
    "detail_down": "scroll the detail pane down",
    "detail_up": "scroll the detail pane up",
    "detail_tab": "switch detail pane section (notes, info, links)",
    "duplicate": "duplicate task with its subtasks",
    "yank": "copy task text to the clipboard",
    "settings": "open the settings panel",
}

DEFAULTS = {
    "theme": "tokyonight",
    "sort": "manual",
    "sidebar": True,
    "sidebar_width": 24,
    "detail": "right",
    "detail_size": 38,
    "ascii": False,
    "transparent": False,
    "exact_colors": True,
    "animations": True,
    "anim_speed": 1.0,
    "week_start": "mon",
    "focus_work": 25,
    "focus_break": 5,
    "focus_long": 15,
    "focus_rounds": 4,
    "focus_auto": True,
    "focus_bell": True,
    "open_cmd": "",
    "copy_cmd": "",
    "show_done": True,
    "cascade_done": True,
    "confirm_delete": True,
    "scrolloff": 3,
    "date_format": "%b %d",
    "columns": ["check", "prio", "title", "tags", "project", "due"],
    "symbols": {},
    "priority_labels": ["none", "low", "medium", "high"],
    "keys": {},
    "hooks": {},
    "themes": {},
    "views": [],
    "notes_editor": "builtin",
    "note_stamp": "%Y-%m-%d %H:%M",
    "notes_inline": False,
    "snooze_hide": True,
    "blocked_done": "warn",
    "header_habits": True,
    "header_clock": False,
    "clock_format": "%H:%M",
    "header_progress": True,
    "header_info": True,
    "sidebar_counts": True,
    "sidebar_sections": ["custom", "projects", "tags"],
    "sidebar_builtin": ["all", "today", "upcoming", "inbox", "done", "ready", "blocked", "snoozed"],
    "indent": 2,
    "border_style": "round",
    "mouse": True,
    "start_screen": "list",
    "journal_template": "",
    "rules": [],
    "sorts": {},
    "tag_colors": {},
    "project_colors": {},
    "priority_symbols": [],
    "priority_colors": [],
    "column_widths": {},
    "strings": {},
    "actions": [],
    "templates": [],
    "hints": [],
    "include": [],
    "detail_tab": "notes",
    "detail_sections": ["notes", "info", "links"],
}

BORDERS = {
    "round": ("╭", "╮", "╰", "╯", "─", "│"),
    "square": ("┌", "┐", "└", "┘", "─", "│"),
    "double": ("╔", "╗", "╚", "╝", "═", "║"),
    "heavy": ("┏", "┓", "┗", "┛", "━", "┃"),
    "ascii": ("+", "+", "+", "+", "-", "|"),
}
STR_OPTS = {
    "notes_editor": ["builtin", "external"],
    "border_style": list(BORDERS),
    "blocked_done": ["warn", "allow", "deny"],
    "start_screen": ["list", "journal", "habits", "projects", "stats", "calendar", "agenda"],
    "detail_tab": ["notes", "info", "links"],
    "note_stamp": None,
    "clock_format": None,
}

SORTS = ["manual", "priority", "due", "created", "alpha"]  # custom sorts are added from [sorts]
BOOL_OPTS = ["snooze_hide", "notes_inline", "header_habits", "header_clock", "header_progress", "header_info",
             "sidebar_counts", "mouse",
             "sidebar", "ascii", "transparent", "exact_colors", "animations", "show_done", "cascade_done",
             "confirm_delete", "focus_auto", "focus_bell"]
INT_OPTS = ["indent", "sidebar_width", "detail_size", "scrolloff", "focus_work", "focus_break", "focus_long", "focus_rounds"]
FLOAT_OPTS = ["anim_speed"]

UNICODE_SYMBOLS = {
    "check_off": "○",
    "check_on": "●",
    "fold_open": "▾",
    "fold_closed": "▸",
    "repeat": "↻",
    "note": "≡",
    "bar_on": "▰",
    "bar_off": "▱",
    "cursor": "▌",
    "select": "◆",
    "ellipsis": "…",
    "hline": "─",
    "vline": "│",
    "corner_tl": "╭",
    "corner_tr": "╮",
    "corner_bl": "╰",
    "corner_br": "╯",
    "bullet": "•",
    "link": "↗",
    "web": "⌁",
    "back": "↖",
    "track": "▶",
    "blocked": "⊘",
    "snooze": "◌",
    "wake": "▲",
}

ASCII_SYMBOLS = {
    "check_off": "[ ]",
    "check_on": "[x]",
    "fold_open": "-",
    "fold_closed": "+",
    "repeat": "~",
    "note": "=",
    "bar_on": "#",
    "bar_off": "-",
    "cursor": ">",
    "select": "*",
    "ellipsis": "...",
    "hline": "-",
    "vline": "|",
    "corner_tl": "+",
    "corner_tr": "+",
    "corner_bl": "+",
    "corner_br": "+",
    "bullet": "*",
    "link": "->",
    "web": "@",
    "back": "<-",
    "track": ">",
    "blocked": "X",
    "snooze": "z",
    "wake": "^",
}

THEME_ROLES = [
    "bg", "fg", "dim", "accent", "accent2", "sel_bg", "done", "p1", "p2", "p3",
    "overdue", "today", "soon", "tag", "project", "border", "bar_bg", "ok", "err",
]

THEMES = {
    "tokyonight": {
        "bg": "#1a1b26", "fg": "#c0caf5", "dim": "#565f89", "accent": "#7aa2f7",
        "accent2": "#7dcfff", "sel_bg": "#283457", "done": "#545c7e", "p1": "#9ece6a",
        "p2": "#e0af68", "p3": "#f7768e", "overdue": "#f7768e", "today": "#e0af68",
        "soon": "#7dcfff", "tag": "#bb9af7", "project": "#73daca", "border": "#3b4261",
        "bar_bg": "#16161e", "ok": "#9ece6a", "err": "#f7768e",
    },
    "tokyonight-storm": {
        "bg": "#24283b", "fg": "#c0caf5", "dim": "#565f89", "accent": "#7aa2f7",
        "accent2": "#7dcfff", "sel_bg": "#2e3c64", "done": "#545c7e", "p1": "#9ece6a",
        "p2": "#e0af68", "p3": "#f7768e", "overdue": "#f7768e", "today": "#e0af68",
        "soon": "#7dcfff", "tag": "#bb9af7", "project": "#73daca", "border": "#3b4261",
        "bar_bg": "#1f2335", "ok": "#9ece6a", "err": "#f7768e",
    },
    "tokyonight-day": {
        "bg": "#e1e2e7", "fg": "#3760bf", "dim": "#848cb5", "accent": "#2e7de9",
        "accent2": "#007197", "sel_bg": "#b7c1e3", "done": "#a8aecb", "p1": "#587539",
        "p2": "#8c6c3e", "p3": "#f52a65", "overdue": "#f52a65", "today": "#8c6c3e",
        "soon": "#007197", "tag": "#9854f1", "project": "#118c74", "border": "#c4c8da",
        "bar_bg": "#d0d5e3", "ok": "#587539", "err": "#f52a65",
    },
    "synth": {
        "bg": "#120e1f", "fg": "#d9d4f0", "dim": "#6b6488", "accent": "#ff4fd8",
        "accent2": "#3df5ff", "sel_bg": "#2b2150", "done": "#5a5478", "p1": "#7cf7a6",
        "p2": "#ffd166", "p3": "#ff5c7a", "overdue": "#ff5c7a", "today": "#ffd166",
        "soon": "#3df5ff", "tag": "#b48cff", "project": "#3df5ff", "border": "#3b2f6b",
        "bar_bg": "#1d1633", "ok": "#7cf7a6", "err": "#ff5c7a",
    },
    "nord": {
        "bg": "#2e3440", "fg": "#d8dee9", "dim": "#616e88", "accent": "#88c0d0",
        "accent2": "#81a1c1", "sel_bg": "#3b4252", "done": "#4c566a", "p1": "#a3be8c",
        "p2": "#ebcb8b", "p3": "#bf616a", "overdue": "#bf616a", "today": "#ebcb8b",
        "soon": "#88c0d0", "tag": "#b48ead", "project": "#8fbcbb", "border": "#434c5e",
        "bar_bg": "#3b4252", "ok": "#a3be8c", "err": "#bf616a",
    },
    "gruvbox": {
        "bg": "#282828", "fg": "#ebdbb2", "dim": "#928374", "accent": "#fabd2f",
        "accent2": "#83a598", "sel_bg": "#3c3836", "done": "#665c54", "p1": "#b8bb26",
        "p2": "#fabd2f", "p3": "#fb4934", "overdue": "#fb4934", "today": "#fabd2f",
        "soon": "#83a598", "tag": "#d3869b", "project": "#8ec07c", "border": "#504945",
        "bar_bg": "#32302f", "ok": "#b8bb26", "err": "#fb4934",
    },
    "mono": {
        "bg": "#000000", "fg": "#d0d0d0", "dim": "#707070", "accent": "#ffffff",
        "accent2": "#b0b0b0", "sel_bg": "#303030", "done": "#505050", "p1": "#a0a0a0",
        "p2": "#c8c8c8", "p3": "#ffffff", "overdue": "#ffffff", "today": "#e0e0e0",
        "soon": "#b0b0b0", "tag": "#909090", "project": "#a8a8a8", "border": "#404040",
        "bar_bg": "#1c1c1c", "ok": "#d0d0d0", "err": "#ffffff",
    },
    "daylight": {
        "bg": "#fdf6e3", "fg": "#47585f", "dim": "#93a1a1", "accent": "#d33682",
        "accent2": "#268bd2", "sel_bg": "#eee8d5", "done": "#a8b2b2", "p1": "#859900",
        "p2": "#b58900", "p3": "#dc322f", "overdue": "#dc322f", "today": "#b58900",
        "soon": "#268bd2", "tag": "#6c71c4", "project": "#2aa198", "border": "#d8d1bb",
        "bar_bg": "#eee8d5", "ok": "#859900", "err": "#dc322f",
    },
}

CONFIG_TEMPLATE = """\
# synth config. Every option is optional. Delete a line to get the default.
# You do not have to edit this file: press , inside synth for the settings panel.
# What you save there goes to settings.json next to this file and wins over this file.
# Changes apply on next launch, or run :reload inside synth.

# theme = "tokyonight"       # tokyonight, tokyonight-storm, tokyonight-day, synth, nord,
#                            # gruvbox, mono, daylight, or your own
# sort = "manual"            # manual, priority, due, created, alpha, or one of your [sorts]
# sidebar = true
# sidebar_width = 24
# detail = "right"           # right, bottom, off
# detail_size = 38           # width when right, height when bottom
# ascii = false              # plain ascii symbols for limited fonts
# transparent = false        # use the terminal background
# exact_colors = true        # redefine palette slots so theme colors are exact
#                            # (turn off if your terminal misbehaves)
# show_done = true
# cascade_done = true        # completing a parent completes its subtasks
# confirm_delete = true
# animations = true          # completion sweep, typewriter add, eased progress bar
# anim_speed = 1.0           # 2.0 is twice as fast
# week_start = "mon"         # calendar week start: mon or sun
# focus_work = 25            # focus mode minutes
# focus_break = 5
# focus_long = 15
# focus_rounds = 4           # work rounds before a long break
# focus_auto = true          # start the next phase automatically
# focus_bell = true
# open_cmd = ""              # command that opens links, default xdg-open
# copy_cmd = ""              # clipboard command for y, default wl-copy, xclip, xsel, pbcopy or OSC 52
# scrolloff = 3
# date_format = "%b %d"      # strftime
# priority_labels = ["none", "low", "medium", "high"]

# Column order for the task list. Remove names to hide columns.
# Available: check, prio, title, tags, project, time, due, est, id, deps, snooze, created
# columns = ["check", "prio", "title", "tags", "project", "due"]
# column_widths = { tags = 14, project = 12 }   # caps for the flexible columns

# Override any symbol:
# [symbols]
# check_off = "[ ]"
# check_on = "[x]"
# cursor = ">"

# Key bindings. Each action takes a list of keys, [] unbinds it.
# Names: letters, symbols, enter, space, tab, esc, up, down, left, right,
# home, end, pgup, pgdn, delete, backspace, ctrl-x, alt-x, f1..f12
# [keys]
# toggle = ["x", "space"]
# quit = ["q"]
# add = ["a", "o"]

# Run shell commands on events. Env: SYNTH_EVENT, SYNTH_TITLE, SYNTH_ID.
# [hooks]
# on_done = "notify-send 'done' \\"$SYNTH_TITLE\\""
# on_add = ""
# on_delete = ""
# on_focus_start = ""
# on_focus_end = ""

# Custom views appear in the sidebar. Query syntax is the same as the / filter.
# [[views]]
# name = "Work, urgent"
# query = "@work !2+ is:open"

# Custom themes. Missing roles fall back to the tokyonight theme.
# Roles: bg fg dim accent accent2 sel_bg done p1 p2 p3 overdue today soon
#        tag project border bar_bg ok err
# Colors: "#rrggbb", 0-255, or a basic name. "default" is the terminal color.
# [themes.cherry]
# bg = "#1a0a10"
# accent = "#ff3366"
# sel_bg = "#3a1220"
# inherit = "nord"           # start from another theme instead of tokyonight

# ---- notes, journal, habits, snooze, dependencies ----
# detail_sections = ["notes", "info", "links"]   # tabs of the detail pane, press I to cycle
# detail_tab = "notes"       # tab to open with
# notes_editor = "builtin"   # builtin (ctrl-s saves) or external ($VISUAL / $EDITOR)
# note_stamp = "%Y-%m-%d %H:%M"   # stamp used by the quick note key
# notes_inline = false       # show the first line of notes after the title
# snooze_hide = true         # snoozed tasks leave every view except Snoozed
# blocked_done = "warn"      # finishing a blocked task: warn, allow or deny
# journal_template = "# {weekday}, {date}\\n\\n## Done\\n{done}\\n\\n## Notes\\n"
#   variables: {date} {weekday} {done} {done_count} {time} {open} {overdue} {habits}
# start_screen = "list"      # list, journal, habits, projects, stats, calendar, agenda

# ---- make it yours ----
# indent = 2                 # spaces per subtask level
# border_style = "round"     # round, square, double, heavy, ascii
# mouse = true
# header_info = true         # sort and hide-done text in the header
# header_progress = true     # progress bar
# header_habits = true       # habits done today
# header_clock = false       # clock in the header
# clock_format = "%H:%M"
# sidebar_counts = true
# sidebar_sections = ["custom", "projects", "tags"]   # order and visibility
# sidebar_builtin = ["all", "today", "upcoming", "inbox", "done", "ready", "blocked", "snoozed"]
# priority_symbols = ["", "!", "!!", "!!!"]
# priority_colors = ["", "#9ece6a", "#e0af68", "#f7768e"]
# hints = ["add:new", "toggle:done", "notes", "journal"]   # footer, action or action:label
# Multi key chords work in [keys]: quit = ["q", "g q"]

# [strings]                  # rename pieces of the interface
# app_name = "synth."
# empty = "all clear"
# add_title = "what needs doing?"

# [tag_colors]
# urgent = "#f7768e"
# [project_colors]
# home = "#73daca"

# Custom sorts. Fields: done prio due created title project tags est time id blocked snooze notes
# A leading - reverses a field. Cycle with the sort key or :sort NAME.
# [sorts]
# focus = "done,blocked,-prio,due"

# Rules style tasks that match a filter. Later rules win. Keys: fg bg bold dim prefix suffix
# [[rules]]
# when = "is:open !3"
# fg = "p3"
# bold = true
# [[rules]]
# when = "is:blocked"
# dim = true
# suffix = "(waiting)"

# Per view overrides: sort, columns, show_done, icon
# [[views]]
# name = "Deep work"
# query = "#deep is:open"
# sort = "priority"
# columns = ["check", "title", "est", "due"]
# icon = "*"

# Templates create a task with subtasks. {name} asks you for a value, {date} {weekday} are built in.
# [[templates]]
# name = "Bug report"
# key = "alt-b"              # optional shortcut
# title = "Fix {bug} #bug !2"
# notes = "## Repro\\n\\n## Expected\\n"
# subtasks = ["reproduce {bug}", "write a test", "fix it"]
# due = "+3d"

# Actions run a shell command on the selected task. Env: SYNTH_ID SYNTH_TITLE SYNTH_NOTES
# SYNTH_PROJECT SYNTH_TAGS SYNTH_DUE SYNTH_IDS SYNTH_VIEW. mode: bg (default), fg, capture.
# [[actions]]
# name = "copy title"
# key = "ctrl-g"
# cmd = "printf %s \\"$SYNTH_TITLE\\" | wl-copy"

# Extra hooks: on_note on_snooze on_wake on_habit on_journal
# Load more files with: include = ["work.toml"]. Run synth --profile work to also load config-work.toml.
"""

# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------


def cw(ch):
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def cell_len(s):
    return sum(cw(c) for c in s)


def clip(s, w, ell="…"):
    if w <= 0:
        return ""
    if cell_len(s) <= w:
        return s
    e = cell_len(ell)
    out, n = "", 0
    for c in s:
        k = cw(c)
        if n + k > w - e:
            break
        out += c
        n += k
    return out + ell


def pad(s, w, right=False):
    s = clip(s, w)
    gap = " " * (w - cell_len(s))
    return gap + s if right else s + gap


def wrap(text, w):
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, max(w, 4), replace_whitespace=False) or [""])
    return lines


# ---------------------------------------------------------------------------
# dates, quick-add parsing, queries
# ---------------------------------------------------------------------------

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def today():
    return dt.date.today()


def add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(d.day, last))


def parse_date(s, base=None):
    """Parse a human date. Returns a date, or None for 'none'. Raises ValueError."""
    base = base or today()
    s = s.strip().lower()
    if s in ("", "none", "clear", "-", "no"):
        return None
    if s in ("today", "tod", "now"):
        return base
    if s in ("tomorrow", "tom", "tmr"):
        return base + dt.timedelta(days=1)
    if s == "yesterday":
        return base - dt.timedelta(days=1)
    if s in ("nextweek", "nw"):
        return base + dt.timedelta(days=7 - base.weekday())
    if s == "eow":
        return base + dt.timedelta(days=(4 - base.weekday()) % 7)
    if s == "eom":
        return add_months(base.replace(day=1), 1) - dt.timedelta(days=1)
    if s[:3] in WEEKDAYS and (len(s) == 3 or "day" in s or s.startswith(("tues", "wednes", "thurs"))):
        delta = (WEEKDAYS.index(s[:3]) - base.weekday()) % 7
        return base + dt.timedelta(days=delta or 7)
    m = re.fullmatch(r"\+?(\d+)([dwmy])", s)
    if m:
        n, u = int(m.group(1)), m.group(2)
        if u == "d":
            return base + dt.timedelta(days=n)
        if u == "w":
            return base + dt.timedelta(weeks=n)
        if u == "m":
            return add_months(base, n)
        return add_months(base, 12 * n)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", s)
    if m:
        d = dt.date(base.year, int(m.group(1)), int(m.group(2)))
        return d if d >= base else d.replace(year=base.year + 1)
    raise ValueError("bad date: " + s)


def parse_repeat(s):
    s = s.strip().lower()
    if s in ("", "none", "no", "-"):
        return ""
    alias = {"daily": "1d", "weekly": "1w", "monthly": "1m", "yearly": "1y"}
    s = alias.get(s, s)
    if re.fullmatch(r"\d+[dwmy]", s):
        return s
    raise ValueError("bad repeat: " + s)


def next_due(due_iso, repeat, base=None):
    base = base or today()
    d = dt.date.fromisoformat(due_iso)
    d = max(d, base)
    n, u = int(repeat[:-1]), repeat[-1]
    if u == "d":
        return d + dt.timedelta(days=n)
    if u == "w":
        return d + dt.timedelta(weeks=n)
    if u == "m":
        return add_months(d, n)
    return add_months(d, 12 * n)


PRIO_WORDS = {"low": 1, "med": 2, "medium": 2, "high": 3}
UNSET = object()


def parse_quick(text):
    """Quick-add syntax: title #tag @project !2 due:tomorrow every:1w"""
    out = {"title": "", "tags": [], "project": "", "prio": 0, "due": UNSET, "repeat": "", "est": 0, "notes": ""}
    words = []
    if " // " in text:
        text, _, note = text.partition(" // ")
        out["notes"] = note.strip()
    for tok in text.split():
        low = tok.lower()
        if tok.startswith("#") and len(tok) > 1:
            if low[1:] not in out["tags"]:
                out["tags"].append(low[1:])
        elif tok.startswith("@") and len(tok) > 1:
            out["project"] = tok[1:]
        elif re.fullmatch(r"![0-3]", tok):
            out["prio"] = int(tok[1])
        elif low.startswith("!") and low[1:] in PRIO_WORDS:
            out["prio"] = PRIO_WORDS[low[1:]]
        elif low.startswith("due:") or tok.startswith("^"):
            try:
                d = parse_date(tok.split(":", 1)[1] if low.startswith("due:") else tok[1:])
                out["due"] = d.isoformat() if d else None
            except (ValueError, IndexError):
                words.append(tok)
        elif low.startswith("est:"):
            try:
                out["est"] = parse_duration(tok[4:])
            except ValueError:
                words.append(tok)
        elif low.startswith("every:") or tok.startswith("~"):
            try:
                out["repeat"] = parse_repeat(tok.split(":", 1)[1] if low.startswith("every:") else tok[1:])
            except (ValueError, IndexError):
                words.append(tok)
        else:
            words.append(tok)
    out["title"] = " ".join(words)
    return out


def serialize(t):
    parts = [t["title"]]
    parts += ["#" + g for g in t["tags"]]
    if t["project"]:
        parts.append("@" + t["project"].replace(" ", "-"))
    if t["prio"]:
        parts.append("!%d" % t["prio"])
    if t["due"]:
        parts.append("due:" + t["due"])
    if t["repeat"]:
        parts.append("every:" + t["repeat"])
    if t.get("est"):
        parts.append("est:" + fmt_duration(t["est"]))
    return " ".join(parts)


def compile_query(text, store=None):
    """Return predicate(task, today) for query text. All terms must match."""
    preds = []
    for tok in text.split():
        neg = False
        body = tok
        if tok.startswith("-") and len(tok) > 1 and (tok[1] in "#@!" or tok[1:].startswith(("due:", "is:", "has:"))):
            neg, body = True, tok[1:]
        low = body.lower()
        if low.startswith("#") and len(low) > 1:
            key = low[1:]
            p = (lambda t, td, key=key: any(g.startswith(key) for g in t["tags"]))
        elif low.startswith("@") and len(low) > 1:
            key = low[1:]
            if key == "none":
                p = (lambda t, td: not t["project"])
            else:
                p = (lambda t, td, key=key: t["project"].lower().startswith(key))
        elif re.fullmatch(r"![0-3]\+?", low):
            lvl, plus = int(low[1]), low.endswith("+")
            p = (lambda t, td, lvl=lvl, plus=plus: t["prio"] >= lvl if plus else t["prio"] == lvl)
        elif low.startswith("due:"):
            arg = low[4:]
            p = _due_pred(arg)
        elif low == "is:done":
            p = (lambda t, td: t["done"])
        elif low == "is:open":
            p = (lambda t, td: not t["done"])
        elif low == "has:notes":
            p = (lambda t, td: bool(t["notes"].strip()))
        elif low == "has:repeat":
            p = (lambda t, td: bool(t["repeat"]))
        elif low == "has:deps":
            p = (lambda t, td: bool(t.get("deps")))
        elif low == "has:est":
            p = (lambda t, td: bool(t.get("est")))
        elif low == "is:snoozed":
            p = (lambda t, td: is_snoozed(t, td))
        elif low == "is:blocked":
            p = (lambda t, td: store is not None and not t["done"] and bool(blockers(store, t)))
        elif low == "is:ready":
            p = (lambda t, td: store is not None and not t["done"] and not blockers(store, t)
                 and not is_snoozed(t, td))
        else:
            p = (lambda t, td, low=low: low in t["title"].lower() or low in t["notes"].lower())
        preds.append((neg, p))

    def run(t, td):
        for neg, p in preds:
            if bool(p(t, td)) == neg:
                return False
        return True

    return run


def _due_pred(arg):
    def f(t, td):
        d = t["due"]
        if arg == "none":
            return d is None
        if arg == "any":
            return d is not None
        if d is None:
            return False
        dd = dt.date.fromisoformat(d)
        if arg == "today":
            return dd == td
        if arg == "overdue":
            return dd < td
        if arg == "now":
            return dd <= td
        if arg == "week":
            return td <= dd <= td + dt.timedelta(days=7)
        try:
            target = parse_date(arg, td)
        except ValueError:
            return False
        return dd == target

    return f


BUILTIN_VIEWS = [
    ("all", "All", ""),
    ("today", "Today", "is:open due:now"),
    ("upcoming", "Upcoming", "is:open due:any"),
    ("inbox", "Inbox", "is:open @none"),
    ("done", "Done", "is:done"),
    ("ready", "Ready", "is:ready"),
    ("blocked", "Blocked", "is:blocked"),
    ("snoozed", "Snoozed", "is:snoozed"),
]


# ---------------------------------------------------------------------------
# data store
# ---------------------------------------------------------------------------


def now_iso():
    return dt.datetime.now().replace(microsecond=0).isoformat()


def blank_task(tid, title):
    return {
        "id": tid, "title": title, "done": False, "prio": 0, "due": None, "tags": [],
        "project": "", "notes": "", "created": now_iso(), "done_at": None,
        "parent": None, "folded": False, "repeat": "", "est": 0,
        "deps": [], "snooze": "",
    }


class Store:
    def __init__(self, path):
        self.path = path
        self.tasks = []
        self.next_id = 1
        self.undo_stack = []
        self.redo_stack = []
        self.mtime = 0.0
        self._map = None
        self.active = None
        self.done_log = []
        self.time_log = []
        self.habits = []
        self.projects = {}
        self.journal = {}
        self.goals = []
        self.load()

    def load(self):
        self._map = None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.mtime = os.path.getmtime(self.path)
        except (OSError, ValueError):
            return
        self.tasks = []
        for raw in data.get("tasks", []):
            t = blank_task(raw.get("id", 0), "")
            t.update(raw)
            self.tasks.append(t)
        self.next_id = max([data.get("next_id", 1)] + [t["id"] + 1 for t in self.tasks])
        self.done_log = data.get("done_log", [])
        self.time_log = data.get("time_log", [])
        self.active = data.get("active")
        self.habits = data.get("habits", [])
        self.projects = data.get("projects", {})
        self.journal = data.get("journal", {})
        self.goals = data.get("goals", [])

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".todos-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 2, "next_id": self.next_id, "tasks": self.tasks, "done_log": self.done_log,
                           "time_log": self.time_log, "active": self.active, "habits": self.habits,
                           "projects": self.projects, "journal": self.journal, "goals": self.goals}, fh, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)
            self.mtime = os.path.getmtime(self.path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    def changed_on_disk(self):
        try:
            return os.path.getmtime(self.path) != self.mtime
        except OSError:
            return False

    def get(self, tid):
        if self._map is None:
            self._map = {t["id"]: t for t in self.tasks}
        return self._map.get(tid)

    def invalidate(self):
        self._map = None

    def snap(self):
        self.undo_stack.append((copy.deepcopy(self.tasks), self.next_id, copy.deepcopy(self.done_log), copy.deepcopy((self.habits, self.projects, self.journal, self.goals))))
        del self.undo_stack[:-200]
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append((copy.deepcopy(self.tasks), self.next_id, copy.deepcopy(self.done_log), copy.deepcopy((self.habits, self.projects, self.journal, self.goals))))
        self.tasks, self.next_id, self.done_log, ex = self.undo_stack.pop()
        self.habits, self.projects, self.journal, self.goals = ex
        self.invalidate()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append((copy.deepcopy(self.tasks), self.next_id, copy.deepcopy(self.done_log), copy.deepcopy((self.habits, self.projects, self.journal, self.goals))))
        self.tasks, self.next_id, self.done_log, ex = self.redo_stack.pop()
        self.habits, self.projects, self.journal, self.goals = ex
        self.invalidate()
        return True

    def children(self, tid):
        return [t for t in self.tasks if t["parent"] == tid]

    def descendants(self, tid):
        out, stack = [], [tid]
        while stack:
            cur = stack.pop()
            for c in self.children(cur):
                out.append(c)
                stack.append(c["id"])
        return out

    def add(self, title, parent=None, at_top=False, after=None):
        t = blank_task(self.next_id, title)
        t["parent"] = parent
        self.next_id += 1
        if at_top:
            self.tasks.insert(0, t)
        elif after is not None:
            idx = self.tasks.index(after) + 1
            self.tasks.insert(idx, t)
        else:
            self.tasks.append(t)
        self.invalidate()
        return t

    def delete(self, ids):
        doomed = set(ids)
        for tid in list(ids):
            doomed.update(d["id"] for d in self.descendants(tid))
        self.tasks = [t for t in self.tasks if t["id"] not in doomed]
        for t in self.tasks:
            if t.get("deps"):
                t["deps"] = [d for d in t["deps"] if d not in doomed]
        self.invalidate()
        return doomed


# ---------------------------------------------------------------------------
# config and state
# ---------------------------------------------------------------------------


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def read_toml(path, warn):
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, ValueError) as exc:
        warn("config error in %s: %s" % (os.path.basename(path), exc))
        return {}


def load_config(path, warn, profile=None):
    cfg = copy.deepcopy(DEFAULTS)
    if not os.path.exists(path):
        with contextlib.suppress(OSError):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(CONFIG_TEMPLATE)
        return cfg
    if tomllib is None:
        warn("config ignored: python 3.11+ or tomli needed")
        return cfg
    user = read_toml(path, warn)
    base = os.path.dirname(path)
    merged = {}
    for inc in user.get("include", []) if isinstance(user.get("include"), list) else []:
        ip = os.path.join(base, os.path.expanduser(str(inc)))
        if os.path.exists(ip):
            merged = deep_merge(merged, read_toml(ip, warn))
    merged = deep_merge(merged, user)
    if profile:
        pp = os.path.join(base, "config-%s.toml" % profile)
        if os.path.exists(pp):
            merged = deep_merge(merged, read_toml(pp, warn))
        else:
            warn("no profile file: " + pp)
    return deep_merge(cfg, merged)


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh)


# ---------------------------------------------------------------------------
# colors
# ---------------------------------------------------------------------------

BASE16 = [
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
    (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
    (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
]
NAMES = {"black": 0, "red": 1, "green": 2, "yellow": 3, "blue": 4, "magenta": 5, "cyan": 6, "white": 7}


def xterm_rgb(n):
    if n < 16:
        return BASE16[n]
    if n < 232:
        n -= 16

        def v(c):
            return 0 if c == 0 else 55 + 40 * c

        return (v(n // 36), v((n // 6) % 6), v(n % 6))
    g = 8 + 10 * (n - 232)
    return (g, g, g)


def nearest(rgb, limit):
    best, bd = 0, 10 ** 9
    for i in range(limit):
        r, g, b = xterm_rgb(i)
        d = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if d < bd:
            best, bd = i, d
    return best


@functools.lru_cache(maxsize=None)
def color_index(spec, ncolors):
    if spec is None or spec == "default" or spec == -1:
        return -1
    if isinstance(spec, int):
        idx = spec
    elif isinstance(spec, str) and spec.startswith("#") and len(spec) == 7:
        rgb = tuple(int(spec[i:i + 2], 16) for i in (1, 3, 5))
        return nearest(rgb, min(ncolors, 256))
    elif isinstance(spec, str) and spec.lower() in NAMES:
        idx = NAMES[spec.lower()]
    else:
        return -1
    if idx >= ncolors:
        return nearest(xterm_rgb(idx), ncolors)
    return idx


# ---------------------------------------------------------------------------
# key handling
# ---------------------------------------------------------------------------

SPECIAL_KEYS = {
    curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left",
    curses.KEY_RIGHT: "right", curses.KEY_HOME: "home", curses.KEY_END: "end",
    curses.KEY_PPAGE: "pgup", curses.KEY_NPAGE: "pgdn", curses.KEY_DC: "delete",
    curses.KEY_BACKSPACE: "backspace", curses.KEY_ENTER: "enter",
    curses.KEY_BTAB: "shift-tab", curses.KEY_RESIZE: "resize", curses.KEY_MOUSE: "mouse",
    curses.KEY_SR: "shift-up", curses.KEY_SF: "shift-down",
}
for _i in range(1, 13):
    SPECIAL_KEYS[curses.KEY_F0 + _i] = "f%d" % _i


def key_name(k):
    """Return (name, printable_char_or_None)."""
    if isinstance(k, str):
        if k in ("\n", "\r"):
            return "enter", None
        if k == "\t":
            return "tab", None
        if k == "\x1b":
            return "esc", None
        if k in ("\x7f", "\b"):
            return "backspace", None
        o = ord(k)
        if o < 32:
            return "ctrl-" + chr(o + 96), None
        if k == " ":
            return "space", " "
        return k, k
    return SPECIAL_KEYS.get(k, "key-%d" % k), None


# ---------------------------------------------------------------------------
# durations, fuzzy matching, links, stats math
# ---------------------------------------------------------------------------


def parse_duration(s):
    """Parse 90, 90m, 1h30m, 45s into seconds. A bare number means minutes."""
    s = s.strip().lower()
    if re.fullmatch(r"\d+", s):
        return int(s) * 60
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", s)
    if not s or not m or not any(m.groups()):
        raise ValueError("bad duration: " + s)
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se


def fmt_duration(secs, clock=False):
    secs = max(0, int(secs))
    if clock:
        h, r = divmod(secs, 3600)
        m, s = divmod(r, 60)
        return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)
    if secs < 60:
        return "%ds" % secs
    h, r = divmod(secs, 3600)
    m = r // 60
    if h:
        return "%dh%02dm" % (h, m) if m else "%dh" % h
    return "%dm" % m


def _boundary(tl, i):
    return i == 0 or tl[i - 1] in " -_/@#:.[]()"


def fuzzy_score(query, text):
    """Subsequence match. Returns (score, positions) or None."""
    q, tl = query.lower(), text.lower()
    if not q:
        return 0, []
    best = None
    start = -1
    for _ in range(8):
        start = tl.find(q[0], start + 1)
        if start < 0:
            break
        pos = [start]
        score = 10 + (8 if _boundary(tl, start) else 0)
        prev, ok = start, True
        for ch in q[1:]:
            nxt = tl.find(ch, prev + 1)
            if nxt < 0:
                ok = False
                break
            if nxt == prev + 1:
                score += 12
            else:
                score -= min(5, nxt - prev - 1)
                if _boundary(tl, nxt):
                    score += 8
            pos.append(nxt)
            prev = nxt
        if ok and (best is None or score > best[0]):
            best = (score, pos)
    if best is None:
        return None
    return best[0] - len(text) // 8, best[1]


LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
URL_RE = re.compile(r"https?://[^\s<>\[\]()\"']+")


def resolve_ref(store, raw):
    raw = raw.strip()
    num = raw.lstrip("#")
    if num.isdigit():
        return store.get(int(num))
    low = raw.lower()
    for test in (lambda s: s == low, lambda s: s.startswith(low), lambda s: low in s):
        for t in store.tasks:
            if test(t["title"].lower()):
                return t
    return None


def task_links(store, t):
    """Return [(kind, target, raw)] where kind is task, broken or url."""
    out, seen = [], set()
    for text in (t["title"], t["notes"]):
        for m in LINK_RE.finditer(text):
            tgt = resolve_ref(store, m.group(1))
            if tgt is t:
                continue
            out.append(("task" if tgt else "broken", tgt, m.group(1)))
        for m in URL_RE.finditer(text):
            u = m.group(0).rstrip(".,;:!?")
            if u not in seen:
                seen.add(u)
                out.append(("url", u, u))
    return out


def backlinks(store, t):
    return [o for o in store.tasks if o is not t
            and any(k == "task" and tg is t for k, tg, _ in task_links(store, o))]


def render_refs(store, text, arrow):
    if "[[" not in text:
        return text

    def sub(m):
        tg = resolve_ref(store, m.group(1))
        return arrow + " " + tg["title"] if tg else m.group(0)

    return LINK_RE.sub(sub, text)


def streak_info(iso_days, td):
    """Return (current streak, best streak) from an iterable of iso dates."""
    days = sorted({dt.date.fromisoformat(x) for x in iso_days})
    if not days:
        return 0, 0
    best = run = 1
    for a, b in zip(days, days[1:]):
        run = run + 1 if (b - a).days == 1 else 1
        best = max(best, run)
    have = set(days)
    d = td if td in have else td - dt.timedelta(days=1)
    cur = 0
    while d in have:
        cur += 1
        d -= dt.timedelta(days=1)
    return cur, best


BIG_DIGITS = {
    "0": ["###", "# #", "# #", "# #", "###"],
    "1": [" # ", "## ", " # ", " # ", "###"],
    "2": ["###", "  #", "###", "#  ", "###"],
    "3": ["###", "  #", "###", "  #", "###"],
    "4": ["# #", "# #", "###", "  #", "  #"],
    "5": ["###", "#  ", "###", "  #", "###"],
    "6": ["###", "#  ", "###", "# #", "###"],
    "7": ["###", "  #", "  #", "  #", "  #"],
    "8": ["###", "# #", "###", "# #", "###"],
    "9": ["###", "# #", "###", "  #", "###"],
    ":": [" ", "#", " ", "#", " "],
}
CHECK_FRAMES = ["○", "◔", "◑", "◕", "●"]
CHECK_FRAMES_ASCII = ["[ ]", "[.]", "[o]", "[x]"]
SPINNER = ["◐", "◓", "◑", "◒"]
SPINNER_ASCII = ["|", "/", "-", "\\"]
BLOCKS = " ▁▂▃▄▅▆▇█"


# ---------------------------------------------------------------------------
# dependencies, snooze, sorting, rules, habits, goals, projects, estimates
# ---------------------------------------------------------------------------

FAR = "9999-99-99"


def is_snoozed(t, td):
    s = t.get("snooze")
    return bool(s) and not t["done"] and s > td.isoformat()


def blockers(store, t):
    out = []
    for i in t.get("deps", []):
        d = store.get(i)
        if d is not None and not d["done"]:
            out.append(d)
    return out


def waiting_on(store, t):
    return [o for o in store.tasks if not o["done"] and t["id"] in o.get("deps", [])]


def would_cycle(store, tid, dep_id):
    seen, stack = set(), [dep_id]
    while stack:
        cur = stack.pop()
        if cur == tid:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        o = store.get(cur)
        if o:
            stack.extend(o.get("deps", []))
    return False


SORT_BUILTIN = {
    "manual": "",
    "priority": "done,-prio,due",
    "due": "done,due,-prio",
    "created": "done,-created",
    "alpha": "done,title",
}


def sort_value(t, key, ctx):
    if key == "done":
        return t["done"]
    if key == "prio":
        return t["prio"]
    if key == "due":
        return t["due"] or FAR
    if key == "created":
        return t["created"]
    if key == "title":
        return t["title"].lower()
    if key == "project":
        return t["project"].lower() or "~"
    if key == "tags":
        return " ".join(t["tags"])
    if key == "est":
        return t.get("est", 0)
    if key == "time":
        return ctx["time_by"].get(t["id"], 0)
    if key == "id":
        return t["id"]
    if key == "blocked":
        return bool(blockers(ctx["store"], t))
    if key == "snooze":
        return t.get("snooze") or FAR
    if key == "notes":
        return len(t["notes"])
    return 0


def sort_items(items, spec, ctx):
    keys = [k for k in spec.replace(" ", "").split(",") if k]
    for k in reversed(keys):
        name = k.lstrip("-+")
        items.sort(key=lambda t, name=name: sort_value(t, name, ctx), reverse=k.startswith("-"))
    return items


def compile_rules(rules, store):
    out = []
    for r in rules:
        if isinstance(r, dict):
            out.append((compile_query(r.get("when", ""), store), r))
    return out


def match_rules(rules, t, td):
    merged = {}
    for pred, spec in rules:
        if pred(t, td):
            for k in ("fg", "bg", "bold", "dim", "prefix", "suffix"):
                if k in spec:
                    merged[k] = spec[k]
    return merged


def template_vars(spec):
    names = []
    texts = [spec.get("title", ""), spec.get("notes", "")] + list(spec.get("subtasks", []))
    for text in texts:
        for m in re.finditer(r"\{(\w+)\}", str(text)):
            n = m.group(1)
            if n not in ("date", "today", "weekday") and n not in names:
                names.append(n)
    return names


def fill_template(text, values):
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), str(text))


# ----- habits -----

DAY_RE = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*"


def parse_habit(text):
    """Quick syntax: Name daily | 3/week | mon,wed,fri | weekdays | x8"""
    out = {"name": "", "kind": "daily", "target": 1, "days": []}
    words = []
    for tok in text.split():
        low = tok.lower().strip(",")
        m = re.fullmatch(r"(\d+)x?/(?:w|wk|week|weekly)", low)
        if m:
            out["kind"], out["target"] = "weekly", max(1, int(m.group(1)))
            continue
        m = re.fullmatch(r"x(\d+)|(\d+)x", low)
        if m:
            out["target"] = max(1, int(m.group(1) or m.group(2)))
            continue
        if low in ("daily", "everyday", "every-day"):
            out["kind"], out["days"] = "daily", []
            continue
        if low == "weekdays":
            out["kind"], out["days"] = "days", [0, 1, 2, 3, 4]
            continue
        if low == "weekends":
            out["kind"], out["days"] = "days", [5, 6]
            continue
        if re.fullmatch(DAY_RE + "(," + DAY_RE + ")*", low):
            out["kind"] = "days"
            out["days"] = sorted({WEEKDAYS.index(p[:3]) for p in low.split(",")})
            continue
        words.append(tok)
    out["name"] = " ".join(words)
    return out


def serialize_habit(h):
    parts = [h["name"]]
    if h["kind"] == "weekly":
        parts.append("%d/week" % h["target"])
    else:
        if h["kind"] == "days":
            parts.append(",".join(WEEKDAYS[d] for d in h["days"]))
        if h["target"] > 1:
            parts.append("x%d" % h["target"])
    return " ".join(parts)


def habit_schedule_label(h):
    if h["kind"] == "weekly":
        return "%d/wk" % h["target"]
    base = "daily"
    if h["kind"] == "days":
        if h["days"] == [0, 1, 2, 3, 4]:
            base = "weekdays"
        elif h["days"] == [5, 6]:
            base = "weekends"
        else:
            base = "".join(WEEKDAYS[d][0].upper() for d in h["days"])
    return base + (" x%d" % h["target"] if h["target"] > 1 else "")


def blank_habit(hid, name):
    return {"id": hid, "name": name, "kind": "daily", "target": 1, "days": [], "created": now_iso(),
            "archived": False, "log": {}, "note": ""}


def habit_scheduled(h, d):
    return d.weekday() in h["days"] if h["kind"] == "days" else True


def habit_count(h, d):
    return h["log"].get(d.isoformat(), 0)


def habit_day_met(h, d):
    need = 1 if h["kind"] == "weekly" else h["target"]
    return habit_count(h, d) >= need


def week_start(d):
    return d - dt.timedelta(days=d.weekday())


def habit_week_total(h, d):
    ws = week_start(d)
    return sum(habit_count(h, ws + dt.timedelta(days=i)) for i in range(7))


def habit_first_day(h):
    first = dt.date.fromisoformat(h["created"][:10])
    if h["log"]:
        try:
            first = min(first, dt.date.fromisoformat(min(h["log"])))
        except ValueError:
            pass
    return first


def habit_streak(h, td):
    """Return (current, best). Unit is days, or weeks for weekly habits."""
    start = habit_first_day(h)
    if h["kind"] == "weekly":
        weeks, w = [], week_start(start)
        while w <= week_start(td):
            weeks.append(habit_week_total(h, w) >= h["target"])
            w += dt.timedelta(days=7)
        cur = 0
        for i in range(len(weeks) - 1, -1, -1):
            if weeks[i]:
                cur += 1
            elif i == len(weeks) - 1:
                continue
            else:
                break
        best = run = 0
        for m in weeks:
            run = run + 1 if m else 0
            best = max(best, run)
        return cur, best
    cur, d = 0, td
    if habit_scheduled(h, d) and not habit_day_met(h, d):
        d -= dt.timedelta(days=1)
    while d >= start:
        if habit_scheduled(h, d):
            if habit_day_met(h, d):
                cur += 1
            else:
                break
        d -= dt.timedelta(days=1)
    best = run = 0
    d = start
    while d <= td:
        if habit_scheduled(h, d):
            if habit_day_met(h, d):
                run += 1
                best = max(best, run)
            elif d < td:
                run = 0
        d += dt.timedelta(days=1)
    return cur, best


def habit_rate(h, td, days=30):
    start = max(habit_first_day(h), td - dt.timedelta(days=days - 1))
    if h["kind"] == "weekly":
        met = total = 0
        w = week_start(start)
        while w + dt.timedelta(days=6) < td:
            if w >= week_start(habit_first_day(h)):
                total += 1
                met += habit_week_total(h, w) >= h["target"]
            w += dt.timedelta(days=7)
        return (met / float(total)) if total else None
    met = total = 0
    d = start
    while d <= td:
        if habit_scheduled(h, d):
            ok = habit_day_met(h, d)
            if d < td or ok:
                total += 1
                met += ok
        d += dt.timedelta(days=1)
    return (met / float(total)) if total else None


def habit_today(h, td):
    """Return (scheduled, done) for today."""
    if h["kind"] == "weekly":
        return True, habit_week_total(h, td) >= h["target"]
    if not habit_scheduled(h, td):
        return False, False
    return True, habit_day_met(h, td)


def habit_summary(store, td):
    done = total = 0
    for h in store.habits:
        if h.get("archived"):
            continue
        sched, ok = habit_today(h, td)
        if sched:
            total += 1
            done += ok
    return done, total


# ----- journal -----

DEFAULT_JOURNAL_TEMPLATE = (
    "# {weekday}, {date}\n\n## Done\n{done}\n\n## Notes\n\n## Tomorrow\n"
)


def done_on(store, iso):
    out, seen = [], set()
    for e in store.done_log:
        if e["t"][:10] == iso and e["id"] not in seen:
            seen.add(e["id"])
            t = store.get(e["id"])
            title = t["title"] if t else e.get("n", "")
            if title:
                out.append(title)
    return out


def time_on(store, iso):
    return sum(e["s"] for e in store.time_log if e["t"][:10] == iso)


def journal_vars(store, date):
    iso = date.isoformat()
    done = done_on(store, iso)
    habit_lines = []
    for h in store.habits:
        if h.get("archived") or not habit_scheduled(h, date):
            continue
        habit_lines.append("- [%s] %s" % ("x" if habit_day_met(h, date) else " ", h["name"]))
    open_ = [t for t in store.tasks if not t["done"]]
    return {
        "date": iso,
        "weekday": date.strftime("%A"),
        "done": "\n".join("- " + x for x in done) or "- (nothing logged)",
        "done_count": str(len(done)),
        "time": fmt_duration(time_on(store, iso)),
        "open": str(len(open_)),
        "overdue": str(sum(1 for t in open_ if t["due"] and t["due"] < iso)),
        "habits": "\n".join(habit_lines) or "- (no habits)",
    }


def word_count(text):
    return len(text.split())


# ----- estimates -----


def est_samples(store):
    time_by = collections.Counter()
    for e in store.time_log:
        time_by[e["id"]] += e["s"]
    last = {}
    for e in store.done_log:
        last[e["id"]] = e
    out = []
    for tid, e in last.items():
        t = store.get(tid)
        est = e.get("est") or (t.get("est", 0) if t else 0)
        act = time_by.get(tid, 0)
        if est > 0 and act >= 60:
            out.append({"id": tid, "title": t["title"] if t else e.get("n", "?"),
                        "project": t["project"] if t else e.get("p", ""),
                        "est": est, "act": act, "date": e["t"][:10]})
    out.sort(key=lambda s: s["date"])
    return out


def calibration(samples, window=30):
    recent = samples[-window:]
    if not recent:
        return {"n": 0, "median": 1.0, "mean": 1.0, "within": 0.0}
    ratios = sorted(s["act"] / float(s["est"]) for s in recent)
    mid = len(ratios) // 2
    median = ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2.0
    within = sum(1 for r in ratios if 0.75 <= r <= 1.25) / float(len(ratios))
    return {"n": len(ratios), "median": median, "mean": sum(ratios) / len(ratios), "within": within}


# ----- goals and projects -----


def _entry_task(store, e):
    t = store.get(e["id"])
    if t:
        return t
    fake = blank_task(e["id"], e.get("n", ""))
    fake.update(done=True, project=e.get("p", ""), tags=list(e.get("g", [])), est=e.get("est", 0))
    return fake


def goal_range(g, td):
    start = g.get("start") or td.isoformat()
    due = g.get("due") or ""
    return start, due


def goal_progress(store, g, td):
    kind = g.get("kind", "manual")
    if kind == "manual":
        ms = g.get("milestones", [])
        done = sum(1 for m in ms if m.get("done"))
        total = len(ms)
        return {"cur": done, "total": total, "frac": (done / float(total)) if total else 0.0,
                "label": "%d/%d milestones" % (done, total)}
    f = compile_query(g.get("query", ""), store)
    start, due = goal_range(g, td)
    if kind == "tasks":
        match = [t for t in store.tasks if f(t, td)]
        done = sum(1 for t in match if t["done"])
        total = len(match)
        return {"cur": done, "total": total, "frac": (done / float(total)) if total else 0.0,
                "label": "%d/%d tasks" % (done, total)}
    target = float(g.get("target") or 1)
    if kind == "count":
        cur = 0
        for e in store.done_log:
            day = e["t"][:10]
            if day >= start and (not due or day <= due) and f(_entry_task(store, e), td):
                cur += 1
        return {"cur": cur, "total": target, "frac": min(1.0, cur / target), "label": "%d/%d done" % (cur, target)}
    cur = 0.0
    for e in store.time_log:
        day = e["t"][:10]
        if day >= start and (not due or day <= due):
            if f(_entry_task(store, {"id": e["id"], "p": e.get("p", "")}), td):
                cur += e["s"]
    hours = cur / 3600.0
    return {"cur": hours, "total": target, "frac": min(1.0, hours / target),
            "label": "%.1f/%.1f h" % (hours, target)}


def goal_pace(g, frac, td):
    """Return (status, diff) comparing progress with the linear schedule."""
    if frac >= 1.0:
        return "done", 0.0
    due = g.get("due")
    if not due:
        return "", 0.0
    try:
        d_due = dt.date.fromisoformat(due)
        d_start = dt.date.fromisoformat(g.get("start") or td.isoformat())
    except ValueError:
        return "", 0.0
    if td > d_due:
        return "overdue", 0.0
    span = max(1, (d_due - d_start).days)
    expected = min(1.0, max(0.0, (td - d_start).days / float(span)))
    diff = frac - expected
    if diff > 0.1:
        return "ahead", diff
    if diff < -0.1:
        return "behind", diff
    return "on pace", diff


def goal_series(store, g, td):
    """Cumulative progress per day from start to today (or due) for count and time goals."""
    kind = g.get("kind")
    if kind not in ("count", "time"):
        return []
    start, due = goal_range(g, td)
    try:
        d0 = dt.date.fromisoformat(start)
    except ValueError:
        return []
    d1 = min(td, dt.date.fromisoformat(due)) if due else td
    if d1 < d0:
        return []
    f = compile_query(g.get("query", ""), store)
    per = collections.Counter()
    if kind == "count":
        for e in store.done_log:
            if f(_entry_task(store, e), td):
                per[e["t"][:10]] += 1
    else:
        for e in store.time_log:
            if f(_entry_task(store, {"id": e["id"], "p": e.get("p", "")}), td):
                per[e["t"][:10]] += e["s"] / 3600.0
    out, run, d = [], 0.0, d0
    while d <= d1:
        run += per.get(d.isoformat(), 0)
        out.append(run)
        d += dt.timedelta(days=1)
    return out


def project_stats(store, name, td):
    tasks = [t for t in store.tasks if t["project"] == name]
    open_ = [t for t in tasks if not t["done"]]
    done = [t for t in tasks if t["done"]]
    tiso = td.isoformat()
    time_by = collections.Counter()
    for e in store.time_log:
        time_by[e["id"]] += e["s"]
    tracked = sum(time_by.get(t["id"], 0) for t in tasks)
    est_left = sum(max(0, t.get("est", 0) - time_by.get(t["id"], 0)) for t in open_)
    recent = sum(1 for e in store.done_log if e.get("p") == name and e["t"][:10] >= (td - dt.timedelta(days=13)).isoformat())
    velocity = recent / 14.0
    eta = None
    if open_ and velocity > 0:
        eta = td + dt.timedelta(days=int(math.ceil(len(open_) / velocity)))
    stamps = [t["created"] for t in tasks] + [t["done_at"] for t in done if t["done_at"]]
    stamps += [e["t"] for e in store.done_log if e.get("p") == name]
    stamps += [e["t"] for e in store.time_log if e.get("p") == name]
    last = max(stamps)[:10] if stamps else ""
    meta = store.projects.get(name, {})
    due = meta.get("due", "")
    status = meta.get("status", "active")
    total = len(tasks)
    if status == "paused":
        health = "paused"
    elif total and not open_:
        health = "done"
    elif due and due < tiso and open_:
        health = "overdue"
    elif due and eta and eta.isoformat() > due:
        health = "at risk"
    elif open_ and last and (td - dt.date.fromisoformat(last)).days > 21:
        health = "stale"
    else:
        health = "on track"
    return {
        "name": name, "total": total, "done": len(done), "open": len(open_),
        "frac": (len(done) / float(total)) if total else 0.0,
        "overdue": sum(1 for t in open_ if t["due"] and t["due"] < tiso),
        "blocked": sum(1 for t in open_ if blockers(store, t)),
        "snoozed": sum(1 for t in open_ if is_snoozed(t, td)),
        "tracked": tracked, "est_left": est_left, "velocity": velocity, "eta": eta,
        "last": last, "due": due, "status": status, "health": health,
        "desc": meta.get("desc", ""),
    }


def project_names(store):
    names = {t["project"] for t in store.tasks if t["project"]}
    names.update(store.projects)
    return sorted(names, key=str.lower)




# ---------------------------------------------------------------------------
# settings panel schema and helpers
# ---------------------------------------------------------------------------

HOOK_EVENTS = {
    "on_done": "A task was completed.",
    "on_add": "A task was added.",
    "on_delete": "A task was deleted.",
    "on_note": "A note was saved or added.",
    "on_snooze": "A task was snoozed.",
    "on_wake": "A snoozed task woke up.",
    "on_habit": "A habit was logged.",
    "on_journal": "A journal entry was saved.",
    "on_focus_start": "A focus phase started.",
    "on_focus_end": "A focus phase ended.",
}
STRING_KEYS = {"app_name": "Name shown in the header.", "empty": "Text for an empty list.",
               "add_title": "Title of the add task prompt."}
COLUMN_CHOICES = ["check", "prio", "id", "title", "est", "tags", "project", "time", "due", "deps", "snooze", "created"]
SCREEN_CHOICES = ["list", "journal", "habits", "projects", "stats", "calendar", "agenda"]
ROLE_DOC = {
    "bg": "Main background.", "fg": "Normal text.", "dim": "Hints and secondary text.",
    "accent": "Highlights, titles and the cursor.", "accent2": "Secondary highlight.",
    "sel_bg": "Background of the selected row.", "done": "Completed tasks.",
    "p1": "Low priority.", "p2": "Medium priority.", "p3": "High priority.",
    "overdue": "Overdue dates.", "today": "Due today and warnings.", "soon": "Due soon.",
    "tag": "Tags.", "project": "Projects.", "border": "Lines and boxes.",
    "bar_bg": "Header and footer background.", "ok": "Success and progress.", "err": "Errors.",
}

RECORD_FIELDS = {
    "views": [("name", "Name", "text"), ("query", "Filter query", "text"), ("sort", "Sort", "choice", "sorts"),
              ("columns", "Columns", "list"), ("icon", "Icon", "text"), ("show_done", "Show done tasks", "tri")],
    "rules": [("when", "When (filter query)", "text"), ("fg", "Text color", "text"), ("bg", "Background", "text"),
              ("bold", "Bold", "bool"), ("dim", "Dim", "bool"), ("prefix", "Prefix", "text"),
              ("suffix", "Suffix", "text")],
    "templates": [("name", "Name", "text"), ("key", "Shortcut key", "text"), ("title", "Task title", "text"),
                  ("notes", "Notes", "multiline"), ("subtasks", "Subtasks (one per line)", "lines"),
                  ("tags", "Tags", "list"), ("project", "Project", "text"), ("prio", "Priority 0 to 3", "int"),
                  ("est", "Estimate", "text"), ("due", "Due", "text"), ("repeat", "Repeat", "text")],
    "actions": [("name", "Name", "text"), ("key", "Shortcut key", "text"), ("cmd", "Shell command", "text"),
                ("mode", "Run mode", "choice", ["bg", "fg", "capture"]), ("confirm", "Ask first", "bool"),
                ("reload", "Reload tasks after", "bool"), ("pause", "Wait for enter (fg mode)", "bool")],
}


def _s(key, label, kind, desc, **kw):
    d = {"key": key, "label": label, "kind": kind, "desc": desc}
    d.update(kw)
    return d


def _node(name, items=None, children=None, dyn=None, blurb=""):
    return {"name": name, "items": items or [], "children": children or [], "dyn": dyn, "blurb": blurb}


def build_settings_tree():
    general = [
        _s("start_screen", "Start Screen", "choice", "Screen synth opens on launch.", choices=SCREEN_CHOICES),
        _s("sort", "Default Sort", "choice", "Order of the task list. Custom sorts appear here too.",
           choices=lambda app: app.sort_names()),
        _s("week_start", "Week Starts On", "choice", "First day of the week in the calendar and weekly habits.",
           choices=["mon", "sun"]),
        _s("date_format", "Date Format", "text", "strftime format for dates in the list, for example %d/%m or %b %d."),
        _s("mouse", "Mouse", "bool", "Click, double click and wheel support. Takes effect on next launch."),
        _s("open_cmd", "Open Links With", "text", "Command that opens links. Empty uses xdg-open."),
        _s("copy_cmd", "Clipboard Command", "text", "Command that receives text for the copy key. Empty tries wl-copy, xclip, xsel, pbcopy."),
    ]
    theme = [
        _s("theme", "Theme", "choice", "Color theme. Previews live while you move through the list.",
           choices=lambda app: app.theme_names()),
        _s("transparent", "Transparent Background", "bool", "Keep your terminal background instead of the theme background."),
        _s("exact_colors", "Exact Colors", "bool", "Redefine palette slots so hex colors are exact. Turn off if your terminal misbehaves."),
        _s("ascii", "ASCII Symbols", "bool", "Plain ascii symbols for limited fonts."),
        _s("border_style", "Border Style", "choice", "Line style of boxes and dividers.", choices=list(BORDERS)),
        _s("animations", "Animations", "bool", "Completion sweep, typewriter add, eased progress bar."),
        _s("anim_speed", "Animation Speed", "float", "1.0 is normal, 2.0 is twice as fast.", min=0.2, max=5.0),
    ]
    priorities = [
        _s("priority_labels", "Priority Names", "strlist", "Four names: none, low, medium, high. Comma separated.", count=4),
        _s("priority_symbols", "Priority Symbols", "strlist", "Symbols for each priority in the list, comma separated. Empty uses !, !!, !!!."),
        _s("priority_colors", "Priority Colors", "strlist", "Colors for none, low, medium, high. Hex values or theme role names."),
        _s("tag_colors", "Tag Colors", "records", "Give individual tags their own color.", dict=True, vlabel="Color", vkind="color"),
        _s("project_colors", "Project Colors", "records", "Give individual projects their own color.", dict=True, vlabel="Color", vkind="color"),
    ]
    tasklist = [
        _s("columns", "Columns", "order", "Which columns the list shows and in what order.", available=COLUMN_CHOICES, required=["title"]),
        _s("column_widths", "Column Width Limits", "records", "Maximum width for the tags and project columns.", dict=True,
           vlabel="Width", vkind="int", names=["tags", "project"]),
        _s("indent", "Subtask Indent", "int", "Spaces per subtask level.", min=0, max=8),
        _s("scrolloff", "Scroll Margin", "int", "Rows kept visible around the cursor.", min=0, max=10),
        _s("notes_inline", "Inline Notes", "bool", "Show the first line of a task's notes after its title."),
    ]
    sidebar = [
        _s("sidebar", "Show Sidebar", "bool", "The views, projects and tags panel."),
        _s("sidebar_width", "Sidebar Width", "int", "Columns used by the sidebar.", min=12, max=60),
        _s("sidebar_counts", "Sidebar Counts", "bool", "Show task counts next to each entry."),
        _s("sidebar_sections", "Sidebar Sections", "order", "Custom views, projects and tags. Order and visibility.",
           available=["custom", "projects", "tags"]),
        _s("sidebar_builtin", "Built-in Views", "order", "Which of the built-in views the sidebar lists.",
           available=["all", "today", "upcoming", "inbox", "done", "ready", "blocked", "snoozed"]),
    ]
    detail = [
        _s("detail", "Detail Pane", "choice", "Where the task detail pane sits.", choices=["right", "bottom", "off"]),
        _s("detail_size", "Detail Pane Size", "int", "Width when on the right, height when at the bottom.", min=8, max=90),
        _s("detail_sections", "Detail Tabs", "order", "Tabs of the detail pane, in order.", available=["notes", "info", "links"],
           required=["notes"]),
        _s("detail_tab", "Default Tab", "choice", "Tab that opens first.", choices=["notes", "info", "links"]),
    ]
    header = [
        _s("header_info", "Header Sort Info", "bool", "Show the sort and hide-done text in the header."),
        _s("header_progress", "Header Progress Bar", "bool", "Show done over total as a bar."),
        _s("header_habits", "Header Habits", "bool", "Show habits done today."),
        _s("header_clock", "Header Clock", "bool", "Show a clock in the header."),
        _s("clock_format", "Clock Format", "text", "strftime format for the clock."),
        _s("hints", "Footer Hints", "strlist", "Actions shown in the footer, for example add:new, toggle:done. Empty uses the default set."),
        _s("strings", "Wording", "records", "Rename pieces of the interface.", dict=True, vlabel="Text", vkind="text",
           names=list(STRING_KEYS)),
    ]
    tasks = [
        _s("show_done", "Show Done Tasks", "bool", "Keep finished tasks visible in the list."),
        _s("cascade_done", "Complete Subtasks", "bool", "Completing a parent completes its subtasks."),
        _s("confirm_delete", "Confirm Delete", "bool", "Ask before deleting tasks."),
        _s("blocked_done", "Finishing Blocked Tasks", "choice", "What happens when you complete a task that still has blockers.",
           choices=["warn", "allow", "deny"]),
        _s("snooze_hide", "Hide Snoozed Tasks", "bool", "Snoozed tasks leave every view except Snoozed."),
    ]
    notes = [
        _s("notes_editor", "Notes Editor", "choice", "Built-in editor, or your $VISUAL / $EDITOR.", choices=["builtin", "external"]),
        _s("note_stamp", "Note Timestamp", "text", "strftime format for quick note timestamps."),
        _s("journal_template", "Journal Template", "multiline",
           "Starting text of a new journal entry. Variables: {date} {weekday} {done} {done_count} {time} {open} {overdue} {habits}."),
    ]
    focus = [
        _s("focus_work", "Work Minutes", "int", "Length of a focus round.", min=1, max=180),
        _s("focus_break", "Short Break Minutes", "int", "Break after each round.", min=1, max=60),
        _s("focus_long", "Long Break Minutes", "int", "Break after a full set of rounds.", min=1, max=90),
        _s("focus_rounds", "Rounds Per Set", "int", "Work rounds before a long break.", min=1, max=12),
        _s("focus_auto", "Auto Start Next Phase", "bool", "Start the next phase without waiting."),
        _s("focus_bell", "Bell", "bool", "Ring the terminal bell when a phase ends."),
    ]
    views = [
        _s("views", "Custom Views", "records", "Saved filters that appear in the sidebar. Each can have its own sort, columns and icon.",
           fields="views"),
        _s("sorts", "Custom Sorts", "records", "Named sort recipes, for example done,-prio,due. Fields: done prio due created title project tags est time id blocked snooze notes. A leading - reverses.",
           dict=True, vlabel="Recipe", vkind="text"),
    ]
    rules = [
        _s("rules", "Styling Rules", "records", "Style tasks that match a filter. Later rules win.", fields="rules"),
    ]
    tpl = [
        _s("templates", "Task Templates", "records", "Create a task with subtasks and notes. {name} asks you for a value.", fields="templates"),
        _s("actions", "Shell Actions", "records", "Run a shell command on the selected task.", fields="actions"),
    ]
    hooks = [
        _s("hooks", "Event Hooks", "records", "Shell commands that run on events. Env: SYNTH_EVENT, SYNTH_TITLE, SYNTH_ID.",
           dict=True, vlabel="Command", vkind="text", names=list(HOOK_EVENTS)),
    ]
    advanced = [
        _s(None, "Config File", "action", "Open config.toml in your editor. Settings made here take priority over it.",
           run="open_config", button="Open"),
        _s(None, "Settings File", "action", "Open the file this panel saves to.", run="open_settings", button="Open"),
        _s(None, "Reload Files", "action", "Re-read config.toml and settings.json from disk.", run="reload_files", button="Reload"),
        _s(None, "Reset Everything", "action", "Remove every change made in this panel.", run="reset_all", button="Reset"),
    ]
    return [
        _node("General", general),
        _node("Appearance", children=[
            _node("Theme", theme), _node("Colors", dyn="colors", blurb="Edits the current theme. Built-in themes are copied into a custom theme."),
            _node("Symbols", dyn="symbols"), _node("Priorities and Tags", priorities)]),
        _node("Layout", children=[
            _node("Task List", tasklist), _node("Sidebar", sidebar), _node("Detail Pane", detail),
            _node("Header and Footer", header)]),
        _node("Tasks", tasks),
        _node("Notes and Journal", notes),
        _node("Focus", focus),
        _node("Keybindings", dyn="keys", blurb="Comma separated keys. Chords like g g work. Type none to unbind."),
        _node("Views and Sorts", views),
        _node("Styling Rules", rules),
        _node("Templates and Actions", tpl),
        _node("Hooks", hooks),
        _node("Advanced", advanced),
    ]


def load_settings(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings_file(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def parse_key_list(text):
    t = text.strip()
    if t.lower() in ("", "none", "-"):
        return []
    return [k.strip() for k in t.split(",") if k.strip()]


def color_valid(v):
    v = v.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return True
    if v.isdigit():
        return 0 <= int(v) <= 255
    return v.lower() in ("default", "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white") or v in THEME_ROLES


def clean_record(rec, fields):
    """Drop empty values so saved records stay small. Tri state fields keep an explicit False."""
    out = {}
    tri = {f[0] for f in fields if f[2] == "tri"}
    for k, v in rec.items():
        if v in ("", None, [], 0) and k not in tri:
            continue
        if v is False and k not in tri:
            continue
        if k in tri and v in ("", None):
            continue
        out[k] = v
    return out



# ---------------------------------------------------------------------------
# the app
# ---------------------------------------------------------------------------


class App:
    def __init__(self, scr, cfg, store, state, cfg_path, args):
        self.scr = scr
        self.cfg = cfg
        self.store = store
        self.state = state
        self.cfg_path = cfg_path
        self.args = args
        self.opts = {}
        self.pairs = {}
        self.next_pair = 1
        self.slots = {}
        self.next_slot = 16
        self.theme = {}
        self.keymap = {}
        self.view = "all"
        self.query = ""
        self.focus = "list"
        self.cur = 0
        self.cur_id = None
        self.top = 0
        self.side_idx = 0
        self.selected = set()
        self.rows = []
        self.msg = ""
        self.msg_kind = "dim"
        self.msg_until = 0.0
        self.last_click = (0.0, -1)
        self.geo = {}
        self.running = True
        self.anims = {}
        self.bar_disp = 0.0
        self.bar_busy = False
        self.jump_stack = []
        self.time_by = {}
        self.tick_override = None
        self.backdrop = self.draw
        self.sym = UNICODE_SYMBOLS
        self.settings_path = os.path.join(os.path.dirname(cfg_path), "settings%s.json" % (("-" + args.profile) if args.profile else ""))
        self.user_settings = load_settings(self.settings_path)
        self.pending = ""
        self.chord_prefixes = set()
        self.rules = []
        self.detail_scroll = 0
        self.detail_for = None
        self.detail_hits = []
        self.wake_day = ""
        with contextlib.suppress(curses.error):
            curses.use_default_colors()
        self.apply_config(first=True)

    # ----- configuration -----

    def apply_config(self, first=False):
        self.opts = deep_merge(self.cfg, {k: v for k, v in self.state.items() if k in DEFAULTS})
        for k, v in self.user_settings.items():
            if k in DEFAULTS:
                self.opts[k] = copy.deepcopy(v)
        if self.args.theme:
            self.opts["theme"] = self.args.theme
        keys = copy.deepcopy(DEFAULT_KEYS)
        for action, names in self.opts.get("keys", {}).items():
            if action in keys and isinstance(names, str):
                names = [names]
            if action in keys and isinstance(names, list):
                keys[action] = names
        self.keymap = {}
        for action, names in keys.items():
            for n in names:
                self.keymap[str(n)] = action
        self.sym = ASCII_SYMBOLS if self.opts["ascii"] else UNICODE_SYMBOLS
        bs = self.opts.get("border_style", "round")
        if bs in BORDERS and not self.opts["ascii"] and bs != "round":
            tl, tr, bl, br, hl, vl = BORDERS[bs]
            self.sym = dict(self.sym, corner_tl=tl, corner_tr=tr, corner_bl=bl, corner_br=br, hline=hl, vline=vl)
        self.sym = dict(self.sym, **self.opts.get("symbols", {}))
        for n, a in enumerate(self.custom_actions()):
            for k in ([a["key"]] if isinstance(a.get("key"), str) else list(a.get("key") or [])):
                self.keymap[str(k)] = "act:%d" % n
        for n, tp in enumerate(self.opts.get("templates", [])):
            if isinstance(tp, dict) and tp.get("name") and tp.get("key"):
                for k in ([tp["key"]] if isinstance(tp["key"], str) else list(tp["key"])):
                    self.keymap[str(k)] = "tpl:%d" % n
        self.chord_prefixes = set()
        for k in self.keymap:
            parts = k.split(" ")
            for j in range(1, len(parts)):
                self.chord_prefixes.add(" ".join(parts[:j]))
        self.rules = compile_rules(self.opts.get("rules", []), self.store)
        self.set_theme(self.opts["theme"])
        if first:
            wanted = self.args.view or self.state.get("view", "all")
            self.view = wanted if self.view_exists(wanted) else "all"

    def theme_names(self):
        return list(THEMES) + [n for n in self.opts.get("themes", {}) if n not in THEMES]

    def set_theme(self, name):
        if name not in THEMES and name not in self.opts.get("themes", {}):
            name = "tokyonight"
        self.opts["theme"] = name
        t = dict(THEMES["tokyonight"])
        user = self.opts.get("themes", {}).get(name, {})
        if user.get("inherit") in THEMES:
            t.update(THEMES[user["inherit"]])
        t.update(THEMES.get(name, {}))
        t.update({k: v for k, v in user.items() if k != "inherit"})
        if self.opts.get("transparent"):
            t["bg"] = "default"
        self.theme = t
        self.pairs = {}
        self.next_pair = 1
        self.slots = {}
        self.next_slot = 16
        self.scr.bkgd(" ", self.attr("fg", "bg"))

    def color(self, spec):
        """Resolve a color spec. Hex colors get a redefined palette slot when the
        terminal allows it, so they stay exact even if the terminal remaps its
        default 256 palette."""
        if (self.opts.get("exact_colors", True) and isinstance(spec, str) and spec.startswith("#")
                and len(spec) == 7 and curses.COLORS >= 256 and curses.can_change_color()):
            if spec in self.slots:
                return self.slots[spec]
            if self.next_slot < 256:
                r, g, b = (int(spec[i:i + 2], 16) * 1000 // 255 for i in (1, 3, 5))
                try:
                    curses.init_color(self.next_slot, r, g, b)
                except curses.error:
                    return color_index(spec, curses.COLORS)
                self.slots[spec] = self.next_slot
                self.next_slot += 1
                return self.slots[spec]
        return color_index(spec, curses.COLORS)

    def attr(self, fg="fg", bg="bg", bold=False, dim=False, reverse=False):
        fgc = self.color(self.theme.get(fg, fg))
        bgc = self.color(self.theme.get(bg, bg))
        key = (fgc, bgc)
        if key not in self.pairs:
            if self.next_pair >= curses.COLOR_PAIRS:
                return curses.A_BOLD if bold else 0
            try:
                curses.init_pair(self.next_pair, fgc, bgc)
            except curses.error:
                return curses.A_BOLD if bold else 0
            self.pairs[key] = self.next_pair
            self.next_pair += 1
        a = curses.color_pair(self.pairs[key])
        if bold:
            a |= curses.A_BOLD
        if dim:
            a |= curses.A_DIM
        if reverse:
            a |= curses.A_REVERSE
        return a

    def persist(self, key, value):
        if key in DEFAULTS:
            self.user_settings[key] = copy.deepcopy(value)
            self.state.pop(key, None)
            save_settings_file(self.settings_path, self.user_settings)
            save_state(self.state)
            return
        self.state[key] = value
        save_state(self.state)

    # ----- messages -----

    def say(self, text, kind="accent2", secs=3.0):
        self.msg, self.msg_kind, self.msg_until = text, kind, time.time() + secs

    # ----- views -----

    def view_defs(self):
        defs = [(k, label, q) for k, label, q in BUILTIN_VIEWS]
        for v in self.opts.get("views", []):
            if isinstance(v, dict) and v.get("name"):
                defs.append(("v:" + v["name"], v["name"], v.get("query", "")))
        return defs

    def view_query(self, key):
        for k, _, q in self.view_defs():
            if k == key:
                return q
        if key.startswith("p:"):
            return "@" + key[2:].replace(" ", "-")
        if key.startswith("t:"):
            return "#" + key[2:]
        return ""

    def view_exists(self, key):
        return any(i["key"] == key for i in self.sidebar_items() if not i["head"])

    def view_label(self, key):
        for item in self.sidebar_items():
            if item["key"] == key:
                return item["label"]
        return key

    def sidebar_items(self):
        td = today()
        tasks = self.store.tasks
        o = self.opts
        items = []
        any_deps = any(t.get("deps") for t in tasks)
        any_snooze = any(is_snoozed(t, td) for t in tasks)

        def count(q):
            f = compile_query(q, self.store)
            snz = "is:snoozed" in q
            return sum(1 for t in tasks if not t["done"] and f(t, td) and (snz or not self.snoozed_chain(t, td)))

        wanted = o.get("sidebar_builtin") or [k for k, _, _ in BUILTIN_VIEWS]
        for k, label, q in BUILTIN_VIEWS:
            if k not in wanted:
                continue
            if k in ("ready", "blocked") and not any_deps and self.view != k:
                continue
            if k == "snoozed" and not any_snooze and self.view != k:
                continue
            n = sum(1 for t in tasks if t["done"]) if k == "done" else count(q)
            items.append({"key": k, "label": label, "count": n, "head": False})
        sections = o.get("sidebar_sections") or ["custom", "projects", "tags"]
        for sec in sections:
            if sec in ("custom", "views"):
                custom = [v for v in o.get("views", []) if isinstance(v, dict) and v.get("name")]
                if custom:
                    items.append({"key": "", "label": "VIEWS", "count": 0, "head": True})
                    for v in custom:
                        icon = (v.get("icon", "") + " ") if v.get("icon") else ""
                        items.append({"key": "v:" + v["name"], "label": icon + v["name"],
                                      "count": count(v.get("query", "")), "head": False})
            elif sec == "projects":
                names = {t["project"] for t in tasks if t["project"] and not t["done"]}
                names.update(n for n, m in self.store.projects.items() if m.get("status", "active") == "active")
                projects = sorted(names, key=str.lower)
                if projects:
                    items.append({"key": "", "label": "PROJECTS", "count": 0, "head": True})
                    for p in projects:
                        items.append({"key": "p:" + p, "label": "@" + p,
                                      "count": count("@" + p.replace(" ", "-")), "head": False})
            elif sec == "tags":
                tags = sorted({g for t in tasks for g in t["tags"] if not t["done"]})
                if tags:
                    items.append({"key": "", "label": "TAGS", "count": 0, "head": True})
                    for g in tags:
                        items.append({"key": "t:" + g, "label": "#" + g, "count": count("#" + g), "head": False})
        if not o.get("sidebar_counts", True):
            for it in items:
                it["count"] = 0
        return items

    def set_view(self, key):
        self.view = key
        self.top = 0
        self.cur = 0
        self.cur_id = None
        self.persist("view", key)

    def cycle_view(self, step):
        keys = [i["key"] for i in self.sidebar_items() if not i["head"]]
        if self.view not in keys:
            self.set_view("all")
            return
        self.set_view(keys[(keys.index(self.view) + step) % len(keys)])

    # ----- rows -----

    def sort_key(self, t, idx):
        mode = self.opts["sort"]
        far = "9999-99-99"
        if mode == "priority":
            return (t["done"], -t["prio"], t["due"] or far, idx)
        if mode == "due":
            return (t["done"], t["due"] or far, -t["prio"], idx)
        if mode == "created":
            return (t["done"], [-ord(c) for c in t["created"]], idx)
        if mode == "alpha":
            return (t["done"], t["title"].lower(), idx)
        return (idx,)

    def rebuild(self):
        td = today()
        self.time_by = collections.Counter()
        for e in self.store.time_log:
            self.time_by[e["id"]] += e["s"]
        vq = compile_query(self.view_query(self.view), self.store)
        sq = compile_query(self.query, self.store)
        hide_done = not self.view_opt("show_done") and self.view != "done"
        qtxt = self.view_query(self.view) + " " + self.query
        show_snoozed = "is:snoozed" in qtxt or not self.opts.get("snooze_hide", True)
        order = {t["id"]: i for i, t in enumerate(self.store.tasks)}
        keep = {}
        for t in self.store.tasks:
            if hide_done and t["done"]:
                continue
            if not show_snoozed and self.snoozed_chain(t, td):
                continue
            if vq(t, td) and sq(t, td):
                keep[t["id"]] = t
        kids = {}
        roots = []
        for tid, t in keep.items():
            p = t["parent"]
            if p in keep:
                kids.setdefault(p, []).append(t)
            else:
                roots.append(t)

        def key(t):
            return self.sort_key(t, order[t["id"]])

        rows = []

        def walk(t, depth):
            rows.append((t, depth))
            if t["folded"] and not self.query:
                return
            for c in self.sorted_tasks(kids.get(t["id"], [])):
                walk(c, depth + 1)

        for r in self.sorted_tasks(roots):
            walk(r, 0)
        self.rows = rows
        self.selected &= set(keep)
        ids = [r[0]["id"] for r in rows]
        if self.cur_id in ids:
            self.cur = ids.index(self.cur_id)
        else:
            self.cur = max(0, min(self.cur, len(rows) - 1))
            self.cur_id = ids[self.cur] if ids else None
        self.keep_count = len(keep)
        self.keep_done = sum(1 for t in keep.values() if t["done"])

    def current(self):
        if 0 <= self.cur < len(self.rows):
            return self.rows[self.cur][0]
        return None

    def targets(self):
        if self.selected:
            return [t for t in self.store.tasks if t["id"] in self.selected]
        c = self.current()
        return [c] if c else []

    def move_cursor(self, delta, absolute=False):
        if not self.rows:
            return
        n = len(self.rows)
        self.cur = max(0, min(n - 1, delta if absolute else self.cur + delta))
        self.cur_id = self.rows[self.cur][0]["id"]

    # ----- mutations -----

    @contextlib.contextmanager
    def edit(self):
        self.store.snap()
        yield
        self.store.invalidate()
        self.store.save()

    def hook(self, event, task):
        cmd = self.opts.get("hooks", {}).get(event)
        if not cmd:
            return
        env = dict(os.environ, SYNTH_EVENT=event, SYNTH_TITLE=task["title"], SYNTH_ID=str(task["id"]))
        with contextlib.suppress(OSError):
            subprocess.Popen(cmd, shell=True, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def done_entry(self, t):
        return {"t": now_iso(), "id": t["id"], "p": t["project"], "n": t["title"], "g": list(t["tags"]),
                "est": t.get("est", 0)}

    def set_done(self, t, done):
        t["done"] = done
        t["done_at"] = now_iso() if done else None
        if done:
            self.store.done_log.append(self.done_entry(t))
            self.anim("done", t["id"], 0.65)
            if self.store.active and self.store.active["id"] == t["id"]:
                self.stop_tracking(False)
        else:
            log = self.store.done_log
            for i in range(len(log) - 1, -1, -1):
                if log[i]["id"] == t["id"]:
                    del log[i]
                    break

    def complete(self, t, done):
        if done and t["repeat"] and t["due"]:
            t["due"] = next_due(t["due"], t["repeat"]).isoformat()
            self.store.done_log.append(self.done_entry(t))
            self.anim("done", t["id"], 0.65)
            self.hook("on_done", t)
            return "next: " + t["due"]
        if t["done"] == done:
            return ""
        self.set_done(t, done)
        if done:
            self.hook("on_done", t)
        if self.opts["cascade_done"]:
            for d in self.store.descendants(t["id"]):
                if d["done"] != done:
                    self.set_done(d, done)
        return ""

    def act_toggle(self):
        ts = self.targets()
        if not ts:
            return
        make_done = not all(t["done"] for t in ts)
        if make_done and not self.blocked_gate(ts):
            return
        before = {o["id"] for o in self.store.tasks if not o["done"] and blockers(self.store, o)}
        note = ""
        with self.edit():
            for t in ts:
                note = self.complete(t, make_done) or note
        freed = [o for o in self.store.tasks if o["id"] in before and not blockers(self.store, o)] if make_done else []
        if freed:
            note = "unblocked: " + clip(freed[0]["title"], 30) + (" +%d" % (len(freed) - 1) if len(freed) > 1 else "")
        self.say(note or ("done" if make_done else "reopened"), "ok")

    def apply_parsed(self, t, p, new):
        if p["title"]:
            t["title"] = p["title"]
        t["tags"] = p["tags"]
        t["project"] = p["project"]
        t["prio"] = p["prio"]
        t["repeat"] = p["repeat"]
        t["est"] = p["est"]
        if p.get("notes"):
            t["notes"] = (t["notes"].rstrip() + "\n" if t["notes"].strip() else "") + p["notes"]
        if p["due"] is not UNSET:
            t["due"] = p["due"]
        elif not new:
            t["due"] = None

    def add_defaults(self, t):
        v = self.view
        if v.startswith("p:"):
            t["project"] = v[2:]
        elif v.startswith("t:"):
            t["tags"] = [v[2:]]
        elif v == "today":
            t["due"] = today().isoformat()

    def act_add(self, at_top=False, child=False):
        parent = None
        if child:
            cur = self.current()
            if not cur:
                self.say("no task to add a subtask to", "err")
                return
            parent = cur["id"]
        title = "new subtask" if child else "new task"
        text = self.prompt(self.s("add_title", title), "", live=self.live_preview, hist="add")
        if not text or not text.strip():
            return
        p = parse_quick(text)
        if not p["title"]:
            self.say("title is empty", "err")
            return
        with self.edit():
            t = self.store.add(p["title"], parent=parent, at_top=at_top)
            self.add_defaults(t)
            self.apply_parsed(t, p, True)
            if child:
                cur = self.store.get(parent)
                cur["folded"] = False
                self.store.tasks.remove(t)
                last = [cur] + self.store.descendants(parent)
                idx = max(self.store.tasks.index(x) for x in last) + 1
                self.store.tasks.insert(idx, t)
        self.hook("on_add", t)
        self.anim("add", t["id"], 0.4)
        self.cur_id = t["id"]
        self.say("added")

    def act_edit(self):
        t = self.current()
        if t:
            self.edit_task(t)

    def notes_external(self, t):
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
        fd, path = tempfile.mkstemp(prefix="synth-", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(t["notes"])
        curses.def_prog_mode()
        curses.endwin()
        try:
            subprocess.run(shlex.split(editor) + [path])
        except (OSError, ValueError):
            pass
        curses.reset_prog_mode()
        self.scr.clear()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read().rstrip("\n")
        except OSError:
            text = t["notes"]
        with contextlib.suppress(OSError):
            os.unlink(path)
        if text != t["notes"]:
            with self.edit():
                t["notes"] = text
            self.say("notes saved")

    def act_delete(self):
        ts = self.targets()
        if not ts:
            return
        if self.opts["confirm_delete"]:
            n = len(ts)
            label = ('"%s"' % clip(ts[0]["title"], 30)) if n == 1 else "%d tasks" % n
            if not self.confirm("delete %s and its subtasks?" % label):
                return
        doomed = {x["id"] for t in ts for x in [t] + self.store.descendants(t["id"])}
        if self.store.active and self.store.active["id"] in doomed:
            self.stop_tracking(False)
        with self.edit():
            gone = self.store.delete([t["id"] for t in ts])
        for t in ts:
            self.hook("on_delete", t)
        self.selected -= gone
        self.say("deleted %d" % len(gone), "err")

    def act_prio(self, delta):
        ts = self.targets()
        if not ts:
            return
        with self.edit():
            for t in ts:
                t["prio"] = max(0, min(3, t["prio"] + delta))
        labels = self.opts["priority_labels"]
        lvl = ts[0]["prio"]
        self.say("priority: " + (labels[lvl] if lvl < len(labels) else str(lvl)))

    def act_due(self):
        ts = self.targets()
        if not ts:
            return
        initial = ts[0]["due"] or ""
        while True:
            text = self.prompt("due date (today, tom, fri, +3d, 12-25, none)", initial)
            if text is None:
                return
            try:
                d = parse_date(text)
                break
            except ValueError as exc:
                self.say(str(exc), "err")
                initial = text
        with self.edit():
            for t in ts:
                t["due"] = d.isoformat() if d else None
        self.say("due: " + (d.isoformat() if d else "cleared"))

    def act_tags(self):
        ts = self.targets()
        if not ts:
            return
        hint = "tags: work  -old  (space separated)"
        text = self.prompt(hint, "")
        if not text:
            return
        with self.edit():
            for t in ts:
                for tok in text.split():
                    name = tok.lstrip("#").lower()
                    if tok.startswith("-"):
                        name = tok[1:].lstrip("#").lower()
                        if name in t["tags"]:
                            t["tags"].remove(name)
                    elif name and name not in t["tags"]:
                        t["tags"].append(name)
        self.say("tags updated")

    def act_project(self):
        ts = self.targets()
        if not ts:
            return
        projects = sorted({t["project"] for t in self.store.tasks if t["project"]}, key=str.lower)
        items = [{"label": "(no project)", "kind": "none", "payload": ""}]
        items += [{"label": p, "kind": "project", "payload": p} for p in projects]
        pick = self.fuzzy("project  (type to filter, or create a new one)", items, allow_new=True)
        if not pick:
            return
        name = pick.get("text") or pick["payload"]
        name = name.strip().lstrip("@").replace(" ", "-")
        with self.edit():
            for t in ts:
                t["project"] = name
        self.say("project: " + (name or "cleared"))

    def act_repeat(self):
        ts = self.targets()
        if not ts:
            return
        initial = ts[0]["repeat"]
        while True:
            text = self.prompt("repeat (daily, weekly, 2w, 1m, none). needs a due date", initial)
            if text is None:
                return
            try:
                rep = parse_repeat(text)
                break
            except ValueError as exc:
                self.say(str(exc), "err")
                initial = text
        with self.edit():
            for t in ts:
                t["repeat"] = rep
                if rep and not t["due"]:
                    t["due"] = today().isoformat()
        self.say("repeat: " + (rep or "off"))

    def act_move(self, step):
        t = self.current()
        if not t or self.opts["sort"] != "manual":
            if t:
                self.say("switch sort to manual to reorder", "err")
            return
        sibs = [r[0] for r in self.rows if r[0]["parent"] == t["parent"]]
        i = sibs.index(t)
        j = i + step
        if not 0 <= j < len(sibs):
            return
        other = sibs[j]
        with self.edit():
            a, b = self.store.tasks.index(t), self.store.tasks.index(other)
            self.store.tasks[a], self.store.tasks[b] = other, t

    def act_fold(self, mode):
        t = self.current()
        if not t or not self.store.children(t["id"]):
            return
        t["folded"] = (not t["folded"]) if mode == "toggle" else (mode == "collapse")
        self.store.save()

    def act_sort(self):
        names = self.sort_names()
        i = names.index(self.opts["sort"]) if self.opts["sort"] in names else 0
        self.opts["sort"] = names[(i + 1) % len(names)]
        self.persist("sort", self.opts["sort"])
        self.say("sort: " + self.opts["sort"])

    def act_search(self):
        text = self.prompt("filter  (#tag @proj !2+ due:week is:done -term text)", self.query, live=self.query_preview, hist="filter")
        if text is None:
            return
        self.query = text.strip()
        self.top = 0
        self.cur = 0
        self.cur_id = None

    def act_clear_done(self):
        done = [t for t in self.store.tasks if t["done"]]
        if not done:
            self.say("nothing done to clear")
            return
        if not self.confirm("delete %d done tasks?" % len(done)):
            return
        with self.edit():
            self.store.delete([t["id"] for t in done])
        self.say("cleared %d" % len(done), "err")

    def act_theme(self):
        names = self.theme_names()
        orig = self.opts["theme"]
        idx = self.menu("theme", names, names.index(orig) if orig in names else 0,
                        on_move=lambda i: self.set_theme(names[i]))
        if idx is None:
            self.set_theme(orig)
        else:
            self.set_theme(names[idx])
            self.persist("theme", names[idx])
            self.say("theme: " + names[idx])

    def toggle_opt(self, key):
        self.opts[key] = not self.opts[key]
        self.persist(key, self.opts[key])
        if key in ("ascii", "transparent", "exact_colors"):
            self.apply_config()
        self.say("%s: %s" % (key, "on" if self.opts[key] else "off"))

    def act_toggle_detail(self):
        order = ["right", "bottom", "off"]
        cur = self.opts["detail"] if self.opts["detail"] in order else "right"
        self.opts["detail"] = order[(order.index(cur) + 1) % 3]
        self.persist("detail", self.opts["detail"])

    # ----- palette -----

    COMMANDS = ["settings", "journal", "habits", "projects", "goals", "note", "snooze", "deps", "template", "run", "theme", "sort", "view", "filter", "set", "export", "clear", "reload", "config",
                "add", "stats", "calendar", "agenda", "focus", "track", "find", "links", "help", "quit", "w", "q"]

    def act_palette(self):
        text = self.prompt(":", "", complete=self.COMMANDS, hist="cmd")
        if not text or not text.strip():
            return
        cmd, _, arg = text.strip().partition(" ")
        arg = arg.strip()
        if cmd in ("q", "quit"):
            self.running = False
        elif cmd == "w":
            self.store.save()
            self.say("saved")
        elif cmd == "theme":
            if arg in self.theme_names():
                self.set_theme(arg)
                self.persist("theme", arg)
            else:
                self.say("themes: " + ", ".join(self.theme_names()), "err", 5)
        elif cmd == "sort":
            if arg in self.sort_names():
                self.opts["sort"] = arg
                self.persist("sort", arg)
            else:
                self.say("sorts: " + ", ".join(self.sort_names()), "err", 5)
        elif cmd == "view":
            hits = [i for i in self.sidebar_items() if not i["head"] and
                    (i["label"].lower().lstrip("@#") == arg.lower().lstrip("@#") or i["key"] == arg)]
            if hits:
                self.set_view(hits[0]["key"])
            else:
                self.say("no such view", "err")
        elif cmd == "filter":
            self.query = arg
            self.cur, self.cur_id, self.top = 0, None, 0
        elif cmd == "add":
            p = parse_quick(arg)
            if p["title"]:
                with self.edit():
                    t = self.store.add(p["title"])
                    self.add_defaults(t)
                    self.apply_parsed(t, p, True)
                self.say("added")
        elif cmd == "set":
            self.cmd_set(arg)
        elif cmd == "export":
            self.cmd_export(arg or "synth-export.md")
        elif cmd == "clear":
            self.act_clear_done()
        elif cmd == "reload":
            self.cfg = load_config(self.cfg_path, lambda m: self.say(m, "err"), self.args.profile)
            self.apply_config()
            self.say("config reloaded")
        elif cmd == "config":
            self.open_in_editor(self.cfg_path)
        elif cmd == "stats":
            self.act_stats()
        elif cmd == "calendar":
            self.act_calendar()
        elif cmd == "agenda":
            self.act_calendar("agenda")
        elif cmd == "focus":
            self.act_focus()
        elif cmd == "track":
            self.act_track()
        elif cmd == "find":
            self.act_find()
        elif cmd == "links":
            self.act_links()
        elif cmd == "help":
            self.act_help()
        elif cmd == "settings":
            self.act_settings(arg)
        elif cmd == "journal":
            self.act_journal()
        elif cmd == "habits":
            self.act_habits()
        elif cmd in ("projects", "goals"):
            self.act_projects(1 if cmd == "goals" else 0)
        elif cmd == "note":
            if arg:
                t = self.current()
                if t:
                    stamp = dt.datetime.now().strftime(self.opts.get("note_stamp", "%Y-%m-%d %H:%M"))
                    with self.edit():
                        t["notes"] = (t["notes"].rstrip() + "\n" if t["notes"].strip() else "") + "- [%s] %s" % (stamp, arg)
                    self.say("note added", "ok")
            else:
                self.act_note_add()
        elif cmd == "snooze":
            self.act_snooze()
        elif cmd == "deps":
            self.act_deps()
        elif cmd == "template":
            self.act_template()
        elif cmd == "run":
            hit = [a for a in self.custom_actions() if a["name"].lower() == arg.lower()]
            tpl = [t for t in self.opts.get("templates", []) if isinstance(t, dict) and t.get("name", "").lower() == arg.lower()]
            if hit:
                self.run_action(hit[0])
            elif tpl:
                self.run_template(tpl[0])
            else:
                self.act_actions_menu()
        else:
            self.say("unknown command: " + cmd, "err")

    def cmd_set(self, arg):
        parts = arg.split(None, 1)
        if not parts:
            self.act_settings()
            return
        key, val = parts[0], (parts[1] if len(parts) > 1 else "")
        if key in BOOL_OPTS:
            self.opts[key] = val.lower() in ("1", "true", "on", "yes", "") if val else not self.opts[key]
        elif key in INT_OPTS and val.isdigit():
            self.opts[key] = int(val)
        elif key in FLOAT_OPTS and re.fullmatch(r"\d+(\.\d+)?", val or ""):
            self.opts[key] = float(val)
        elif key == "detail" and val in ("right", "bottom", "off"):
            self.opts[key] = val
        elif key == "columns":
            self.opts[key] = [c.strip() for c in val.replace(",", " ").split() if c.strip()]
        elif key == "date_format" and val:
            self.opts[key] = val
        elif key in STR_OPTS and val and (STR_OPTS[key] is None or val in STR_OPTS[key]):
            self.opts[key] = val
        else:
            self.say("bad option or value", "err")
            return
        self.persist(key, self.opts[key])
        if key in ("ascii", "transparent", "exact_colors", "border_style"):
            self.apply_config()
        self.say("%s = %s" % (key, self.opts[key]))

    def cmd_export(self, path):
        lines = ["# synth export", ""]

        def emit(t, depth):
            bits = [t["title"]] + ["#" + g for g in t["tags"]]
            if t["project"]:
                bits.append("@" + t["project"])
            if t["prio"]:
                bits.append("!%d" % t["prio"])
            if t["due"]:
                bits.append("(due %s)" % t["due"])
            lines.append("%s- [%s] %s" % ("  " * depth, "x" if t["done"] else " ", " ".join(bits)))
            if t["notes"].strip():
                for ln in t["notes"].splitlines():
                    lines.append("%s    %s" % ("  " * depth, ln))
            for c in self.store.children(t["id"]):
                emit(c, depth + 1)

        ids = {t["id"] for t in self.store.tasks}
        for t in self.store.tasks:
            if t["parent"] not in ids:
                emit(t, 0)
        try:
            with open(os.path.expanduser(path), "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            self.say("exported to " + path)
        except OSError as exc:
            self.say("export failed: %s" % exc, "err")

    def open_in_editor(self, path):
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
        curses.def_prog_mode()
        curses.endwin()
        try:
            subprocess.run(shlex.split(editor) + [path])
        except (OSError, ValueError):
            pass
        curses.reset_prog_mode()
        self.scr.clear()

    # ----- previews for prompts -----

    def live_preview(self, text):
        p = parse_quick(text)
        out = []
        if p["title"]:
            out.append(("title: " + p["title"], "fg"))
        bits = []
        if p["tags"]:
            bits.append(" ".join("#" + g for g in p["tags"]))
        if p["project"]:
            bits.append("@" + p["project"])
        if p["prio"]:
            labels = self.opts["priority_labels"]
            bits.append("priority " + (labels[p["prio"]] if p["prio"] < len(labels) else str(p["prio"])))
        if p["due"] is not UNSET and p["due"]:
            bits.append("due " + p["due"])
        if p["repeat"]:
            bits.append("every " + p["repeat"])
        if p["est"]:
            bits.append("est " + fmt_duration(p["est"]))
        if p.get("notes"):
            bits.append("note: " + clip(p["notes"], 30))
        if bits:
            out.append(("  ".join(bits), "accent2"))
        hint = self.est_hint(p["est"]) if p["est"] else ""
        if hint:
            out.append((hint, "dim"))
        if not out:
            out.append(("tip: title #tag @project !2 due:fri every:1w est:30m // a note", "dim"))
        return out

    def query_preview(self, text):
        n = 0
        f = compile_query(text, self.store)
        td = today()
        n = sum(1 for t in self.store.tasks if f(t, td))
        return [("%d matching tasks" % n, "accent2")]

    # ----- low level drawing -----

    def put(self, y, x, text, attr, maxw=None):
        H, W = self.scr.getmaxyx()
        if y < 0 or y >= H or x >= W:
            return x
        room = W - x - (1 if y == H - 1 else 0)
        if maxw is not None:
            room = min(room, maxw)
        if cell_len(text) > room:
            text = text[:max(0, room)] if not text.strip() else clip(text, room, self.sym["ellipsis"])
        with contextlib.suppress(curses.error):
            self.scr.addstr(y, x, text, attr)
        return x + cell_len(text)

    def fill(self, y, x, w, attr):
        self.put(y, x, " " * max(0, w), attr, w)

    def box(self, y, x, h, w, title=""):
        s = self.sym
        border = self.attr("border")
        for r in range(h):
            self.fill(y + r, x, w, self.attr("fg", "bg"))
        self.put(y, x, s["corner_tl"] + s["hline"] * (w - 2) + s["corner_tr"], border)
        self.put(y + h - 1, x, s["corner_bl"] + s["hline"] * (w - 2) + s["corner_br"], border)
        for r in range(1, h - 1):
            self.put(y + r, x, s["vline"], border)
            self.put(y + r, x + w - 1, s["vline"], border)
        if title:
            self.put(y, x + 2, " " + clip(title, w - 6) + " ", self.attr("accent", bold=True))

    def read_key(self):
        """Return (name, char)."""
        while True:
            self.scr.timeout(self.tick_ms())
            try:
                k = self.scr.get_wch()
            except curses.error:
                k = None
            except KeyboardInterrupt:
                return "ctrl-c", None
            if k is None:
                if self.store.changed_on_disk():
                    self.store.load()
                    self.say("reloaded from disk", "dim", 2)
                return "tick", None
            if k == "\x1b":
                self.scr.timeout(25)
                try:
                    nxt = self.scr.get_wch()
                except curses.error:
                    nxt = None
                self.scr.timeout(self.tick_ms())
                if isinstance(nxt, str) and nxt != "\x1b":
                    return "alt-" + nxt, None
            return key_name(k)

    # ----- modal widgets -----

    def prompt(self, title, initial="", live=None, complete=None, hist=None):
        buf, pos = list(initial), len(initial)
        hl = list(self.state.get("hist", {}).get(hist, [])) if hist else []
        hi = len(hl)
        while True:
            self.backdrop()
            H, W = self.scr.getmaxyx()
            w = min(W - 4, 76)
            x, y = (W - w) // 2, max(1, H // 3)
            lines = live("".join(buf)) if live else []
            self.box(y, x, 4 + len(lines), w, title)
            inner = w - 4
            text = "".join(buf)
            start = 0
            while cell_len("".join(buf[start:pos])) >= inner:
                start += 1
            shown = "".join(buf[start:])
            self.fill(y + 1, x + 2, inner, self.attr("fg", "sel_bg"))
            self.put(y + 1, x + 2, shown, self.attr("fg", "sel_bg"), inner)
            cx = x + 2 + cell_len("".join(buf[start:pos]))
            under = buf[pos] if pos < len(buf) else " "
            self.put(y + 1, cx, under, self.attr("fg", "sel_bg", reverse=True))
            for i, (ln, role) in enumerate(lines):
                self.put(y + 2 + i, x + 2, clip(ln, inner), self.attr(role))
            self.put(y + 2 + len(lines), x + 2, "enter accept  esc cancel", self.attr("dim"))
            self.scr.refresh()
            name, ch = self.read_key()
            if name in ("enter",):
                if hist and text.strip():
                    allh = dict(self.state.get("hist", {}))
                    allh[hist] = ([h for h in hl if h != text.strip()] + [text.strip()])[-30:]
                    self.persist("hist", allh)
                return text
            if name in ("esc", "ctrl-c"):
                return None
            if name in ("tick", "resize", "mouse"):
                continue
            if name in ("up", "down") and hl:
                hi = max(0, hi - 1) if name == "up" else min(len(hl), hi + 1)
                buf = list(hl[hi]) if hi < len(hl) else []
                pos = len(buf)
            elif name in ("left", "ctrl-b"):
                pos = max(0, pos - 1)
            elif name in ("right", "ctrl-f"):
                pos = min(len(buf), pos + 1)
            elif name in ("home", "ctrl-a"):
                pos = 0
            elif name in ("end", "ctrl-e"):
                pos = len(buf)
            elif name == "backspace":
                if pos:
                    del buf[pos - 1]
                    pos -= 1
            elif name == "delete":
                if pos < len(buf):
                    del buf[pos]
            elif name == "ctrl-u":
                del buf[:pos]
                pos = 0
            elif name == "ctrl-k":
                del buf[pos:]
            elif name == "ctrl-w":
                j = pos
                while j > 0 and buf[j - 1] == " ":
                    j -= 1
                while j > 0 and buf[j - 1] != " ":
                    j -= 1
                del buf[j:pos]
                pos = j
            elif name == "alt-b":
                while pos > 0 and buf[pos - 1] == " ":
                    pos -= 1
                while pos > 0 and buf[pos - 1] != " ":
                    pos -= 1
            elif name == "alt-f":
                while pos < len(buf) and buf[pos] == " ":
                    pos += 1
                while pos < len(buf) and buf[pos] != " ":
                    pos += 1
            elif name == "tab" and complete:
                word = "".join(buf[:pos])
                hits = [c for c in complete if c.startswith(word)]
                if len(hits) >= 1 and " " not in word:
                    buf = list(hits[0]) + [" "] + buf[pos:]
                    pos = len(hits[0]) + 1
            elif ch:
                buf.insert(pos, ch)
                pos += 1

    def menu(self, title, options, index=0, on_move=None):
        if on_move:
            on_move(index)
        while True:
            self.backdrop()
            H, W = self.scr.getmaxyx()
            w = min(W - 4, max(28, max(cell_len(o) for o in options) + 8))
            h = min(H - 2, len(options) + 4)
            x, y = (W - w) // 2, max(1, (H - h) // 2)
            self.box(y, x, h, w, title)
            vis = h - 4
            first = max(0, min(index - vis // 2, len(options) - vis))
            for r in range(vis):
                i = first + r
                if i >= len(options):
                    break
                sel = i == index
                a = self.attr("accent", "sel_bg", bold=True) if sel else self.attr("fg")
                if sel:
                    self.fill(y + 2 + r, x + 1, w - 2, a)
                self.put(y + 2 + r, x + 3, options[i], a, w - 6)
            self.scr.refresh()
            name, ch = self.read_key()
            old = index
            if name in ("down", "j", "ctrl-n"):
                index = (index + 1) % len(options)
            elif name in ("up", "k", "ctrl-p"):
                index = (index - 1) % len(options)
            elif name == "enter":
                return index
            elif name in ("esc", "q", "ctrl-c"):
                return None
            if index != old and on_move:
                on_move(index)

    def confirm(self, msg):
        while True:
            self.backdrop()
            H, W = self.scr.getmaxyx()
            w = min(W - 4, max(30, cell_len(msg) + 6))
            x, y = (W - w) // 2, max(1, H // 3)
            self.box(y, x, 5, w, "confirm")
            self.put(y + 2, x + 2, clip(msg, w - 4), self.attr("fg"))
            self.put(y + 3, x + 2, "y yes   n no", self.attr("dim"))
            self.scr.refresh()
            name, ch = self.read_key()
            if name in ("y", "Y", "enter"):
                return True
            if name in ("n", "N", "esc", "q", "ctrl-c"):
                return False

    def pager(self, title, lines):
        top = 0
        while True:
            self.backdrop()
            H, W = self.scr.getmaxyx()
            w, h = min(W - 4, 84), H - 2
            x, y = (W - w) // 2, 1
            self.box(y, x, h, w, title)
            vis = h - 3
            for r in range(vis):
                i = top + r
                if i < len(lines):
                    text, role = lines[i]
                    self.put(y + 1 + r, x + 2, text, self.attr(role, bold=(role == "accent")), w - 4)
            self.put(y + h - 2, x + 2, "j/k scroll  any other key closes", self.attr("dim"))
            self.scr.refresh()
            name, ch = self.read_key()
            if name in ("down", "j"):
                top = min(max(0, len(lines) - vis), top + 1)
            elif name in ("up", "k"):
                top = max(0, top - 1)
            elif name in ("pgdn", "ctrl-d", "space"):
                top = min(max(0, len(lines) - vis), top + vis)
            elif name in ("pgup", "ctrl-u"):
                top = max(0, top - vis)
            elif name not in ("tick", "resize", "mouse"):
                return

    def act_help(self):
        lines = [("QUICK ADD SYNTAX", "accent"),
                 ("  buy milk #errands @home !2 due:fri every:1w est:45m", "fg"),
                 ("  link tasks with [[title]] or [[id]] in notes, urls open from the links menu", "dim"),
                 ("  !1 low  !2 medium  !3 high    ^fri = due:fri    ~1w = every:1w", "dim"),
                 ("  dates: today tom fri +3d +2w 12-25 2026-12-25 eow eom none", "dim"),
                 ("", "fg"),
                 ("FILTER SYNTAX  (press /)", "accent"),
                 ("  #tag  @project  !2  !2+  due:today|overdue|week|any|none|<date>", "fg"),
                 ("  is:done  is:open  is:blocked  is:ready  is:snoozed  has:notes  has:deps  has:est", "dim"),
                 ("  -term negates, plain words match title and notes", "dim"),
                 ("", "fg"),
                 ("KEYS", "accent")]
        groups = [
            ("MOVE AND VIEW", ["up", "down", "top", "bottom", "pgup", "pgdn", "focus", "view_next", "view_prev",
                               "toggle_sidebar", "toggle_detail", "detail_tab", "detail_down", "detail_up", "find",
                               "back", "redraw"]),
            ("EDIT TASKS", ["toggle", "add", "add_top", "add_child", "edit", "delete", "duplicate", "prio_up",
                            "prio_down", "due", "tags", "project", "repeat", "move_up", "move_down", "fold",
                            "collapse", "expand", "select", "select_all", "yank", "undo", "redo", "clear_done"]),
            ("NOTES, LINKS, PLANNING", ["notes", "note_add", "links", "link_add", "deps", "snooze", "template",
                                        "actions_menu"]),
            ("FILTER AND SORT", ["search", "clear_filter", "sort", "hide_done"]),
            ("SCREENS AND TOOLS", ["journal", "habits", "projects", "calendar", "stats", "focus_mode", "track",
                                   "theme", "settings", "palette", "help", "quit"]),
        ]
        seen = set()
        for gname, acts in groups:
            lines += [("", "fg"), (gname, "accent")]
            for action in acts:
                if action not in ACTION_DOC:
                    continue
                seen.add(action)
                names = [n for n, a_ in self.keymap.items() if a_ == action]
                lines.append(("  %-16s %s" % (" ".join(names) or "(unbound)", ACTION_DOC[action]), "fg"))
        for action, doc in ACTION_DOC.items():
            if action not in seen:
                names = [n for n, a_ in self.keymap.items() if a_ == action]
                lines.append(("  %-16s %s" % (" ".join(names) or "(unbound)", doc), "fg"))
        lines += [("", "fg"), ("MOUSE", "accent"),
                  ("  click selects, double click edits, click checkbox toggles, wheel scrolls", "fg"),
                  ("", "fg"), ("PALETTE  (press :)", "accent"),
                  ("  theme sort view filter set export clear reload config add help quit", "fg"),
                  ("  stats calendar agenda focus track find links journal habits projects goals", "fg"),
                 ("  note TEXT  snooze  deps  template  run NAME", "fg"),
                  ("  set sidebar|ascii|transparent|show_done|cascade_done|confirm_delete [on|off]", "dim"),
                  ("  set sidebar_width|detail_size|scrolloff N   set detail right|bottom|off", "dim"),
                  ("  set columns title due tags    set date_format %d/%m", "dim"),
                  ("", "fg"), ("config: " + self.cfg_path, "dim"), ("data:   " + self.store.path, "dim")]
        self.pager("synth. help", lines)

    # ----- drawing the main screen -----

    def due_label(self, t):
        if not t["due"]:
            return "", "dim"
        d = dt.date.fromisoformat(t["due"])
        delta = (d - today()).days
        if t["done"]:
            return d.strftime(self.opts["date_format"]), "done"
        if delta < 0:
            return "%dd late" % -delta, "overdue"
        if delta == 0:
            return "today", "today"
        if delta == 1:
            return "tomorrow", "soon"
        if delta < 7:
            return d.strftime("%a"), "soon"
        return d.strftime(self.opts["date_format"]), "dim"

    def prio_role(self, p):
        cols = self.opts.get("priority_colors") or []
        if p < len(cols) and cols[p]:
            return cols[p]
        return {0: "dim", 1: "p1", 2: "p2", 3: "p3"}[p]

    def draw(self):
        scr = self.scr
        scr.erase()
        H, W = scr.getmaxyx()
        if H < 8 or W < 30:
            self.put(0, 0, "terminal too small", self.attr("err"))
            return
        self.purge_anims()
        self.rebuild()
        s = self.sym
        o = self.opts
        sw = o["sidebar_width"] if o["sidebar"] and W >= 60 else 0
        list_x = sw + (1 if sw else 0)
        body_y, body_h = 1, H - 2
        dw = dh = 0
        if o["detail"] == "right" and W - list_x >= 72:
            dw = min(o["detail_size"], W - list_x - 36)
        elif o["detail"] == "bottom" and body_h >= 16:
            dh = min(o["detail_size"] if o["detail_size"] < 20 else 9, body_h - 8)
        list_w = W - list_x - (dw + 1 if dw else 0)
        list_h = body_h - (dh + 1 if dh else 0)
        self.geo = {"list_x": list_x, "list_y": body_y, "list_w": list_w, "list_h": list_h, "sw": sw}

        # header
        hb = self.attr("fg", "bar_bg")
        self.fill(0, 0, W, hb)
        x = self.put(0, 1, self.s("app_name", "synth."), self.attr("accent", "bar_bg", bold=True))
        x = self.put(0, x + 1, self.view_label(self.view), self.attr("accent2", "bar_bg", bold=True))
        info = "  sort:" + self.view_opt("sort")
        if not self.view_opt("show_done"):
            info += "  hide-done"
        if o.get("header_info", True):
            x = self.put(0, x, info, self.attr("dim", "bar_bg"))
        if self.query:
            x = self.put(0, x + 2, "/" + self.query, self.attr("today", "bar_bg", bold=True))
        total, done = self.keep_count, self.keep_done
        target = (done / float(total)) if total else 0.0
        if o.get("animations"):
            self.bar_disp += (target - self.bar_disp) * 0.3
            if abs(target - self.bar_disp) < 0.01:
                self.bar_disp = target
            self.bar_busy = abs(target - self.bar_disp) > 0.0
        else:
            self.bar_disp, self.bar_busy = target, False
        right_x = W - 1
        if total and o.get("header_progress", True):
            bw = 10
            filled = int(round(bw * self.bar_disp))
            bar = s["bar_on"] * filled + s["bar_off"] * (bw - filled)
            right = " %s %d/%d " % (bar, done, total)
            right_x = W - cell_len(right) - 1
            self.put(0, right_x, right, self.attr("ok", "bar_bg"))
        if o.get("header_habits", True) and self.store.habits:
            hd, ht = habit_summary(self.store, today())
            if ht:
                seg = " habits %d/%d " % (hd, ht)
                if right_x - cell_len(seg) - 1 > x + 4:
                    right_x = right_x - cell_len(seg) - 1
                    self.put(0, right_x, seg, self.attr("ok" if hd == ht else "accent2", "bar_bg"))
        if o.get("header_clock"):
            seg = " %s " % dt.datetime.now().strftime(o.get("clock_format", "%H:%M"))
            if right_x - cell_len(seg) - 1 > x + 4:
                right_x = right_x - cell_len(seg) - 1
                self.put(0, right_x, seg, self.attr("dim", "bar_bg"))
        act = self.store.active
        if act:
            tt = self.store.get(act["id"])
            frames = SPINNER_ASCII if o["ascii"] else SPINNER
            spin = frames[int(time.time() * 5) % 4] if o.get("animations") else s["track"]
            seg = " %s %s %s " % (spin, fmt_duration(self.active_elapsed(), True), clip(tt["title"] if tt else "?", 24))
            self.put(0, max(2, right_x - cell_len(seg) - 1), seg, self.attr("today", "bar_bg", bold=True))

        # sidebar
        if sw:
            self.draw_sidebar(body_y, body_h, sw)
            for r in range(body_h):
                self.put(body_y + r, sw, s["vline"], self.attr("border"))

        # list
        self.draw_list(list_x, body_y, list_w, list_h)

        # detail
        if dw:
            dx = list_x + list_w
            for r in range(body_h):
                self.put(body_y + r, dx, s["vline"], self.attr("border"))
            self.draw_detail(dx + 1, body_y, dw, body_h)
        elif dh:
            dy = body_y + list_h
            self.put(dy, list_x, s["hline"] * list_w, self.attr("border"))
            self.draw_detail(list_x + 1, dy + 1, list_w - 2, dh)

        # footer
        fb = self.attr("fg", "bar_bg")
        self.fill(H - 1, 0, W, fb)
        right = ""
        if self.selected:
            right = "%d selected " % len(self.selected)
        if self.pending:
            right = "%s ... " % self.pending + right
        right += "[%s] %d/%d" % ("side" if self.focus == "sidebar" else "list", min(self.cur + 1, len(self.rows)), len(self.rows))
        left_w = max(0, W - cell_len(right) - 4)
        if self.msg and time.time() < self.msg_until:
            self.put(H - 1, 1, self.msg, self.attr(self.msg_kind, "bar_bg", bold=True), left_w)
        else:
            self.put(H - 1, 1, self.hint_line(), self.attr("dim", "bar_bg"), left_w)
        self.put(H - 1, W - cell_len(right) - 2, right, self.attr("accent2", "bar_bg"))
        scr.refresh()

    def first_key(self, action):
        for n, a in self.keymap.items():
            if a == action:
                return n
        return "?"

    def hint_line(self):
        names = self.opts.get("hints") or []
        if names:
            parts = []
            for n in names:
                a, _, label = str(n).partition(":")
                parts.append((a, label or a.replace("_", " ")))
        else:
            parts = [("add", "add"), ("toggle", "done"), ("edit", "edit"), ("notes", "notes"), ("note_add", "note"),
                     ("search", "filter"), ("find", "find"), ("track", "track"), ("focus_mode", "focus"),
                     ("journal", "journal"), ("habits", "habits"), ("calendar", "cal"), ("stats", "stats"),
                     ("settings", "settings"), ("palette", "cmd"), ("help", "help")]
        return "  ".join("%s %s" % (self.first_key(a), label) for a, label in parts)

    def draw_sidebar(self, y, h, w):
        items = self.sidebar_items()
        sel_key = self.view
        for r, item in enumerate(items[:h]):
            if item["head"]:
                self.put(y + r, 1, item["label"], self.attr("dim", bold=True))
                continue
            active = item["key"] == sel_key
            focus = active and self.focus == "sidebar"
            bg = "sel_bg" if active else "bg"
            if active:
                self.fill(y + r, 0, w, self.attr("fg", bg))
            mark = self.sym["cursor"] if active else " "
            self.put(y + r, 0, mark, self.attr("accent", bg, bold=True))
            label = clip(item["label"], w - 6)
            self.put(y + r, 2, label, self.attr("accent" if focus else ("accent2" if active else "fg"), bg, bold=active))
            cnt = str(item["count"]) if item["count"] else ""
            self.put(y + r, w - 1 - len(cnt), cnt, self.attr("dim", bg))

    def draw_list(self, x, y, w, h):
        if not self.rows:
            msg = self.s("empty", "nothing here. press %s to add a task" % self.first_key("add"))
            if self.query:
                msg = "no tasks match the filter. %s clears it" % self.first_key("clear_filter")
            self.put(y + h // 2, x + max(0, (w - cell_len(msg)) // 2), msg, self.attr("dim"))
            return
        so = min(self.opts["scrolloff"], max(0, h // 2 - 1))
        if self.cur < self.top + so:
            self.top = max(0, self.cur - so)
        if self.cur > self.top + h - 1 - so:
            self.top = self.cur - h + 1 + so
        self.top = max(0, min(self.top, max(0, len(self.rows) - h)))
        td = today()
        iso_today = td.isoformat()
        allowed = ("check", "prio", "title", "tags", "project", "time", "due", "est", "id", "deps", "snooze",
                   "created", "notes")
        cols = [c for c in (self.view_opt("columns") or []) if c in allowed]
        if "title" not in cols:
            cols.append("title")
        cwid = self.opts.get("column_widths", {}) or {}

        def cap(name, natural, default_max):
            lim = cwid.get(name)
            lim = int(lim) if isinstance(lim, int) and lim > 0 else default_max
            return min(lim, natural)

        tag_w = cap("tags", max([cell_len(" ".join("#" + g for g in t["tags"])) for t, _ in self.rows] + [0]), 22)
        proj_w = cap("project", max([cell_len("@" + t["project"]) if t["project"] else 0 for t, _ in self.rows] + [0]), 16)
        due_w = 9 if any(t["due"] for t, _ in self.rows) else 0
        time_w = 7 if (self.time_by or self.store.active) else 0
        est_w = 6 if any(t.get("est") for t, _ in self.rows) else 0
        id_w = max([len(str(t["id"])) for t, _ in self.rows] + [2]) + 1
        deps_w = 4 if any(t.get("deps") for t, _ in self.rows) else 0
        snz_w = 6 if any(t.get("snooze") for t, _ in self.rows) else 0
        cre_w = 6
        cell = max(cell_len(self.sym["check_off"]), cell_len(self.sym["check_on"]))
        psyms = self.opts.get("priority_symbols") or []
        pw = max([3] + [cell_len(str(s_)) for s_ in psyms])
        fixed = {"check": cell, "prio": pw, "tags": tag_w, "project": proj_w, "time": time_w, "due": due_w,
                 "est": est_w, "id": id_w, "deps": deps_w, "snooze": snz_w, "created": cre_w, "notes": 0}
        used = sum(fixed[c] + 1 for c in cols if c not in ("title", "notes") and fixed[c] > 0)
        title_w = max(10, w - 2 - used)
        indent = max(0, int(self.opts.get("indent", 2)))
        tag_colors = self.opts.get("tag_colors", {}) or {}
        proj_colors = self.opts.get("project_colors", {}) or {}
        for r in range(min(h, len(self.rows) - self.top)):
            i = self.top + r
            t, depth = self.rows[i]
            is_cur = i == self.cur
            sel = t["id"] in self.selected
            st = self.style_for(t, td)
            bg = "sel_bg" if is_cur else st.get("bg", "bg")
            row_y = y + r
            if is_cur or "bg" in st:
                self.fill(row_y, x, w, self.attr("fg", bg))
            if sel:
                self.put(row_y, x, self.sym["select"], self.attr("accent", bg, bold=True))
            elif is_cur:
                self.put(row_y, x, self.sym["cursor"], self.attr("accent", bg, bold=True))
            cx = x + 2
            done = t["done"]
            blocked = (not done) and bool(t.get("deps")) and bool(blockers(self.store, t))
            for c in cols:
                if c not in ("title", "notes") and fixed[c] == 0:
                    continue
                if c == "check":
                    role = "done" if done else self.prio_role(t["prio"]) if t["prio"] else "accent2"
                    sym = self.sym["check_on"] if done else self.sym["check_off"]
                    ap = self.anim_p("done", t["id"])
                    if ap is not None and done:
                        frames = CHECK_FRAMES_ASCII if self.opts["ascii"] else CHECK_FRAMES
                        sym = frames[min(len(frames) - 1, int(ap * len(frames)))]
                    self.put(row_y, cx, pad(sym, cell), self.attr(role, bg, bold=not done))
                    cx += cell + 1
                elif c == "prio":
                    txt = (psyms[t["prio"]] if t["prio"] < len(psyms) else "!" * t["prio"]) if t["prio"] else ""
                    role = "done" if done else self.prio_role(t["prio"])
                    self.put(row_y, cx, pad(str(txt), pw), self.attr(role, bg, bold=True))
                    cx += pw + 1
                elif c == "title":
                    kids = self.store.children(t["id"])
                    lead = " " * (indent * depth)
                    if kids:
                        lead += (self.sym["fold_closed"] if t["folded"] else self.sym["fold_open"]) + " "
                    elif depth:
                        lead += " " * indent
                    suffix = ""
                    if t["repeat"]:
                        suffix += " " + self.sym["repeat"]
                    if t["notes"].strip():
                        suffix += " " + self.sym["note"]
                    blob = t["title"] + " " + t["notes"]
                    if "[[" in blob or "http" in blob:
                        suffix += " " + self.sym["link"]
                    if blocked:
                        suffix += " " + self.sym["blocked"]
                    if t.get("woke") == iso_today and not done:
                        suffix += " " + self.sym["wake"]
                    if is_snoozed(t, td):
                        suffix += " " + self.sym["snooze"] + t["snooze"][5:]
                    if self.store.active and self.store.active["id"] == t["id"]:
                        suffix += " " + self.sym["track"]
                    if kids:
                        suffix += " (%d/%d)" % (sum(1 for k in kids if k["done"]), len(kids))
                    if st.get("suffix"):
                        suffix += " " + str(st["suffix"])
                    title_txt = render_refs(self.store, t["title"], self.sym["link"])
                    if st.get("prefix"):
                        title_txt = str(st["prefix"]) + " " + title_txt
                    addp = self.anim_p("add", t["id"])
                    if addp is not None:
                        title_txt = title_txt[:max(1, int(addp * len(title_txt)))]
                    text = lead + title_txt
                    tw = title_w if len(cols) > 1 else w - 2
                    room = tw - cell_len(suffix)
                    shown = pad(text, max(4, room))
                    role = "done" if done else ("accent" if addp is not None else st.get("fg", "fg"))
                    if blocked and not is_cur and "fg" not in st:
                        role = "dim"
                    self.put(row_y, cx, shown, self.attr(role, bg, bold=(is_cur and not done) or bool(st.get("bold")),
                                                         dim=bool(st.get("dim"))))
                    self.put(row_y, cx + cell_len(shown), suffix, self.attr("dim", bg))
                    after = cx + cell_len(shown) + cell_len(suffix)
                    if self.opts.get("notes_inline") and t["notes"].strip() and "notes" not in cols:
                        first = next((ln.strip() for ln in t["notes"].splitlines() if ln.strip()), "")
                        first = re.sub(r"^[-*]\s*\[\d{4}-\d\d-\d\d[^\]]*\]\s*", "", first)
                        left = cx + tw - after
                        if left > 8:
                            self.put(row_y, after + 1, self.sym["bullet"] + " " + first, self.attr("dim", bg), left - 1)
                    cx += tw + 1
                elif c == "notes":
                    pass
                elif c == "tags":
                    px = cx
                    for g in t["tags"]:
                        if px - cx >= tag_w:
                            break
                        role = "done" if done else tag_colors.get(g, "tag")
                        px = self.put(row_y, px, "#" + g, self.attr(role, bg), tag_w - (px - cx)) + 1
                    cx += tag_w + 1
                elif c == "project":
                    txt = "@" + t["project"] if t["project"] else ""
                    role = "done" if done else proj_colors.get(t["project"], "project")
                    self.put(row_y, cx, pad(txt, proj_w), self.attr(role, bg))
                    cx += proj_w + 1
                elif c == "time":
                    secs = self.task_time(t)
                    self.put(row_y, cx, pad(fmt_duration(secs) if secs else "", time_w, right=True),
                             self.attr("done" if done else "accent2", bg))
                    cx += time_w + 1
                elif c == "est":
                    self.put(row_y, cx, pad(fmt_duration(t["est"]) if t.get("est") else "", est_w, right=True),
                             self.attr("done" if done else "dim", bg))
                    cx += est_w + 1
                elif c == "id":
                    self.put(row_y, cx, pad(str(t["id"]), id_w, right=True), self.attr("dim", bg))
                    cx += id_w + 1
                elif c == "deps":
                    n = len(blockers(self.store, t)) if t.get("deps") and not done else 0
                    self.put(row_y, cx, pad((self.sym["blocked"] + str(n)) if n else "", deps_w, right=True),
                             self.attr("p3" if n else "dim", bg))
                    cx += deps_w + 1
                elif c == "snooze":
                    self.put(row_y, cx, pad(t["snooze"][5:] if is_snoozed(t, td) else "", snz_w, right=True),
                             self.attr("dim", bg))
                    cx += snz_w + 1
                elif c == "created":
                    self.put(row_y, cx, pad(t["created"][5:10], cre_w, right=True), self.attr("dim", bg))
                    cx += cre_w + 1
                elif c == "due":
                    txt, role = self.due_label(t)
                    self.put(row_y, cx, pad(txt, due_w, right=True), self.attr(role, bg, bold=role in ("overdue", "today")))
                    cx += due_w + 1
            sp = self.anim_p("done", t["id"])
            if sp is not None and t["done"]:
                self.sweep(row_y, x, w, sp)

    def detail_tab_names(self):
        names = [n for n in self.opts.get("detail_sections", []) if n in ("notes", "info", "links")]
        return names or ["notes", "info", "links"]

    def act_detail_tab(self, step=1, name=None):
        names = self.detail_tab_names()
        cur = self.opts.get("detail_tab", "notes")
        if name in names:
            new = name
        else:
            new = names[(names.index(cur) + step) % len(names)] if cur in names else names[0]
        self.opts["detail_tab"] = new
        self.persist("detail_tab", new)
        self.detail_scroll = 0

    def detail_body(self, t, tab, w, td):
        """Return the scrolling body lines for one detail section."""
        lines = []

        def row(k, v, role="fg"):
            for i, ln in enumerate(wrap("%-9s %s" % (k, v), w) or [""]):
                lines.append((ln if i == 0 else "          " + ln.lstrip(), role, False))

        def head(text):
            if lines:
                lines.append(("", "fg", False))
            lines.append((text, "accent2", True))

        if tab == "notes":
            if t["notes"].strip():
                for raw in t["notes"].split("\n"):
                    for ln in wrap(render_refs(self.store, raw, self.sym["link"]), w) or [""]:
                        lines.append((ln, "fg", False))
            else:
                for ln in wrap("No notes yet. Press %s to write them, or %s for a quick timestamped line."
                               % (self.first_key("notes"), self.first_key("note_add")), w):
                    lines.append((ln, "dim", False))
        elif tab == "info":
            labels = self.opts["priority_labels"]
            due_txt, due_role = self.due_label(t)
            row("status", "done" if t["done"] else "open", "ok" if t["done"] else "fg")
            row("priority", labels[t["prio"]] if t["prio"] < len(labels) else str(t["prio"]),
                self.prio_role(t["prio"]) if t["prio"] else "dim")
            if t["due"]:
                row("due", "%s (%s)" % (t["due"], due_txt), due_role)
            if t["repeat"]:
                row("repeat", "every " + t["repeat"], "accent2")
            if t["project"]:
                row("project", "@" + t["project"], "project")
            if t["tags"]:
                row("tags", " ".join("#" + g for g in t["tags"]), "tag")
            if is_snoozed(t, td):
                row("snoozed", "until " + t["snooze"], "today")
            tt = self.task_time(t)
            if tt or t.get("est"):
                txt = fmt_duration(tt)
                if t.get("est"):
                    txt += " / " + fmt_duration(t["est"])
                row("time", txt, "overdue" if t.get("est") and tt > t["est"] else "accent2")
                hint = self.est_hint(t["est"]) if t.get("est") and not t["done"] else ""
                if hint:
                    row("", hint, "dim")
            lines.append(("", "fg", False))
            row("id", str(t["id"]), "dim")
            row("created", t["created"].replace("T", " ")[:16], "dim")
            if t["done_at"]:
                row("finished", t["done_at"].replace("T", " ")[:16], "dim")
        else:
            wo = waiting_on(self.store, t)
            if t.get("deps") or wo:
                head("dependencies  (%s to edit)" % self.first_key("deps"))
                for d in [self.store.get(i) for i in t.get("deps", [])]:
                    if d:
                        for ln in wrap("%s needs: %s" % (self.sym["check_on"] if d["done"] else self.sym["blocked"], d["title"]), w):
                            lines.append((ln, "done" if d["done"] else "p3", False))
                for o_ in wo[:5]:
                    lines.append(("%s blocks: %s" % (self.sym["bullet"], clip(o_["title"], w - 10)), "fg", False))
            kids = self.store.children(t["id"])
            if kids:
                head("subtasks %d/%d" % (sum(1 for k in kids if k["done"]), len(kids)))
                for k in kids[:12]:
                    mark = self.sym["check_on"] if k["done"] else self.sym["check_off"]
                    lines.append(("%s %s" % (mark, clip(k["title"], w - 4)), "done" if k["done"] else "fg", False))
            links, back = task_links(self.store, t), backlinks(self.store, t)
            if links or back:
                head("links  (%s to open)" % self.first_key("links"))
                for kind, tgt, raw in links[:8]:
                    if kind == "task":
                        lines.append(("%s %s" % (self.sym["link"], clip(tgt["title"], w - 4)), "fg", False))
                    elif kind == "url":
                        lines.append(("%s %s" % (self.sym["web"], clip(raw, w - 4)), "soon", False))
                    else:
                        lines.append(("? %s (not found)" % clip(raw, w - 16), "err", False))
                for o_ in back[:5]:
                    lines.append(("%s %s" % (self.sym["back"], clip(o_["title"], w - 4)), "dim", False))
            if not lines:
                lines.append(("No subtasks, links or dependencies.", "dim", False))
        return lines

    def draw_detail(self, x, y, w, h):
        t = self.current()
        self.detail_hits = []
        if not t:
            self.put(y, x + 1, "no task selected", self.attr("dim"))
            return
        td = today()
        tab = self.opts.get("detail_tab", "notes")
        names = self.detail_tab_names()
        if tab not in names:
            tab = names[0]
        if self.detail_for != (t["id"], tab):
            self.detail_for, self.detail_scroll = (t["id"], tab), 0
        w = max(10, w - 1)
        r = y
        # fixed header: title, then one compact line of chips
        title_lines = wrap(render_refs(self.store, t["title"], self.sym["link"]), w - 2) or [""]
        for ln in title_lines[:2 if h < 12 else 3]:
            self.put(r, x + 1, ln, self.attr("accent", bold=True), w)
            r += 1
        chips = []
        labels = self.opts["priority_labels"]
        chips.append(("done", "ok") if t["done"] else ("open", "fg"))
        if t["prio"]:
            chips.append((labels[t["prio"]] if t["prio"] < len(labels) else "!" * t["prio"], self.prio_role(t["prio"])))
        if t["due"]:
            txt, role = self.due_label(t)
            chips.append(("due " + txt, role))
        if t["repeat"]:
            chips.append((self.sym["repeat"] + " " + t["repeat"], "accent2"))
        if t["project"]:
            chips.append(("@" + t["project"], "project"))
        for g in t["tags"]:
            chips.append(("#" + g, (self.opts.get("tag_colors") or {}).get(g, "tag")))
        if is_snoozed(t, td):
            chips.append((self.sym["snooze"] + " " + t["snooze"][5:], "today"))
        if t.get("deps") and blockers(self.store, t):
            chips.append((self.sym["blocked"] + " blocked", "p3"))
        cx, max_chip_rows, used_rows = x + 1, 1 if h < 12 else 2, 1
        for text, role in chips:
            cl = cell_len(text)
            if cx + cl > x + w and cx > x + 1:
                if used_rows >= max_chip_rows:
                    break
                used_rows += 1
                r += 1
                cx = x + 1
            self.put(r, cx, text, self.attr(role, bold=role in ("overdue", "today")), x + w - cx)
            cx += cl + 2
        r += 1
        # tab strip
        tx = x + 1
        for name in names:
            badge = ""
            if name == "notes" and t["notes"].strip():
                badge = " " + self.sym["note"]
            elif name == "links":
                n = len(task_links(self.store, t)) + len(backlinks(self.store, t)) + len(self.store.children(t["id"]))
                n += len(t.get("deps", [])) + len(waiting_on(self.store, t))
                badge = " %d" % n if n else ""
            label = " %s%s " % (name, badge)
            on = name == tab
            self.put(r, tx, label, self.attr("accent" if on else "dim", "sel_bg" if on else "bg", bold=on), x + w - tx)
            self.detail_hits.append((tx, tx + cell_len(label), r, name))
            tx += cell_len(label) + 1
        r += 1
        self.put(r, x + 1, self.sym["hline"] * max(0, w - 1), self.attr("border"))
        r += 1
        body_h = max(0, y + h - r)
        lines = self.detail_body(t, tab, w - 2, td)
        top = max(0, min(self.detail_scroll, max(0, len(lines) - body_h)))
        self.detail_scroll = top
        for i, (text, role, bold) in enumerate(lines[top:top + body_h]):
            self.put(r + i, x + 1, text, self.attr(role, bold=bold), w)
        if len(lines) > body_h > 0:
            pct = 100 * top // max(1, len(lines) - body_h)
            self.put(r - 2, x + w - 5, "%3d%%" % pct, self.attr("dim"), 5)

    # ----- animation helpers -----

    def tick_ms(self):
        if self.tick_override is not None:
            return self.tick_override
        if not self.opts.get("animations"):
            return 1000
        if self.anims or self.bar_busy:
            return 40
        if self.store.active:
            return 250
        return 1000

    def anim(self, kind, tid, dur):
        if self.opts.get("animations"):
            speed = max(0.1, float(self.opts.get("anim_speed", 1.0)))
            self.anims[(kind, tid)] = (time.time(), dur / speed)

    def anim_p(self, kind, tid):
        a = self.anims.get((kind, tid))
        if not a:
            return None
        p = (time.time() - a[0]) / a[1]
        return None if p >= 1 else max(0.0, p)

    def purge_anims(self):
        now = time.time()
        for k, (t0, d) in list(self.anims.items()):
            if now - t0 >= d:
                del self.anims[k]

    def sweep(self, y, x, w, p):
        pos = x + int(p * (w + 6)) - 3
        x0, x1 = max(x, pos - 3), min(x + w, pos + 1)
        if x1 > x0:
            with contextlib.suppress(curses.error):
                self.scr.chgat(y, x0, x1 - x0, self.attr("bg", "accent2", bold=True))

    # ----- time tracking -----

    def active_elapsed(self):
        a = self.store.active
        if not a:
            return 0
        try:
            start = dt.datetime.fromisoformat(a["start"])
            return max(0, int((dt.datetime.now() - start).total_seconds()))
        except (ValueError, KeyError):
            return 0

    def stop_tracking(self, save=True):
        a = self.store.active
        if not a:
            return 0
        secs = self.active_elapsed()
        t = self.store.get(a["id"])
        if secs >= 1:
            self.store.time_log.append({"t": a["start"], "s": secs, "id": a["id"],
                                        "p": t["project"] if t else ""})
        self.store.active = None
        if save:
            self.store.save()
        return secs

    def act_track(self):
        t = self.current()
        if not t:
            return
        a = self.store.active
        if a and a["id"] == t["id"]:
            secs = self.stop_tracking()
            self.say("stopped, logged " + fmt_duration(secs), "ok")
            return
        if a:
            self.stop_tracking(False)
        self.store.active = {"id": t["id"], "start": now_iso()}
        self.store.save()
        self.say("tracking: " + clip(t["title"], 40), "ok")

    def task_time(self, t):
        total = self.time_by.get(t["id"], 0)
        a = self.store.active
        if a and a["id"] == t["id"]:
            total += self.active_elapsed()
        return total

    # ----- links and jumping -----

    def jump_to(self, tid, push=True):
        t = self.store.get(tid)
        if not t:
            return
        if push:
            self.jump_stack.append((self.view, self.query, self.cur_id))
            del self.jump_stack[:-50]
        p = t["parent"]
        while p:
            pt = self.store.get(p)
            if not pt:
                break
            pt["folded"] = False
            p = pt["parent"]
        self.query = ""
        self.view = "done" if (t["done"] and not self.opts["show_done"]) else "all"
        self.cur_id = tid
        self.focus = "list"
        self.say("jumped to: " + clip(t["title"], 40), "accent2")

    def act_back(self):
        if not self.jump_stack:
            self.say("nowhere to go back to", "dim")
            return
        self.view, self.query, self.cur_id = self.jump_stack.pop()
        if not self.view_exists(self.view):
            self.view = "all"

    def open_url(self, url):
        cmd = self.opts.get("open_cmd") or os.environ.get("BROWSER") or \
            ("open" if sys.platform == "darwin" else "xdg-open")
        try:
            subprocess.Popen(shlex.split(cmd) + [url], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.say("opened " + clip(url, 50))
        except (OSError, ValueError):
            self.say("could not run " + cmd, "err")

    def act_links(self):
        t = self.current()
        if not t:
            return
        entries = []
        for kind, tgt, raw in task_links(self.store, t):
            if kind == "task":
                entries.append(("%s %s" % (self.sym["link"], tgt["title"]), "task", tgt["id"]))
            elif kind == "url":
                entries.append(("%s %s" % (self.sym["web"], raw), "url", raw))
            else:
                entries.append(("? [[%s]] not found" % raw, "none", None))
        for o in backlinks(self.store, t):
            entries.append(("%s from: %s" % (self.sym["back"], o["title"]), "task", o["id"]))
        if not entries:
            self.say("no links. write [[title]] or a url in notes, or press %s to link a task"
                     % self.first_key("link_add"), "dim", 5)
            return
        i = self.menu("links", [e[0] for e in entries])
        if i is None:
            return
        _, kind, payload = entries[i]
        if kind == "task":
            self.jump_to(payload)
        elif kind == "url":
            self.open_url(payload)

    def act_link_add(self):
        t = self.current()
        if not t:
            return
        items = [{"label": o["title"], "detail": self.task_detail(o), "kind": "task", "payload": o["id"],
                  "bias": -5 if o["done"] else 0}
                 for o in self.store.tasks if o is not t]
        pick = self.fuzzy("link to task", items)
        if not pick:
            return
        with self.edit():
            t["notes"] = (t["notes"] + "\n" if t["notes"] else "") + "[[%d]]" % pick["payload"]
        self.say("linked to: " + clip(pick["label"], 40), "ok")

    # ----- fuzzy finder -----

    def task_detail(self, t):
        bits = []
        if t["project"]:
            bits.append("@" + t["project"])
        bits += ["#" + g for g in t["tags"]]
        return " ".join(bits)

    def fuzzy(self, title, items, allow_new=False):
        q, sel = "", 0
        while True:
            res = []
            for i, it in enumerate(items):
                label = it["label"]
                if q:
                    r = fuzzy_score(q, label + "  " + it.get("detail", ""))
                    if r is None:
                        continue
                    res.append((-(r[0] + it.get("bias", 0)), i, it, [p for p in r[1] if p < len(label)]))
                else:
                    res.append((-it.get("bias", 0), i, it, []))
            res.sort(key=lambda r: (r[0], r[1]))
            shown = [(r[2], r[3]) for r in res[:60]]
            if allow_new and q.strip() and not any(it["label"].lower().lstrip("@#") == q.strip().lower() for it in items):
                shown.insert(0, ({"label": 'create "%s"' % q.strip(), "kind": "new", "text": q.strip()}, []))
            sel = max(0, min(sel, len(shown) - 1))
            self.backdrop()
            H, W = self.scr.getmaxyx()
            w = min(W - 4, 78)
            vis = max(1, min(12, H - 8, len(shown)))
            h = 5 + vis
            x, y = (W - w) // 2, max(1, (H - h) // 3)
            self.box(y, x, h, w, title)
            inner = w - 4
            self.fill(y + 1, x + 2, inner, self.attr("fg", "sel_bg"))
            self.put(y + 1, x + 2, "> " + q, self.attr("fg", "sel_bg", bold=True), inner)
            self.put(y + 1, x + 4 + cell_len(q), " ", self.attr("fg", "sel_bg", reverse=True))
            first = max(0, min(sel - vis // 2, len(shown) - vis))
            kinds = {"task": self.sym["check_off"], "project": "@", "tag": "#", "view": "~", "new": "+", "none": "-"}
            for r in range(vis):
                i = first + r
                if i >= len(shown):
                    break
                it, pos = shown[i]
                on = i == sel
                bg = "sel_bg" if on else "bg"
                yy = y + 3 + r
                if on:
                    self.fill(yy, x + 1, w - 2, self.attr("fg", bg))
                glyph = kinds.get(it.get("kind", "task"), " ")
                self.put(yy, x + 2, glyph[:2], self.attr("accent", bg, bold=True), 3)
                cx = x + 6
                label = it["label"]
                maxl = inner - 6 - (cell_len(it.get("detail", "")) + 2 if it.get("detail") else 0)
                maxl = max(10, maxl)
                shown_label = clip(label, maxl)
                for k, chr_ in enumerate(shown_label):
                    hit = k in pos
                    self.put(yy, cx, chr_, self.attr("today" if hit else "fg", bg, bold=hit or on))
                    cx += cw(chr_)
                if it.get("detail"):
                    self.put(yy, x + w - 2 - cell_len(it["detail"]), it["detail"], self.attr("tag", bg), inner // 2)
            if not shown:
                self.put(y + 3, x + 3, "no matches", self.attr("dim"))
            self.put(y + h - 2, x + 2, "type to filter  up/down move  enter select  esc cancel", self.attr("dim"), inner)
            self.scr.refresh()
            name, ch = self.read_key()
            if name == "enter":
                return shown[sel][0] if shown else None
            if name in ("esc", "ctrl-c"):
                return None
            if name in ("down", "ctrl-n", "tab"):
                sel += 1
            elif name in ("up", "ctrl-p", "shift-tab"):
                sel -= 1
            elif name == "backspace":
                q = q[:-1]
                sel = 0
            elif name == "ctrl-u":
                q, sel = "", 0
            elif name == "ctrl-w":
                q = q.rstrip().rsplit(" ", 1)[0] if " " in q.rstrip() else ""
                sel = 0
            elif ch:
                q += ch
                sel = 0

    def act_find(self):
        items = []
        for it in self.sidebar_items():
            if not it["head"]:
                items.append({"label": it["label"], "detail": "view", "kind": "view", "payload": it["key"], "bias": 50})
        projects = sorted({t["project"] for t in self.store.tasks if t["project"]}, key=str.lower)
        tags = sorted({g for t in self.store.tasks for g in t["tags"]})
        items += [{"label": "@" + p, "detail": "project", "kind": "project", "payload": p, "bias": 40} for p in projects]
        items += [{"label": "#" + g, "detail": "tag", "kind": "tag", "payload": g, "bias": 30} for g in tags]
        for t in sorted(self.store.tasks, key=lambda t: (t["done"], [-ord(c) for c in t["created"]])):
            items.append({"label": t["title"], "detail": self.task_detail(t), "kind": "task",
                          "payload": t["id"], "bias": -8 if t["done"] else 0})
        pick = self.fuzzy("find  (tasks, projects, tags, views)", items)
        if not pick:
            return
        kind = pick["kind"]
        if kind == "task":
            self.jump_to(pick["payload"])
        elif kind == "view":
            self.query = ""
            self.set_view(pick["payload"])
        elif kind == "project":
            self.query = ""
            self.set_view("p:" + pick["payload"])
        elif kind == "tag":
            self.query = ""
            self.set_view("t:" + pick["payload"])

    def edit_task(self, t):
        text = self.prompt("edit task", serialize(t), live=self.live_preview)
        if text is None:
            return
        p = parse_quick(text)
        if not p["title"]:
            self.say("title is empty", "err")
            return
        with self.edit():
            self.apply_parsed(t, p, False)
        self.say("updated")

    # ----- stats -----

    def stats_data(self, days):
        td = today()
        dates = [td - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]
        iso = [d.isoformat() for d in dates]
        done_c = collections.Counter(e["t"][:10] for e in self.store.done_log)
        time_c = collections.Counter()
        proj_t, task_t = collections.Counter(), collections.Counter()
        sessions = 0
        entries = list(self.store.time_log)
        a = self.store.active
        if a:
            live = self.store.get(a["id"])
            entries.append({"t": a["start"], "s": self.active_elapsed(), "id": a["id"],
                            "p": live["project"] if live else ""})
        for e in entries:
            day = e["t"][:10]
            time_c[day] += e["s"]
            if day >= iso[0]:
                proj_t[e.get("p") or "(none)"] += e["s"]
                task_t[e["id"]] += e["s"]
                sessions += 1
        cur, best = streak_info(done_c.keys(), td)
        open_ = [t for t in self.store.tasks if not t["done"]]
        return {
            "dates": dates,
            "done": [done_c.get(d, 0) for d in iso],
            "time": [time_c.get(d, 0) for d in iso],
            "done_c": done_c,
            "proj_t": proj_t,
            "task_t": task_t,
            "sessions": sessions,
            "streak": cur,
            "best": best,
            "open": len(open_),
            "overdue": sum(1 for t in open_ if t["due"] and t["due"] < td.isoformat()),
            "by_prio": [sum(1 for t in open_ if t["prio"] == p) for p in (3, 2, 1, 0)],
            "done_today": done_c.get(td.isoformat(), 0),
        }

    def tiles(self, y, items):
        W = self.scr.getmaxyx()[1]
        tw = max(10, (W - 4) // len(items))
        for i, (val, label, role) in enumerate(items):
            x = 2 + i * tw
            self.put(y, x, val, self.attr(role, bold=True), tw - 1)
            self.put(y + 1, x, label, self.attr("dim"), tw - 1)

    def vbars(self, y, x, h, w, vals, labels, role, grow):
        n = len(vals)
        colw = max(1, w // n)
        bw = max(1, colw - 1) if colw > 1 else 1
        mx = max(max(vals), 1)
        ascii_ = self.opts["ascii"]
        stride = max(1, -(-3 // colw))
        for i, v in enumerate(vals):
            bx = x + i * colw
            eighths = int(round(v / mx * h * 8 * grow))
            full, rem = divmod(eighths, 8)
            for r in range(h):
                ch = None
                if r < full:
                    ch = "#" if ascii_ else "█"
                elif r == full and rem > 0:
                    ch = "=" if ascii_ else BLOCKS[rem]
                if ch:
                    for k in range(bw):
                        self.put(y + h - 1 - r, bx + k, ch, self.attr(role))
            if v == 0:
                self.put(y + h - 1, bx, ".", self.attr("border"))
            if i % stride == 0:
                self.put(y + h, bx, labels[i], self.attr("dim"), colw * stride)

    def hbars(self, y, x, w, rows, role, grow):
        if not rows:
            self.put(y, x, "nothing yet", self.attr("dim"))
            return
        mx = max([r[1] for r in rows] + [1])
        lw = min(16, max(cell_len(r[0]) for r in rows))
        bw = max(4, w - lw - 12)
        ascii_ = self.opts["ascii"]
        for i, (label, val, text) in enumerate(rows):
            self.put(y + i, x, pad(label, lw), self.attr("fg"))
            n = val / mx * bw * grow
            full = int(n)
            frac = int((n - full) * 8)
            bar = "#" * full if ascii_ else "█" * full + (BLOCKS[frac] if frac else "")
            self.put(y + i, x + lw + 1, bar, self.attr(role))
            self.put(y + i, x + lw + 2 + bw, text, self.attr("dim"))

    def act_stats(self):
        ranges = [7, 14, 30]
        tabs = ["overview", "time", "heatmap", "estimates"]
        S = {"ri": 1, "tab": 0, "t0": time.time()}

        def render():
            H, W = self.scr.getmaxyx()
            grow = 1.0
            if self.opts.get("animations"):
                g = min(1.0, (time.time() - S["t0"]) * 2.0 * float(self.opts.get("anim_speed", 1.0)))
                grow = 1 - (1 - g) ** 3
                self.tick_override = 30 if g < 1.0 else None
            else:
                self.tick_override = None
            self.scr.erase()
            if H < 16 or W < 50:
                self.put(0, 0, "terminal too small for stats (q closes)", self.attr("err"))
                return
            self.draw_stats(H, W, tabs, S["tab"], ranges[S["ri"]], grow)

        self.backdrop = render
        try:
            while True:
                render()
                self.scr.refresh()
                name, _ = self.read_key()
                if name in ("q", "esc", "ctrl-c") or self.keymap.get(name) == "stats":
                    return
                if name in ("tab", "l", "right"):
                    S["tab"] = (S["tab"] + 1) % len(tabs)
                    S["t0"] = time.time()
                elif name in ("shift-tab", "h", "left"):
                    S["tab"] = (S["tab"] - 1) % len(tabs)
                    S["t0"] = time.time()
                elif name in ("1", "2", "3", "4"):
                    S["tab"] = int(name) - 1
                    S["t0"] = time.time()
                elif name == "r":
                    S["ri"] = (S["ri"] + 1) % len(ranges)
                    S["t0"] = time.time()
        finally:
            self.backdrop = self.draw
            self.tick_override = None

    def draw_stats(self, H, W, tabs, tab, days, grow):
        d = self.stats_data(days)
        self.fill(0, 0, W, self.attr("fg", "bar_bg"))
        x = self.put(0, 1, "synth.", self.attr("accent", "bar_bg", bold=True))
        x = self.put(0, x + 1, "stats", self.attr("accent2", "bar_bg", bold=True))
        x += 3
        for i, name in enumerate(tabs):
            on = i == tab
            x = self.put(0, x, " %d %s " % (i + 1, name), self.attr("accent" if on else "dim", "sel_bg" if on else "bar_bg", bold=on)) + 1
        self.put(0, W - 16, "last %d days " % days, self.attr("dim", "bar_bg"))
        self.fill(H - 1, 0, W, self.attr("fg", "bar_bg"))
        self.put(H - 1, 1, "tab or h/l switch   1 2 3 4 jump   r range   q close", self.attr("dim", "bar_bg"), W - 2)
        td = today()
        labels = [str(x.day) for x in d["dates"]]
        if tab == 0:
            avg = sum(d["done"]) / float(days)
            self.tiles(2, [
                (str(d["done_today"]), "done today", "ok"),
                (str(sum(d["done"])), "done in %d days" % days, "accent2"),
                ("%d day%s" % (d["streak"], "" if d["streak"] == 1 else "s"), "streak (best %d)" % d["best"], "today"),
                ("%.1f" % avg, "per day", "accent"),
                ("%d / %d" % (d["open"], d["overdue"]), "open / overdue", "p3" if d["overdue"] else "fg"),
            ])
            self.put(5, 2, "completed per day", self.attr("accent", bold=True))
            self.put(5, 22, "max %d" % max(d["done"] + [0]), self.attr("dim"))
            h = max(3, H - 15)
            self.vbars(6, 2, h, W - 6, d["done"], labels, "ok", grow)
            by = 6 + h + 2
            if by + 5 < H - 1:
                self.put(by, 2, "open tasks by priority", self.attr("accent", bold=True))
                names = ["high", "medium", "low", "none"]
                roles = ["p3", "p2", "p1", "dim"]
                rows = [(names[i], d["by_prio"][i], str(d["by_prio"][i])) for i in range(4)]
                mx = max([r[1] for r in rows] + [1])
                bw = min(W - 30, 50)
                for i, (label, val, text) in enumerate(rows):
                    self.put(by + 1 + i, 2, pad(label, 8), self.attr(roles[i]))
                    n = val / mx * bw * grow
                    full = int(n)
                    frac = int((n - full) * 8)
                    bar = "#" * full if self.opts["ascii"] else "█" * full + (BLOCKS[frac] if frac else "")
                    self.put(by + 1 + i, 11, bar, self.attr(roles[i]))
                    self.put(by + 1 + i, 12 + bw, text, self.attr("dim"))
        elif tab == 1:
            total = sum(d["time"])
            active_days = sum(1 for v in d["time"] if v)
            self.tiles(2, [
                (fmt_duration(total) if total else "0m", "tracked in %d days" % days, "accent2"),
                (fmt_duration(total / float(days)) if total else "0m", "per day", "accent"),
                (str(d["sessions"]), "sessions", "ok"),
                (str(active_days), "days with time", "today"),
            ])
            self.put(5, 2, "time tracked per day", self.attr("accent", bold=True))
            self.put(5, 26, "max " + fmt_duration(max(d["time"] + [0])), self.attr("dim"))
            h = max(3, H - 17)
            self.vbars(6, 2, h, W - 6, d["time"], labels, "accent2", grow)
            by = 6 + h + 2
            half = (W - 6) // 2
            if by + 6 < H:
                self.put(by, 2, "by project", self.attr("accent", bold=True))
                rows = [(k, v, fmt_duration(v)) for k, v in d["proj_t"].most_common(5)]
                self.hbars(by + 1, 2, half - 2, rows, "project", grow)
                self.put(by, 2 + half, "top tasks", self.attr("accent", bold=True))
                rows = []
                for tid, v in d["task_t"].most_common(5):
                    tt = self.store.get(tid)
                    rows.append((tt["title"] if tt else "(deleted)", v, fmt_duration(v)))
                self.hbars(by + 1, 2 + half, half - 2, rows, "tag", grow)
        elif tab == 3:
            self.draw_estimates(H, W, days, grow)
        else:
            weeks = max(8, min(26, (W - 10) // 2))
            start = td - dt.timedelta(days=td.weekday()) - dt.timedelta(weeks=weeks - 1)
            counts = d["done_c"]
            mx = max([counts.get((start + dt.timedelta(days=i)).isoformat(), 0) for i in range(weeks * 7)] + [1])
            self.put(2, 2, "completions, last %d weeks" % weeks, self.attr("accent", bold=True))
            roles = ["border", "dim", "accent", "accent2", "ok"]
            glyph = "#" if self.opts["ascii"] else "■"
            lastm = -1
            for col in range(weeks):
                if col / float(weeks) > grow:
                    break
                cx = 6 + col * 2
                first = start + dt.timedelta(weeks=col)
                if first.month != lastm and col % 1 == 0:
                    self.put(3, cx, first.strftime("%b"), self.attr("dim"))
                    lastm = first.month
                for row in range(7):
                    day = first + dt.timedelta(days=row)
                    if day > td:
                        continue
                    c = counts.get(day.isoformat(), 0)
                    lvl = 0 if c == 0 else min(4, 1 + (c - 1) * 4 // max(1, mx))
                    self.put(4 + row, cx, "." if lvl == 0 else glyph, self.attr(roles[lvl], bold=(lvl == 4)))
            for row, name in ((0, "Mon"), (2, "Wed"), (4, "Fri"), (6, "Sun")):
                self.put(4 + row, 2, name, self.attr("dim"))
            self.put(12, 6, "less", self.attr("dim"))
            for lvl in range(5):
                self.put(12, 11 + lvl * 2, "." if lvl == 0 else glyph, self.attr(roles[lvl]))
            self.put(12, 22, "more", self.attr("dim"))
            if H >= 24:
                wd = collections.Counter()
                for k, v in counts.items():
                    try:
                        wd[dt.date.fromisoformat(k).weekday()] += v
                    except ValueError:
                        pass
                names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                self.put(14, 2, "by weekday, all time", self.attr("accent", bold=True))
                self.hbars(15, 2, min(W - 6, 64), [(names[i], wd.get(i, 0), str(wd.get(i, 0))) for i in range(7)], "accent2", grow)
                self.put(23, 2, "%d completed all time" % sum(counts.values()), self.attr("dim"))

    # ----- calendar and agenda -----

    def due_map(self):
        m = {}
        for t in self.store.tasks:
            if t["due"]:
                m.setdefault(t["due"], []).append(t)
        for v in m.values():
            v.sort(key=lambda t: (t["done"], -t["prio"], t["title"].lower()))
        return m

    def date_heading(self, date, td):
        delta = (date - td).days
        base = date.strftime("%a %b %d")
        if delta == 0:
            return "Today  " + base
        if delta == 1:
            return "Tomorrow  " + base
        return "%s  in %dd" % (base, delta)

    def agenda_rows(self, by, td):
        rows = []
        tiso = td.isoformat()
        over = [t for k, ts in by.items() if k < tiso for t in ts if not t["done"]]
        over.sort(key=lambda t: t["due"])
        if over:
            rows.append(("head", "Overdue", None))
            rows += [("task", t) for t in over]
        horizon = (td + dt.timedelta(days=90)).isoformat()
        for k in sorted(x for x in by if tiso <= x <= horizon):
            date = dt.date.fromisoformat(k)
            rows.append(("head", self.date_heading(date, td), date))
            rows += [("task", t) for t in by[k]]
        nodate = [t for t in self.store.tasks if not t["due"] and not t["done"] and t["parent"] is None]
        if nodate:
            rows.append(("head", "No date (%d)" % len(nodate), None))
            rows += [("task", t) for t in nodate[:20]]
        return rows

    def cal_task_row(self, y, x, w, t, cur, show_due=False):
        bg = "sel_bg" if cur else "bg"
        if cur:
            self.fill(y, x, w, self.attr("fg", bg))
        on, off = self.sym["check_on"], self.sym["check_off"]
        cell = max(cell_len(on), cell_len(off))
        role = "done" if t["done"] else (self.prio_role(t["prio"]) if t["prio"] else "accent2")
        cx = x + 1
        self.put(y, cx, pad(on if t["done"] else off, cell), self.attr(role, bg, bold=not t["done"]))
        cx += cell + 1
        self.put(y, cx, pad("!" * t["prio"], 3), self.attr("done" if t["done"] else self.prio_role(t["prio"]), bg, bold=True))
        cx += 4
        right = ("@" + t["project"]) if t["project"] else ""
        if show_due and t["due"]:
            right += "  " + self.due_label(t)[0]
        rw = cell_len(right)
        title_w = max(6, x + w - cx - rw - 2)
        text = render_refs(self.store, t["title"], self.sym["link"])
        self.put(y, cx, pad(text, title_w), self.attr("done" if t["done"] else "fg", bg, bold=cur and not t["done"]))
        if right:
            self.put(y, x + w - rw - 1, right, self.attr("done" if t["done"] else "project", bg))

    def cal_month(self, S, by, rows, trows, H, W, ws, td):
        sel = S["sel"]
        cw_ = max(5, min(9, (W - 34) // 7))
        avail = H - 5
        chh = 3 if avail >= 18 else (2 if avail >= 12 else 1)
        gx, gy = 2, 3
        self.put(1, gx, sel.strftime("%B %Y"), self.attr("accent2", bold=True))
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        names = names[ws:] + names[:ws]
        for c, n in enumerate(names):
            self.put(2, gx + c * cw_, pad(n, cw_), self.attr("dim", bold=True))
        first = sel.replace(day=1)
        start = first - dt.timedelta(days=(first.weekday() - ws) % 7)
        dot = "o" if self.opts["ascii"] else "●"
        for r in range(6):
            for c in range(7):
                d = start + dt.timedelta(days=r * 7 + c)
                ts = by.get(d.isoformat(), [])
                open_ = [t for t in ts if not t["done"]]
                cx, cy = gx + c * cw_, gy + r * chh
                is_sel = d == sel
                bg = "sel_bg" if is_sel else "bg"
                if is_sel:
                    for k in range(chh):
                        self.fill(cy + k, cx, cw_ - 1, self.attr("fg", bg))
                if d == td:
                    nrole = "accent"
                elif d < td and open_:
                    nrole = "overdue"
                elif d.month != sel.month:
                    nrole = "dim"
                else:
                    nrole = "fg"
                self.put(cy, cx, "%2d" % d.day, self.attr(nrole, bg, bold=(d == td or is_sel)))
                if chh == 1:
                    if open_:
                        self.put(cy, cx + 3, str(len(open_)), self.attr("accent2", bg))
                    continue
                cap = cw_ - 2
                for i, t in enumerate(open_[:cap]):
                    if i == cap - 1 and len(open_) > cap:
                        self.put(cy + 1, cx + i, "+", self.attr("accent2", bg, bold=True))
                    else:
                        role = "overdue" if d < td else (self.prio_role(t["prio"]) if t["prio"] else "accent2")
                        self.put(cy + 1, cx + i, dot, self.attr(role, bg))
                if not open_ and ts:
                    self.put(cy + 1, cx, self.sym["check_on"][:cw_ - 1], self.attr("done", bg))
                if chh == 3 and open_:
                    self.put(cy + 2, cx, clip(open_[0]["title"], cw_ - 1), self.attr("dim", bg), cw_ - 1)
        px = gx + 7 * cw_ + 2
        pw = W - px - 1
        head = sel.strftime("%A, %b %d")
        if sel == td:
            head += "  (today)"
        self.put(1, px, head, self.attr("accent", bold=True))
        self.put(2, px, self.sym["hline"] * pw, self.attr("border"))
        cur_row = trows[S["idx"]] if (trows and S["focus"] == "list") else -1
        if not rows:
            self.put(3, px + 1, "nothing due. press a to add a task for this day", self.attr("dim"), pw)
        for i, r in enumerate(rows[:H - 6]):
            self.cal_task_row(3 + i, px, pw, r[1], i == cur_row)

    def cal_agenda(self, S, rows, trows, H, W):
        x, w = 2, W - 4
        h = H - 4
        cur_row = trows[S["idx"]] if trows else -1
        if cur_row >= 0:
            if cur_row < S["top"] + 1:
                S["top"] = max(0, cur_row - 1)
            if cur_row > S["top"] + h - 1:
                S["top"] = cur_row - h + 1
        S["top"] = max(0, min(S["top"], max(0, len(rows) - h)))
        if not rows:
            self.put(3, x, "no scheduled tasks. press a to add one", self.attr("dim"))
        for i in range(h):
            ri = S["top"] + i
            if ri >= len(rows):
                break
            r, y = rows[ri], 2 + i
            if r[0] == "head":
                role = "overdue" if r[1].startswith("Overdue") else "accent2"
                self.put(y, x, r[1], self.attr(role, bold=True))
                self.put(y, x + cell_len(r[1]) + 1, self.sym["hline"] * max(0, w - cell_len(r[1]) - 1), self.attr("border"))
            else:
                self.cal_task_row(y, x, w, r[1], ri == cur_row, show_due=False)

    def act_calendar(self, mode="month"):
        td = today()
        S = {"mode": mode, "sel": td, "focus": "grid" if mode == "month" else "list", "idx": 0, "top": 0}
        ws = 6 if self.opts.get("week_start") == "sun" else 0

        def compute():
            by = self.due_map()
            if S["mode"] == "month":
                rows = [("task", t) for t in by.get(S["sel"].isoformat(), [])]
            else:
                rows = self.agenda_rows(by, td)
            trows = [i for i, r in enumerate(rows) if r[0] == "task"]
            S["idx"] = max(0, min(S["idx"], len(trows) - 1)) if trows else 0
            cur = rows[trows[S["idx"]]][1] if trows else None
            cdate = S["sel"] if S["mode"] == "month" else None
            if S["mode"] == "agenda" and trows:
                for r in reversed(rows[:trows[S["idx"]]]):
                    if r[0] == "head":
                        cdate = r[2]
                        break
            return by, rows, trows, cur, cdate

        def render():
            H, W = self.scr.getmaxyx()
            data = compute()
            by, rows, trows, cur, cdate = data
            self.scr.erase()
            self.fill(0, 0, W, self.attr("fg", "bar_bg"))
            x = self.put(0, 1, "synth.", self.attr("accent", "bar_bg", bold=True))
            self.put(0, x + 1, "calendar" if S["mode"] == "month" else "agenda", self.attr("accent2", "bar_bg", bold=True))
            self.fill(H - 1, 0, W, self.attr("fg", "bar_bg"))
            if S["mode"] == "month":
                hint = "h/j/k/l day   [ ] month   t today   enter tasks   a add   v agenda   q close"
                if S["focus"] == "list":
                    hint = "j/k move   x done   < > shift day   m move   e edit   enter jump   esc back   a add"
            else:
                hint = "j/k move   x done   < > shift day   m move   e edit   enter jump   a add   v month   q close"
            self.put(H - 1, 1, hint, self.attr("dim", "bar_bg"), W - 2)
            if H < 12 or W < 40:
                self.put(2, 2, "terminal too small", self.attr("err"))
            elif S["mode"] == "month":
                self.cal_month(S, by, rows, trows, H, W, ws, td)
            else:
                self.cal_agenda(S, rows, trows, H, W)
            return data

        def add_for(date):
            text = self.prompt("new task due " + date.isoformat(), "", live=self.live_preview)
            if not text or not text.strip():
                return
            p = parse_quick(text)
            if not p["title"]:
                self.say("title is empty", "err")
                return
            with self.edit():
                t = self.store.add(p["title"])
                self.apply_parsed(t, p, True)
                if p["due"] is UNSET:
                    t["due"] = date.isoformat()
            self.hook("on_add", t)
            self.say("added for " + (t["due"] or ""))

        def shift(t, n):
            with self.edit():
                t["due"] = (dt.date.fromisoformat(t["due"]) + dt.timedelta(days=n)).isoformat()
            self.say("due " + t["due"])

        if self.scr.getmaxyx()[1] < 72 and S["mode"] == "month":
            S["mode"], S["focus"] = "agenda", "list"
        self.backdrop = render
        try:
            while True:
                by, rows, trows, cur, cdate = render()
                self.scr.refresh()
                name, ch = self.read_key()
                if name in ("tick", "resize", "mouse"):
                    continue
                if name in ("q", "ctrl-c") or self.keymap.get(name) == "calendar" or (name == "esc" and S["focus"] == "grid"):
                    return
                if name == "esc":
                    S["focus"] = "grid"
                    continue
                if name == "v":
                    S["mode"] = "agenda" if S["mode"] == "month" else "month"
                    S["focus"] = "list" if S["mode"] == "agenda" else "grid"
                    S["idx"] = S["top"] = 0
                    continue
                if S["mode"] == "month" and S["focus"] == "grid":
                    step = {"h": -1, "left": -1, "l": 1, "right": 1, "k": -7, "up": -7, "j": 7, "down": 7}.get(name)
                    if step:
                        S["sel"] += dt.timedelta(days=step)
                        S["idx"] = 0
                    elif name in ("[", "pgup"):
                        S["sel"] = add_months(S["sel"], -1)
                    elif name in ("]", "pgdn"):
                        S["sel"] = add_months(S["sel"], 1)
                    elif name == "t":
                        S["sel"] = td
                    elif name in ("enter", "tab") and trows:
                        S["focus"], S["idx"] = "list", 0
                    elif name == "a":
                        add_for(S["sel"])
                    continue
                if name in ("j", "down"):
                    S["idx"] = min(len(trows) - 1, S["idx"] + 1)
                elif name in ("k", "up"):
                    S["idx"] = max(0, S["idx"] - 1)
                elif name == "g":
                    S["idx"] = 0
                elif name == "G":
                    S["idx"] = max(0, len(trows) - 1)
                elif name == "tab" and S["mode"] == "month":
                    S["focus"] = "grid"
                elif name == "a":
                    add_for(cdate or td)
                elif cur is None:
                    continue
                elif name in ("x", "space"):
                    with self.edit():
                        self.complete(cur, not cur["done"])
                elif name in (">", "<") and cur["due"]:
                    shift(cur, 1 if name == ">" else -1)
                elif name == "m":
                    text = self.prompt("move to date (fri, +3d, 12-25, none)", cur["due"] or "")
                    if text is not None:
                        try:
                            nd = parse_date(text)
                            with self.edit():
                                cur["due"] = nd.isoformat() if nd else None
                        except ValueError as exc:
                            self.say(str(exc), "err")
                elif name == "e":
                    self.edit_task(cur)
                elif name == "enter":
                    self.jump_to(cur["id"])
                    return
        finally:
            self.backdrop = self.draw

    # ----- focus mode -----

    def focus_elapsed(self, F):
        return F["acc"] + ((time.monotonic() - F["start"]) if F["running"] else 0.0)

    def focus_flush(self, t, F):
        if not F["running"]:
            return
        now = time.monotonic()
        seg = now - F["start"]
        F["acc"] += seg
        F["start"] = now
        if F["phase"] == "work" and seg >= 1:
            self.store.time_log.append({"t": F["iso"], "s": int(seg), "id": t["id"], "p": t["project"]})
            F["logged"] += int(seg)
            self.store.save()
        F["iso"] = now_iso()

    def act_focus(self):
        t = self.current()
        if not t:
            self.say("select a task first", "err")
            return
        if t["done"]:
            self.say("that task is already done", "err")
            return
        self.stop_tracking()
        o = self.opts
        mins = {"work": o["focus_work"], "break": o["focus_break"], "long": o["focus_long"]}
        rounds_per = max(1, int(o["focus_rounds"]))
        F = {"phase": "work", "dur": mins["work"] * 60, "acc": 0.0, "start": time.monotonic(),
             "iso": now_iso(), "running": True, "rounds": 0, "logged": 0, "rounds_per": rounds_per}
        self.hook("on_focus_start", t)
        self.backdrop = lambda: self.draw_focus(t, F)
        completed = False
        try:
            while True:
                self.tick_override = 100 if o.get("animations") else 500
                rem = F["dur"] - self.focus_elapsed(F)
                if F["running"] and rem <= 0:
                    self.focus_advance(t, F, mins)
                elif F["running"] and F["phase"] == "work" and time.monotonic() - F["start"] >= 60:
                    self.focus_flush(t, F)
                self.draw_focus(t, F)
                self.scr.refresh()
                name, _ = self.read_key()
                if name in ("q", "esc", "ctrl-c"):
                    break
                if name == "x":
                    completed = True
                    break
                if name == "space":
                    if F["running"]:
                        self.focus_flush(t, F)
                        F["running"] = False
                    else:
                        F["running"] = True
                        F["start"] = time.monotonic()
                        F["iso"] = now_iso()
                elif name == "n":
                    self.focus_advance(t, F, mins, skipped=True)
                elif name in ("+", "="):
                    F["dur"] += 300
                elif name == "-":
                    F["dur"] = max(60, F["dur"] - 300)
                elif name == "r":
                    self.focus_flush(t, F)
                    F["acc"] = 0.0
                    F["start"] = time.monotonic()
        finally:
            self.focus_flush(t, F)
            self.backdrop = self.draw
            self.tick_override = None
        if completed:
            with self.edit():
                self.complete(t, True)
        self.hook("on_focus_end", t)
        self.say("focus ended: %s logged, %d round%s" % (fmt_duration(F["logged"]), F["rounds"], "" if F["rounds"] == 1 else "s"), "ok", 5)

    def focus_advance(self, t, F, mins, skipped=False):
        self.focus_flush(t, F)
        prev = F["phase"]
        if prev == "work":
            F["rounds"] += 1
            nxt = "long" if F["rounds"] % F["rounds_per"] == 0 else "break"
        else:
            nxt = "work"
        F["phase"], F["dur"], F["acc"] = nxt, mins[nxt] * 60, 0.0
        F["start"] = time.monotonic()
        F["iso"] = now_iso()
        F["running"] = bool(self.opts.get("focus_auto", True)) or skipped
        if not skipped and self.opts.get("focus_bell", True):
            with contextlib.suppress(curses.error):
                curses.beep()
        self.hook("on_focus_end" if prev == "work" else "on_focus_start", t)
        self.say(("break time" if nxt != "work" else "back to work"), "ok", 4)

    def draw_focus(self, t, F):
        scr = self.scr
        H, W = scr.getmaxyx()
        scr.erase()
        now = time.time()
        animated = self.opts.get("animations")
        ascii_ = self.opts["ascii"]
        phase = F["phase"]
        role = {"work": "accent", "break": "ok", "long": "accent2"}[phase]
        rem = max(0.0, F["dur"] - self.focus_elapsed(F))
        secs = int(math.ceil(rem))
        clock = fmt_duration(secs, True)
        block = "#" if ascii_ else "█"
        glyphs = [BIG_DIGITS[c] for c in clock]
        big_w = sum(len(g[0]) * 2 for g in glyphs) + 2 * (len(glyphs) - 1)
        big = H >= 22 and W >= big_w + 4
        top = max(1, (H - (18 if big else 9)) // 2)

        def center(y, text, attr):
            self.put(y, max(0, (W - cell_len(text)) // 2), text, attr)

        label = {"work": "FOCUS", "break": "BREAK", "long": "LONG BREAK"}[phase]
        if not F["running"]:
            label += "  (paused)"
        center(top, label, self.attr(role, bold=True))
        blink_off = (not F["running"]) and int(now * 2) % 2 == 1
        if big:
            for r in range(5):
                ln = "  ".join("".join(ch * 2 for ch in g[r]) for g in glyphs).replace("#", block)
                if not blink_off:
                    center(top + 2 + r, ln, self.attr(role if F["running"] else "dim", bold=True))
            base = top + 9
        else:
            if not blink_off:
                center(top + 2, clock, self.attr(role if F["running"] else "dim", bold=True))
            base = top + 4
        center(base, clip(render_refs(self.store, t["title"], self.sym["link"]), W - 6), self.attr("fg", bold=True))
        meta = "tracked " + fmt_duration(self.task_time(t))
        if t.get("est"):
            meta += " of " + fmt_duration(t["est"]) + " estimate"
        center(base + 1, meta, self.attr("dim"))
        bw = min(W - 10, 60)
        frac = 1.0 - (rem / F["dur"] if F["dur"] else 0)
        n = max(0.0, min(1.0, frac)) * bw
        full, part = int(n), int((n - int(n)) * 8)
        bx = (W - bw) // 2
        self.put(base + 3, bx, self.sym["hline"] * bw, self.attr("border"))
        bar = block * full + (BLOCKS[part] if part and not ascii_ and full < bw else "")
        self.put(base + 3, bx, bar, self.attr(role, bold=True))
        cyc = F["rounds"] % F["rounds_per"]
        if phase == "long":
            cyc = F["rounds_per"]
        dots = []
        for i in range(F["rounds_per"]):
            if i < cyc:
                dots.append("*" if ascii_ else "●")
            elif i == cyc and phase == "work":
                dots.append("@" if ascii_ else "◉")
            else:
                dots.append("o" if ascii_ else "○")
        center(base + 5, " ".join(dots) + "   round %d" % (F["rounds"] + (1 if phase == "work" else 0)), self.attr("dim"))
        if phase != "work" and F["running"]:
            cycle = (now % 8.0) / 8.0 if animated else 0.25
            amp = 0.5 - 0.5 * math.cos(2 * math.pi * cycle)
            width = 3 + int(amp * max(4, min(W // 2, 30)))
            center(base + 7, self.sym["hline"] * width, self.attr(role))
            center(base + 8, "breathe in" if cycle < 0.5 else "breathe out", self.attr("dim"))
        if H >= 18:
            t_ = now if animated else 0.0
            thirds = ["accent", "tag", "accent2"]
            for y, spd in ((H - 5, 1.6), (H - 4, 2.3)):
                for x in range(W - 1):
                    v = (math.sin(x * 0.17 + t_ * spd) + math.sin(x * 0.06 - t_ * 0.9 * spd)) / 4 + 0.5
                    lvl = max(1, min(8, int(v * 8.99)))
                    r = "dim" if y == H - 5 else (thirds[min(2, x * 3 // max(1, W))] if phase == "work" else role)
                    self.put(y, x, "~" if ascii_ else BLOCKS[lvl], self.attr(r))
        self.put(H - 1, 1, "space pause   n skip   + - 5 min   r restart   x done   q leave", self.attr("dim"), W - 2)
        if self.msg and time.time() < self.msg_until:
            center(H - 2, self.msg, self.attr(self.msg_kind, bold=True))

    # ----- v1.2 helpers -----

    def s(self, key, default):
        """Look up a user overridable UI string."""
        v = self.opts.get("strings", {}).get(key)
        return v if isinstance(v, str) and v else default

    def view_opt(self, key):
        """Per view option, falling back to the global one."""
        for v in self.opts.get("views", []):
            if isinstance(v, dict) and v.get("name") and "v:" + v["name"] == self.view and key in v:
                return v[key]
        return self.opts.get(key)

    def sorted_tasks(self, items):
        mode = self.view_opt("sort")
        spec = self.opts.get("sorts", {}).get(mode)
        if spec is None:
            spec = SORT_BUILTIN.get(mode, "")
        if not spec:
            return list(items)
        return sort_items(list(items), spec, {"time_by": self.time_by, "store": self.store})

    def sort_names(self):
        return SORTS + [k for k in self.opts.get("sorts", {}) if k not in SORTS]

    def style_for(self, t, td):
        """Merged rule styling for a task, cached per draw."""
        return match_rules(self.rules, t, td) if self.rules else {}

    # ----- multiline text editor -----

    def edit_text(self, title, initial="", footer="", tmpl=None):
        """Built-in multiline editor with soft wrap. Returns text or None if cancelled."""
        lines = initial.split("\n") if initial else [""]
        cy, cx, top, want = len(lines) - 1, len(lines[-1]), 0, None
        changed = False

        def ranges(line, width):
            out, start, cur = [], 0, 0
            for i, ch in enumerate(line):
                c = cw(ch)
                if cur + c > width:
                    out.append((start, i))
                    start, cur = i, 0
                cur += c
            out.append((start, len(line)))
            return out

        while True:
            self.backdrop()
            H, W = self.scr.getmaxyx()
            w, h = min(W - 2, 104), max(8, H - 2)
            x, y = (W - w) // 2, 1
            inner = max(10, w - 4)
            vis = h - 4
            visual = []
            for li, ln in enumerate(lines):
                for a, b in ranges(ln, inner - 1):
                    visual.append((li, a, b))
            crow = 0
            for k, (li, a, b) in enumerate(visual):
                if li == cy:
                    crow = k
                    if a <= cx < b:
                        break
            if crow < top:
                top = crow
            if crow >= top + vis:
                top = crow - vis + 1
            self.box(y, x, h, w, title)
            for r in range(vis):
                k = top + r
                if k >= len(visual):
                    break
                li, a, b = visual[k]
                self.put(y + 2 + r, x + 2, lines[li][a:b], self.attr("fg"), inner)
            li, a, b = visual[crow]
            ccol = cell_len(lines[li][a:cx])
            under = lines[cy][cx] if cx < len(lines[cy]) else " "
            self.put(y + 2 + crow - top, x + 2 + ccol, under, self.attr("fg", reverse=True))
            words = sum(word_count(ln) for ln in lines)
            status = "%d words  line %d/%d" % (words, cy + 1, len(lines))
            self.put(y + 1, x + 2, clip(footer or "markdown friendly. [[task]] links work.", inner - 24), self.attr("dim"))
            self.put(y + 1, x + w - 2 - cell_len(status), status, self.attr("accent2"))
            self.put(y + h - 2, x + 2, "ctrl-s or ctrl-d save   esc cancel   ctrl-t timestamp   tab indent   ctrl-k kill line",
                     self.attr("dim"), inner)
            self.scr.refresh()
            name, ch = self.read_key()
            if name in ("tick", "resize", "mouse"):
                continue
            if name in ("ctrl-s", "ctrl-d"):
                return "\n".join(lines)
            if name in ("esc", "ctrl-c"):
                if not changed or self.confirm("discard changes?"):
                    return None
                continue
            moved_v = False
            if name == "left":
                if cx:
                    cx -= 1
                elif cy:
                    cy -= 1
                    cx = len(lines[cy])
            elif name == "right":
                if cx < len(lines[cy]):
                    cx += 1
                elif cy + 1 < len(lines):
                    cy, cx = cy + 1, 0
            elif name in ("up", "down", "pgup", "pgdn"):
                step = {"up": -1, "down": 1, "pgup": -vis, "pgdn": vis}[name]
                if want is None:
                    want = ccol
                nk = max(0, min(len(visual) - 1, crow + step))
                nl, na, nb = visual[nk]
                col, idx = 0, na
                while idx < nb and col + cw(lines[nl][idx]) <= want:
                    col += cw(lines[nl][idx])
                    idx += 1
                cy, cx = nl, idx
                moved_v = True
            elif name == "home":
                cx = 0
            elif name == "end":
                cx = len(lines[cy])
            elif name == "ctrl-a":
                cx = visual[crow][1]
            elif name == "ctrl-e":
                cx = visual[crow][2]
            elif name == "enter":
                head, tail = lines[cy][:cx], lines[cy][cx:]
                m = re.match(r"^(\s*(?:[-*]|\d+\.)\s+(?:\[[ x]\]\s+)?)", head)
                lead = m.group(1) if m else re.match(r"^\s*", head).group(0)
                if m and head[m.end():].strip() == "":
                    lines[cy] = tail
                    cx = 0
                else:
                    lines[cy] = head
                    lines.insert(cy + 1, lead + tail)
                    cy, cx = cy + 1, len(lead)
                changed = True
            elif name == "backspace":
                if cx:
                    lines[cy] = lines[cy][:cx - 1] + lines[cy][cx:]
                    cx -= 1
                    changed = True
                elif cy:
                    cx = len(lines[cy - 1])
                    lines[cy - 1] += lines[cy]
                    del lines[cy]
                    cy -= 1
                    changed = True
            elif name == "delete":
                if cx < len(lines[cy]):
                    lines[cy] = lines[cy][:cx] + lines[cy][cx + 1:]
                    changed = True
                elif cy + 1 < len(lines):
                    lines[cy] += lines[cy + 1]
                    del lines[cy + 1]
                    changed = True
            elif name == "ctrl-k":
                if cx < len(lines[cy]):
                    lines[cy] = lines[cy][:cx]
                elif cy + 1 < len(lines):
                    lines[cy] += lines[cy + 1]
                    del lines[cy + 1]
                changed = True
            elif name == "ctrl-u":
                lines[cy] = lines[cy][cx:]
                cx = 0
                changed = True
            elif name == "ctrl-w":
                j = cx
                while j > 0 and lines[cy][j - 1] == " ":
                    j -= 1
                while j > 0 and lines[cy][j - 1] != " ":
                    j -= 1
                lines[cy] = lines[cy][:j] + lines[cy][cx:]
                cx = j
                changed = True
            elif name == "ctrl-t":
                stamp = "[%s] " % dt.datetime.now().strftime(self.opts.get("note_stamp", "%Y-%m-%d %H:%M"))
                lines[cy] = lines[cy][:cx] + stamp + lines[cy][cx:]
                cx += len(stamp)
                changed = True
            elif name == "tab":
                lines[cy] = lines[cy][:cx] + "  " + lines[cy][cx:]
                cx += 2
                changed = True
            elif name == "alt-b":
                while cx > 0 and lines[cy][cx - 1] == " ":
                    cx -= 1
                while cx > 0 and lines[cy][cx - 1] != " ":
                    cx -= 1
            elif name == "alt-f":
                while cx < len(lines[cy]) and lines[cy][cx] == " ":
                    cx += 1
                while cx < len(lines[cy]) and lines[cy][cx] != " ":
                    cx += 1
            elif ch and ch.isprintable():
                lines[cy] = lines[cy][:cx] + ch + lines[cy][cx:]
                cx += 1
                changed = True
            if not moved_v:
                want = None

    # ----- notes -----

    def act_notes(self):
        t = self.current()
        if not t:
            return
        if self.opts.get("notes_editor") == "external":
            self.notes_external(t)
            return
        text = self.edit_text("notes: " + clip(t["title"], 44), t["notes"])
        if text is None:
            return
        text = text.rstrip()
        if text != t["notes"]:
            with self.edit():
                t["notes"] = text
            self.hook("on_note", t)
            self.say("notes saved (%d words)" % word_count(text), "ok")

    def act_note_add(self):
        t = self.current()
        if not t:
            return
        line = self.prompt("quick note for: " + clip(t["title"], 40))
        if not line or not line.strip():
            return
        stamp = dt.datetime.now().strftime(self.opts.get("note_stamp", "%Y-%m-%d %H:%M"))
        entry = "- [%s] %s" % (stamp, line.strip())
        with self.edit():
            t["notes"] = (t["notes"].rstrip() + "\n" if t["notes"].strip() else "") + entry
        self.detail_scroll = 10 ** 6
        self.hook("on_note", t)
        self.say("note added", "ok")

    def copy_text(self, text):
        cmds = [self.opts.get("copy_cmd")] if self.opts.get("copy_cmd") else []
        cmds += ["wl-copy", "xclip -selection clipboard", "xsel -ib", "pbcopy"]
        for c in cmds:
            if not c:
                continue
            argv = shlex.split(c)
            if not shutil.which(argv[0]):
                continue
            try:
                subprocess.run(argv, input=text.encode("utf-8"), timeout=3, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except (OSError, subprocess.SubprocessError):
                continue
        try:
            import base64
            sys.stdout.write("\x1b]52;c;%s\x07" % base64.b64encode(text.encode("utf-8")).decode())
            sys.stdout.flush()
            return True
        except (OSError, ValueError):
            return False

    def act_yank(self):
        ts = self.targets()
        if not ts:
            return
        if len(ts) == 1:
            t = ts[0]
            kinds = ["title", "title and notes", "markdown checklist item"]
            i = self.menu("copy to clipboard", kinds)
            if i is None:
                return
            if i == 0:
                text = t["title"]
            elif i == 1:
                text = t["title"] + ("\n\n" + t["notes"] if t["notes"].strip() else "")
            else:
                text = "- [%s] %s" % ("x" if t["done"] else " ", t["title"])
                if t["notes"].strip():
                    text += "\n" + "\n".join("  " + ln for ln in t["notes"].splitlines())
        else:
            text = "\n".join("- [%s] %s" % ("x" if t["done"] else " ", t["title"]) for t in ts)
        self.say("copied" if self.copy_text(text) else "no clipboard tool found", "ok")

    def act_duplicate(self):
        t = self.current()
        if not t:
            return
        with self.edit():
            mapping = {}
            order = [t] + self.store.descendants(t["id"])
            pos = max(self.store.tasks.index(x) for x in order) + 1
            for src in order:
                c = self.store.add(src["title"] + (" (copy)" if src is t else ""), parent=mapping.get(src["parent"], t["parent"]))
                self.store.tasks.remove(c)
                self.store.tasks.insert(pos, c)
                pos += 1
                for k in ("prio", "due", "tags", "project", "notes", "repeat", "est"):
                    c[k] = copy.deepcopy(src[k])
                mapping[src["id"]] = c["id"]
        self.cur_id = mapping[t["id"]]
        self.say("duplicated", "ok")

    def act_detail_scroll(self, step):
        self.detail_scroll = max(0, self.detail_scroll + step)

    # ----- dependencies -----

    def dep_items(self, t, want_blocker):
        items = []
        for o in self.store.tasks:
            if o is t:
                continue
            if want_blocker:
                if o["id"] in t.get("deps", []) or would_cycle(self.store, t["id"], o["id"]):
                    continue
            else:
                if t["id"] in o.get("deps", []) or would_cycle(self.store, o["id"], t["id"]):
                    continue
            items.append({"label": o["title"], "detail": self.task_detail(o), "kind": "task",
                          "payload": o["id"], "bias": -20 if o["done"] else 0})
        return items

    def act_deps(self):
        t = self.current()
        if not t:
            return
        opts_, acts = [], []
        opts_.append("needs another task first (pick a blocker)")
        acts.append(("need", None))
        opts_.append("this task blocks another (pick one)")
        acts.append(("block", None))
        for d in [self.store.get(i) for i in t.get("deps", [])]:
            if d:
                opts_.append("remove blocker: " + clip(d["title"], 36))
                acts.append(("rm", d["id"]))
        for o in waiting_on(self.store, t) + [x for x in self.store.tasks if t["id"] in x.get("deps", []) and x["done"]]:
            opts_.append("remove dependent: " + clip(o["title"], 34))
            acts.append(("rmdep", o["id"]))
        if t.get("deps"):
            opts_.append("clear all blockers")
            acts.append(("clear", None))
        i = self.menu("dependencies: " + clip(t["title"], 30), opts_)
        if i is None:
            return
        kind, payload = acts[i]
        if kind in ("need", "block"):
            items = self.dep_items(t, kind == "need")
            if not items:
                self.say("nothing to pick (cycles are blocked)", "err")
                return
            pick = self.fuzzy("blocked by" if kind == "need" else "blocks", items)
            if not pick:
                return
            with self.edit():
                if kind == "need":
                    t.setdefault("deps", []).append(pick["payload"])
                else:
                    self.store.get(pick["payload"]).setdefault("deps", []).append(t["id"])
            self.say("dependency added", "ok")
        elif kind == "rm":
            with self.edit():
                t["deps"] = [d for d in t["deps"] if d != payload]
            self.say("blocker removed")
        elif kind == "rmdep":
            with self.edit():
                o = self.store.get(payload)
                o["deps"] = [d for d in o["deps"] if d != t["id"]]
            self.say("dependent removed")
        elif kind == "clear":
            with self.edit():
                t["deps"] = []
            self.say("blockers cleared")

    def blocked_gate(self, ts):
        """Return False when completing the given tasks should not go ahead."""
        mode = self.opts.get("blocked_done", "warn")
        if mode == "allow":
            return True
        stuck = [t for t in ts if not t["done"] and blockers(self.store, t)]
        if not stuck:
            return True
        if mode == "deny":
            self.say("blocked by: " + clip(blockers(self.store, stuck[0])[0]["title"], 40), "err")
            return False
        return self.confirm("%d task%s still blocked. finish anyway?" % (len(stuck), "" if len(stuck) == 1 else "s"))

    # ----- snooze -----

    def act_snooze(self):
        ts = self.targets()
        if not ts:
            return
        td = today()
        opts_ = [("tomorrow", td + dt.timedelta(days=1)), ("in 3 days", td + dt.timedelta(days=3)),
                 ("next monday", parse_date("mon", td)), ("in a week", td + dt.timedelta(days=7)),
                 ("in a month", add_months(td, 1))]
        labels = ["%s  (%s)" % (a, b.strftime("%a %d %b")) for a, b in opts_]
        labels += ["pick a date...", "wake now (clear)"]
        i = self.menu("snooze until", labels)
        if i is None:
            return
        if i < len(opts_):
            until = opts_[i][1]
        elif i == len(opts_):
            text = self.prompt("snooze until  (fri, +3d, 12-25, 2026-12-25)")
            if not text:
                return
            try:
                until = parse_date(text.strip(), td)
            except ValueError:
                self.say("could not read that date", "err")
                return
            if until is None or until <= td:
                self.say("pick a date after today", "err")
                return
        else:
            until = None
        with self.edit():
            for t in ts:
                t["snooze"] = until.isoformat() if until else ""
                t["woke"] = ""
        if until:
            self.hook("on_snooze", ts[0])
            self.say("snoozed until " + until.strftime("%a %d %b"), "ok")
        else:
            self.say("awake")

    def wake_check(self):
        td = today()
        iso = td.isoformat()
        if self.wake_day == iso:
            return
        self.wake_day = iso
        woke = [t for t in self.store.tasks if t.get("snooze") and not t["done"] and t["snooze"] <= iso]
        for t in self.store.tasks:
            if t.get("woke") and t["woke"] != iso:
                t["woke"] = ""
        if woke:
            for t in woke:
                t["snooze"] = ""
                t["woke"] = iso
            self.store.save()
            self.hook("on_wake", woke[0])
            self.say("%d snoozed task%s woke up" % (len(woke), "" if len(woke) == 1 else "s"), "today", 6)

    # ----- templates and custom actions -----

    def act_template(self):
        tpls = [t for t in self.opts.get("templates", []) if isinstance(t, dict) and t.get("name")]
        if not tpls:
            self.say("no templates. add [[templates]] to the config", "err", 5)
            return
        i = self.menu("new from template", [t["name"] for t in tpls])
        if i is None:
            self.say("")
            return
        self.run_template(tpls[i])

    def run_template(self, spec):
        td = today()
        values = {"date": td.isoformat(), "today": td.isoformat(), "weekday": td.strftime("%A")}
        for var in template_vars(spec):
            v = self.prompt("%s: %s" % (spec["name"], var))
            if v is None:
                return
            values[var] = v.strip()
        title = fill_template(spec.get("title", spec["name"]), values)
        p = parse_quick(title)
        if not p["title"]:
            p["title"] = spec["name"]
        cur = self.current()
        with self.edit():
            t = self.store.add(p["title"])
            self.add_defaults(t)
            self.apply_parsed(t, p, True)
            if spec.get("tags"):
                t["tags"] = sorted(set(t["tags"]) | set(spec["tags"]))
            if spec.get("project") and not t["project"]:
                t["project"] = spec["project"]
            if spec.get("prio") and not t["prio"]:
                t["prio"] = int(spec["prio"])
            if spec.get("est") and not t["est"]:
                t["est"] = parse_duration(str(spec["est"])) or 0
            if spec.get("due") and not t["due"]:
                with contextlib.suppress(ValueError):
                    d = parse_date(fill_template(spec["due"], values), td)
                    t["due"] = d.isoformat() if d else None
            if spec.get("repeat") and not t["repeat"]:
                t["repeat"] = spec["repeat"]
            if spec.get("notes"):
                t["notes"] = fill_template(spec["notes"], values)
            for sub in spec.get("subtasks", []):
                sp = parse_quick(fill_template(sub, values))
                if not sp["title"]:
                    continue
                c = self.store.add(sp["title"], parent=t["id"])
                self.store.tasks.remove(c)
                last = [t] + self.store.descendants(t["id"])
                self.store.tasks.insert(max(self.store.tasks.index(x) for x in last) + 1, c)
                c["project"], c["tags"] = t["project"], list(t["tags"])
                self.apply_parsed(c, dict(sp, tags=sorted(set(sp["tags"]) | set(t["tags"])),
                                          project=sp["project"] or t["project"]), True)
        self.hook("on_add", t)
        self.cur_id = t["id"]
        self.anim("add", t["id"], 0.4)
        self.say("created from template: " + spec["name"], "ok")

    def custom_actions(self):
        return [a for a in self.opts.get("actions", []) if isinstance(a, dict) and a.get("name") and a.get("cmd")]

    def act_actions_menu(self):
        acts = self.custom_actions()
        tpls = [t for t in self.opts.get("templates", []) if isinstance(t, dict) and t.get("name")]
        entries = [("action", a) for a in acts] + [("template", t) for t in tpls]
        if not entries:
            self.say("no actions or templates in the config yet", "err", 5)
            return
        labels = [("run: " if k == "action" else "new: ") + e["name"] for k, e in entries]
        i = self.menu("actions and templates", labels)
        if i is None:
            return
        kind, e = entries[i]
        if kind == "action":
            self.run_action(e)
        else:
            self.run_template(e)

    def run_action(self, a):
        t = self.current()
        if a.get("confirm") and not self.confirm("run %s?" % a["name"]):
            return
        env = dict(os.environ, SYNTH_EVENT="action", SYNTH_ACTION=a["name"], SYNTH_DATA=self.store.path,
                   SYNTH_VIEW=self.view, SYNTH_QUERY=self.query)
        if t:
            env.update(SYNTH_ID=str(t["id"]), SYNTH_TITLE=t["title"], SYNTH_NOTES=t["notes"],
                       SYNTH_PROJECT=t["project"], SYNTH_TAGS=" ".join(t["tags"]), SYNTH_DUE=t["due"] or "")
        env["SYNTH_IDS"] = " ".join(str(x["id"]) for x in self.targets())
        mode = a.get("mode", "bg")
        if mode == "fg":
            curses.def_prog_mode()
            curses.endwin()
            try:
                subprocess.run(a["cmd"], shell=True, env=env)
                if a.get("pause", True):
                    input("\nenter to return to synth ")
            except (OSError, EOFError, KeyboardInterrupt):
                pass
            curses.reset_prog_mode()
            self.scr.clear()
        elif mode == "capture":
            try:
                r = subprocess.run(a["cmd"], shell=True, env=env, capture_output=True, text=True, timeout=30)
                out = (r.stdout + r.stderr).rstrip().splitlines() or ["(no output)"]
            except (OSError, subprocess.TimeoutExpired) as exc:
                out = [str(exc)]
            self.pager(a["name"], [(ln, "fg") for ln in out])
        else:
            with contextlib.suppress(OSError):
                subprocess.Popen(a["cmd"], shell=True, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.say("ran " + a["name"], "ok")
        if a.get("reload", True):
            self.store.load()
            self.store.invalidate()


    def snoozed_chain(self, t, td):
        seen = 0
        while t is not None and seen < 50:
            if is_snoozed(t, td):
                return True
            t = self.store.get(t["parent"]) if t["parent"] else None
            seen += 1
        return False

    # ----- screen helpers -----

    def screen_bar(self, W, title, right=""):
        self.fill(0, 0, W, self.attr("fg", "bar_bg"))
        x = self.put(0, 1, self.s("app_name", "synth."), self.attr("accent", "bar_bg", bold=True))
        x = self.put(0, x + 1, title, self.attr("accent2", "bar_bg", bold=True))
        if right:
            self.put(0, max(x + 2, W - cell_len(right) - 2), right, self.attr("dim", "bar_bg"))
        return x

    def screen_foot(self, H, W, text):
        self.fill(H - 1, 0, W, self.attr("fg", "bar_bg"))
        self.put(H - 1, 1, text, self.attr("dim", "bar_bg"), W - 2)

    def progress_bar(self, frac, width):
        s = self.sym
        n = int(round(max(0.0, min(1.0, frac)) * width))
        return s["bar_on"] * n + s["bar_off"] * (width - n)

    def screen_loop(self, render, handle, tick=None):
        self.backdrop = render
        try:
            while True:
                render()
                self.scr.refresh()
                name, ch = self.read_key()
                if name in ("tick", "resize", "mouse"):
                    continue
                if handle(name, ch):
                    return
        finally:
            self.backdrop = self.draw
            self.tick_override = None

    # ----- daily journal -----

    def journal_days(self):
        return sorted(k for k, v in self.store.journal.items() if v.strip())

    def journal_edit(self, d):
        iso = d.isoformat()
        cur = self.store.journal.get(iso, "")
        if not cur.strip():
            tpl = self.opts.get("journal_template") or DEFAULT_JOURNAL_TEMPLATE
            cur = fill_template(tpl, journal_vars(self.store, d))
        text = self.edit_text("journal: " + d.strftime("%A %d %B %Y"), cur,
                              footer="what happened, what you learned, what future you should know")
        if text is None:
            return
        text = text.rstrip()
        with self.edit():
            if text.strip():
                self.store.journal[iso] = text
            else:
                self.store.journal.pop(iso, None)
        self.hook("on_journal", {"title": iso, "id": 0})
        self.say("journal saved (%d words)" % word_count(text), "ok")

    def journal_add_line(self, d):
        line = self.prompt("quick journal line for " + d.isoformat())
        if not line or not line.strip():
            return
        iso = d.isoformat()
        cur = self.store.journal.get(iso, "").rstrip()
        if not cur:
            cur = "# %s, %s\n" % (d.strftime("%A"), iso)
        entry = "- [%s] %s" % (dt.datetime.now().strftime("%H:%M"), line.strip())
        with self.edit():
            self.store.journal[iso] = cur + "\n" + entry
        self.hook("on_journal", {"title": iso, "id": 0})
        self.say("added to journal", "ok")

    def act_journal(self, date=None):
        J = {"d": date or today(), "top": 0, "max": 0}

        def body(d, w):
            iso = d.isoformat()
            text = self.store.journal.get(iso, "")
            out = []
            if text.strip():
                for raw in text.split("\n"):
                    role, bold = "fg", False
                    if raw.startswith("#"):
                        role, bold = "accent", True
                    elif re.match(r"^\s*-\s+\[\d", raw):
                        role = "fg"
                    for ln in wrap(render_refs(self.store, raw, self.sym["link"]), w) or [""]:
                        out.append((ln, role, bold))
            else:
                out.append(("no entry for this day. press e to write one, n for a quick line.", "dim", False))
            out.append(("", "fg", False))
            out.append(("that day", "accent2", True))
            done = done_on(self.store, iso)
            tt = time_on(self.store, iso)
            out.append(("done %d   tracked %s" % (len(done), fmt_duration(tt) if tt else "0m"), "dim", False))
            for t_ in done[:12]:
                out.append(("  " + self.sym["bullet"] + " " + t_, "fg", False))
            if len(done) > 12:
                out.append(("  ... %d more" % (len(done) - 12), "dim", False))
            hs = [h for h in self.store.habits if not h.get("archived") and habit_scheduled(h, d)]
            if hs:
                met = sum(1 for h in hs if habit_day_met(h, d))
                out.append(("habits %d/%d" % (met, len(hs)), "accent2", True))
                for h in hs:
                    ok = habit_day_met(h, d)
                    out.append(("  %s %s" % (self.sym["check_on"] if ok else self.sym["check_off"], h["name"]),
                                "ok" if ok else "dim", False))
            return out

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            if H < 10 or W < 44:
                self.put(0, 0, "terminal too small (q closes)", self.attr("err"))
                return
            td = today()
            d = J["d"]
            days = self.journal_days()
            cur, best = streak_info(days, td)
            self.screen_bar(W, "journal", "%d entries   streak %d (best %d)" % (len(days), cur, best))
            lw = 26 if W >= 84 else 0
            vis = H - 3
            if lw:
                allv = sorted(set(days) | {td.isoformat(), d.isoformat()}, reverse=True)
                idx = allv.index(d.isoformat())
                first = max(0, min(idx - vis // 2, len(allv) - vis))
                for r in range(vis):
                    i = first + r
                    if i >= len(allv):
                        break
                    iso = allv[i]
                    on = iso == d.isoformat()
                    bg = "sel_bg" if on else "bg"
                    if on:
                        self.fill(1 + r, 0, lw, self.attr("fg", bg))
                    wc = word_count(self.store.journal.get(iso, ""))
                    dd = dt.date.fromisoformat(iso)
                    label = ("today " if iso == td.isoformat() else dd.strftime("%a ")) + dd.strftime("%d %b")
                    self.put(1 + r, 1, self.sym["cursor"] if on else " ", self.attr("accent", bg, bold=True))
                    self.put(1 + r, 3, label, self.attr("accent" if on else "fg", bg, bold=on))
                    self.put(1 + r, lw - 7, ("%dw" % wc).rjust(6) if wc else "", self.attr("dim", bg))
                for r in range(vis):
                    self.put(1 + r, lw, self.sym["vline"], self.attr("border"))
            x0 = lw + 2 if lw else 2
            w = W - x0 - 2
            head = d.strftime("%A, %d %B %Y")
            self.put(1, x0, head, self.attr("accent", bold=True), w)
            lines = body(d, w)
            rows = H - 4
            J["max"] = max(0, len(lines) - rows)
            J["top"] = max(0, min(J["top"], J["max"]))
            for r in range(rows):
                i = J["top"] + r
                if i < len(lines):
                    text, role, bold = lines[i]
                    self.put(2 + r, x0, text, self.attr(role, bold=bold), w)
            if J["max"]:
                self.put(1, W - 12, "%d%%" % (100 * J["top"] // J["max"]), self.attr("dim"))
            self.screen_foot(H, W, "h l day  H L entry  t today  e write  n quick line  g date  / search  d delete  j k scroll  q close")

        def handle(name, ch):
            d = J["d"]
            td = today()
            if name in ("q", "esc", "ctrl-c"):
                return True
            if name in ("h", "left"):
                J["d"], J["top"] = d - dt.timedelta(days=1), 0
            elif name in ("l", "right"):
                if d < td:
                    J["d"], J["top"] = d + dt.timedelta(days=1), 0
            elif name == "H":
                prev = [x for x in self.journal_days() if x < d.isoformat()]
                if prev:
                    J["d"], J["top"] = dt.date.fromisoformat(prev[-1]), 0
            elif name == "L":
                nxt = [x for x in self.journal_days() if x > d.isoformat()]
                if nxt:
                    J["d"], J["top"] = dt.date.fromisoformat(nxt[0]), 0
            elif name == "t":
                J["d"], J["top"] = td, 0
            elif name in ("e", "enter"):
                self.journal_edit(d)
            elif name == "n":
                self.journal_add_line(d)
            elif name == "g":
                text = self.prompt("go to date  (fri, -3d is not needed, 12-25, 2026-12-25)")
                if text:
                    try:
                        nd = parse_date(text.strip(), td)
                        if nd:
                            J["d"], J["top"] = min(nd, td), 0
                    except ValueError:
                        self.say("could not read that date", "err")
            elif name == "/":
                q = self.prompt("search journal")
                if q and q.strip():
                    hits = []
                    for iso in reversed(self.journal_days()):
                        for ln in self.store.journal[iso].split("\n"):
                            if q.lower() in ln.lower():
                                hits.append((iso, ln.strip()))
                    if not hits:
                        self.say("no journal matches", "err")
                    else:
                        labels = ["%s  %s" % (a, clip(b, 50)) for a, b in hits[:40]]
                        i = self.menu("%d matches" % len(hits), labels)
                        if i is not None:
                            J["d"], J["top"] = dt.date.fromisoformat(hits[i][0]), 0
            elif name == "d":
                iso = d.isoformat()
                if iso in self.store.journal and self.confirm("delete the entry for %s?" % iso):
                    with self.edit():
                        self.store.journal.pop(iso, None)
                    self.say("entry deleted")
            elif name in ("j", "down"):
                J["top"] += 1
            elif name in ("k", "up"):
                J["top"] -= 1
            elif name in ("pgdn", "ctrl-d", "space"):
                J["top"] += 10
            elif name in ("pgup", "ctrl-u"):
                J["top"] -= 10
            elif self.keymap.get(name) == "journal":
                return True
            return False

        self.screen_loop(render, handle)

    # ----- habits -----

    def habit_symbols(self):
        if self.opts["ascii"]:
            return {"met": "#", "part": "+", "miss": ".", "none": " ", "pend": "o"}
        return {"met": "■", "part": "▪", "miss": "·", "none": " ", "pend": "□"}

    def habit_toggle(self, h, d):
        iso = d.isoformat()
        need = 1 if h["kind"] == "weekly" else h["target"]
        cur = habit_count(h, d)
        if cur >= need:
            h["log"].pop(iso, None)
        else:
            h["log"][iso] = cur + 1

    def act_habits(self):
        Hs = {"i": 0, "off": 0, "arch": False}
        sy = self.habit_symbols()

        def visible():
            return [h for h in self.store.habits if bool(h.get("archived")) == Hs["arch"]]

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            if H < 10 or W < 48:
                self.put(0, 0, "terminal too small (q closes)", self.attr("err"))
                return
            td = today()
            hs = visible()
            Hs["i"] = max(0, min(Hs["i"], len(hs) - 1))
            done, total = habit_summary(self.store, td)
            self.screen_bar(W, "habits" + (" (archived)" if Hs["arch"] else ""),
                            "today %d/%d" % (done, total) if total else "")
            nw = min(24, max(12, W // 4))
            ncols = max(7, min(21, (W - nw - 34) // 2))
            gx = 2 + nw + 10
            if not hs:
                msg = "no habits yet. press a to add one  (read 3/week, run mon,wed,fri, water x8, stretch daily)"
                self.put(H // 2, max(2, (W - cell_len(msg)) // 2), msg, self.attr("dim"))
            days = [td - dt.timedelta(days=ncols - 1 - k) for k in range(ncols)]
            self.put(1, 2 + nw + 1, "schedule", self.attr("dim"))
            for k, dd in enumerate(days):
                on = (td - dd).days == Hs["off"]
                self.put(1, gx + k * 2, dd.strftime("%a")[0], self.attr("accent" if on else "dim", bold=on))
            self.put(1, gx + ncols * 2 + 1, "streak best  30d", self.attr("dim"))
            rows_vis = max(1, min(len(hs), H - 14 if H >= 24 else H - 4))
            first = max(0, min(Hs["i"] - rows_vis // 2, len(hs) - rows_vis))
            for r in range(rows_vis):
                i = first + r
                if i >= len(hs):
                    break
                h = hs[i]
                y = 2 + r
                on = i == Hs["i"]
                bg = "sel_bg" if on else "bg"
                if on:
                    self.fill(y, 0, W, self.attr("fg", bg))
                self.put(y, 0, self.sym["cursor"] if on else " ", self.attr("accent", bg, bold=True))
                sched, ok = habit_today(h, td)
                self.put(y, 2, pad(clip(h["name"], nw), nw), self.attr("ok" if ok else "fg", bg, bold=on))
                self.put(y, 2 + nw + 1, pad(habit_schedule_label(h), 8), self.attr("dim", bg))
                for k, dd in enumerate(days):
                    c = habit_count(h, dd)
                    if habit_day_met(h, dd):
                        g, role = sy["met"], "ok"
                    elif c > 0:
                        g, role = sy["part"], "today"
                    elif h["kind"] == "weekly" or habit_scheduled(h, dd):
                        if dd < td:
                            g, role = sy["miss"], "dim"
                        else:
                            g, role = sy["pend"], "today"
                    else:
                        g, role = sy["none"], "dim"
                    cur_col = on and (td - dd).days == Hs["off"]
                    self.put(y, gx + k * 2, g, self.attr(role, bg, bold=cur_col, reverse=cur_col))
                cur_s, best_s = habit_streak(h, td)
                unit = "w" if h["kind"] == "weekly" else "d"
                rate = habit_rate(h, td)
                info = "%3d%s %3d%s  %4s" % (cur_s, unit, best_s, unit, ("%d%%" % round(rate * 100)) if rate is not None else "-")
                self.put(y, gx + ncols * 2 + 1, info, self.attr("accent2" if cur_s else "dim", bg))
                if h["kind"] == "weekly":
                    self.put(y, gx + ncols * 2 + 20, "%d/%d wk" % (habit_week_total(h, td), h["target"]), self.attr("dim", bg))
            if hs and H >= 24:
                h = hs[Hs["i"]]
                y0 = 2 + rows_vis + 1
                self.put(y0, 2, h["name"], self.attr("accent", bold=True))
                cur_s, best_s = habit_streak(h, td)
                total_days = sum(1 for v in h["log"].values() if v > 0)
                self.put(y0 + 1, 2, "current %d  best %d  logged on %d days  since %s" % (
                    cur_s, best_s, total_days, habit_first_day(h).isoformat()), self.attr("dim"))
                if h.get("note"):
                    self.put(y0 + 2, 2, clip(h["note"], W - 6), self.attr("fg"))
                weeks = max(4, min(26, (W - 12) // 2))
                start = week_start(td) - dt.timedelta(weeks=weeks - 1)
                for row, nm in ((0, "Mon"), (2, "Wed"), (4, "Fri"), (6, "Sun")):
                    self.put(y0 + 4 + row, 2, nm, self.attr("dim"))
                for col in range(weeks):
                    first_d = start + dt.timedelta(weeks=col)
                    for row in range(7):
                        dd = first_d + dt.timedelta(days=row)
                        if dd > td or y0 + 4 + row >= H - 1:
                            continue
                        c = habit_count(h, dd)
                        if habit_day_met(h, dd):
                            g, role = sy["met"], "ok"
                        elif c > 0:
                            g, role = sy["part"], "today"
                        else:
                            g, role = sy["miss"], "border"
                        self.put(y0 + 4 + row, 7 + col * 2, g, self.attr(role))
            self.screen_foot(H, W, "j k habit  h l day  space toggle  a add  e edit  n note  d delete  z archive  Z archived  q close")

        def handle(name, ch):
            hs = visible()
            td = today()
            if name in ("q", "esc", "ctrl-c") or self.keymap.get(name) == "habits":
                return True
            if name in ("j", "down"):
                Hs["i"] = min(len(hs) - 1, Hs["i"] + 1)
            elif name in ("k", "up"):
                Hs["i"] = max(0, Hs["i"] - 1)
            elif name in ("h", "left"):
                Hs["off"] = min(60, Hs["off"] + 1)
            elif name in ("l", "right"):
                Hs["off"] = max(0, Hs["off"] - 1)
            elif name == "t":
                Hs["off"] = 0
            elif name in ("space", "x", "enter") and hs:
                h = hs[Hs["i"]]
                with self.edit():
                    self.habit_toggle(h, td - dt.timedelta(days=Hs["off"]))
                cur_s, _ = habit_streak(h, td)
                if habit_day_met(h, td - dt.timedelta(days=Hs["off"])):
                    self.hook("on_habit", {"title": h["name"], "id": h["id"]})
                    self.say("%s: streak %d" % (clip(h["name"], 30), cur_s), "ok")
            elif name == "a":
                text = self.prompt("new habit  (name daily | 3/week | mon,wed,fri | weekdays | x8)")
                if text and text.strip():
                    p = parse_habit(text)
                    if not p["name"]:
                        self.say("name is empty", "err")
                    else:
                        with self.edit():
                            nid = max([x["id"] for x in self.store.habits] + [0]) + 1
                            h = blank_habit(nid, p["name"])
                            h.update(kind=p["kind"], target=p["target"], days=p["days"])
                            self.store.habits.append(h)
                        Hs["arch"] = False
                        Hs["i"] = len(visible()) - 1
                        self.say("habit added", "ok")
            elif name == "e" and hs:
                h = hs[Hs["i"]]
                text = self.prompt("edit habit", serialize_habit(h))
                if text and text.strip():
                    p = parse_habit(text)
                    if p["name"]:
                        with self.edit():
                            h.update(name=p["name"], kind=p["kind"], target=p["target"], days=p["days"])
            elif name == "n" and hs:
                h = hs[Hs["i"]]
                text = self.prompt("note for " + h["name"], h.get("note", ""))
                if text is not None:
                    with self.edit():
                        h["note"] = text.strip()
            elif name == "d" and hs:
                h = hs[Hs["i"]]
                if self.confirm("delete habit %s and its history?" % clip(h["name"], 30)):
                    with self.edit():
                        self.store.habits.remove(h)
                    self.say("habit deleted")
            elif name == "z" and hs:
                h = hs[Hs["i"]]
                with self.edit():
                    h["archived"] = not h.get("archived")
                self.say("archived" if h["archived"] else "restored")
            elif name == "Z":
                Hs["arch"] = not Hs["arch"]
                Hs["i"] = 0
            return False

        self.screen_loop(render, handle)

    # ----- projects and goals -----

    PROJECT_STATUS = ["active", "paused"]

    def goal_form(self, g=None):
        name = self.prompt("goal name", g["name"] if g else "")
        if not name or not name.strip():
            return None
        new = g is None
        out = dict(g) if g else {"id": 0, "kind": "count", "target": 10, "query": "", "due": "", "milestones": [],
                                  "start": today().isoformat()}
        out["name"] = name.strip()
        if new:
            kinds = [("count", "count: finish N tasks (optionally matching a filter)"),
                     ("time", "time: track N hours (optionally on matching tasks)"),
                     ("tasks", "tasks: finish everything that matches a filter"),
                     ("manual", "manual: a checklist of milestones")]
            i = self.menu("goal type", [k[1] for k in kinds])
            if i is None:
                return None
            out["kind"] = kinds[i][0]
        kind = out["kind"]
        if kind in ("count", "time"):
            t = self.prompt("target (%s)" % ("tasks" if kind == "count" else "hours"), str(out["target"]))
            try:
                out["target"] = float(t) if kind == "time" else int(float(t))
                if out["target"] <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                self.say("target must be a positive number", "err")
                return None
        if kind in ("count", "time", "tasks"):
            q = self.prompt("filter  (#tag @project !2+ ...; empty means everything)", out["query"])
            if q is None:
                return None
            out["query"] = q.strip()
        if kind == "manual" and new:
            m = self.prompt("milestones, separated by ;")
            if m is None:
                return None
            out["milestones"] = [{"t": x.strip(), "done": False} for x in m.split(";") if x.strip()]
        d = self.prompt("due date (optional: fri, +3w, eom, 2026-12-31)", out.get("due", ""))
        if d is None:
            return None
        if d.strip():
            try:
                pd = parse_date(d.strip(), today())
                out["due"] = pd.isoformat() if pd else ""
            except ValueError:
                self.say("could not read that date", "err")
                return None
        else:
            out["due"] = ""
        return out

    def milestone_menu(self, g):
        while True:
            ms = g["milestones"]
            labels = ["[%s] %s" % ("x" if m["done"] else " ", m["t"]) for m in ms]
            labels += ["+ add milestone", "- remove a milestone"]
            i = self.menu("milestones: " + clip(g["name"], 30), labels)
            if i is None:
                return
            if i < len(ms):
                with self.edit():
                    ms[i]["done"] = not ms[i]["done"]
            elif i == len(ms):
                t = self.prompt("new milestone")
                if t and t.strip():
                    with self.edit():
                        ms.append({"t": t.strip(), "done": False})
            elif ms:
                j = self.menu("remove which?", [m["t"] for m in ms])
                if j is not None:
                    with self.edit():
                        del ms[j]

    def act_projects(self, tab=0):
        P = {"tab": tab, "i": 0}
        health_role = {"on track": "ok", "done": "ok", "at risk": "today", "overdue": "overdue",
                       "stale": "dim", "paused": "dim"}

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            if H < 12 or W < 52:
                self.put(0, 0, "terminal too small (q closes)", self.attr("err"))
                return
            td = today()
            x = self.screen_bar(W, "")
            x += 1
            for i, nm in enumerate(["projects", "goals"]):
                on = i == P["tab"]
                x = self.put(0, x, " %d %s " % (i + 1, nm), self.attr("accent" if on else "dim", "sel_bg" if on else "bar_bg", bold=on)) + 1
            if P["tab"] == 0:
                self.draw_projects_tab(H, W, td, P, health_role)
            else:
                self.draw_goals_tab(H, W, td, P, health_role)

        def handle(name, ch):
            td = today()
            if name in ("q", "esc", "ctrl-c") or self.keymap.get(name) == "projects":
                return True
            if name in ("tab", "1", "2"):
                P["tab"] = (P["tab"] + 1) % 2 if name == "tab" else int(name) - 1
                P["i"] = 0
                return False
            if P["tab"] == 0:
                names = project_names(self.store)
                P["i"] = max(0, min(P["i"], len(names) - 1))
                if name in ("j", "down"):
                    P["i"] = min(len(names) - 1, P["i"] + 1)
                elif name in ("k", "up"):
                    P["i"] = max(0, P["i"] - 1)
                elif name == "enter" and names:
                    self.query = ""
                    self.set_view("p:" + names[P["i"]])
                    self.focus = "list"
                    return True
                elif name == "a":
                    n = self.prompt("new project name")
                    if n and n.strip():
                        n = n.strip().replace(" ", "-")
                        with self.edit():
                            self.store.projects.setdefault(n, {})
                        self.say("project added: " + n, "ok")
                elif name == "e" and names:
                    nm = names[P["i"]]
                    meta = self.store.projects.get(nm, {})
                    init = "status:%s due:%s %s" % (meta.get("status", "active"), meta.get("due", "") or "none", meta.get("desc", ""))
                    text = self.prompt("%s: status:active|paused due:DATE then a description" % nm, init)
                    if text is not None:
                        m = {"status": "active", "due": "", "desc": []}
                        for tok in text.split():
                            if tok.startswith("status:") and tok[7:] in self.PROJECT_STATUS:
                                m["status"] = tok[7:]
                            elif tok.startswith("due:"):
                                try:
                                    pd = parse_date(tok[4:], td)
                                    m["due"] = pd.isoformat() if pd else ""
                                except ValueError:
                                    pass
                            else:
                                m["desc"].append(tok)
                        with self.edit():
                            self.store.projects[nm] = {"status": m["status"], "due": m["due"], "desc": " ".join(m["desc"])}
                elif name == "s" and names:
                    nm = names[P["i"]]
                    with self.edit():
                        meta = self.store.projects.setdefault(nm, {})
                        meta["status"] = "paused" if meta.get("status", "active") == "active" else "active"
                    self.say("%s is now %s" % (nm, meta["status"]))
                elif name == "d" and names:
                    nm = names[P["i"]]
                    if nm in self.store.projects and not any(t["project"] == nm for t in self.store.tasks):
                        with self.edit():
                            del self.store.projects[nm]
                    else:
                        self.say("only empty projects can be removed here", "err")
            else:
                gs = self.store.goals
                P["i"] = max(0, min(P["i"], len(gs) - 1))
                if name in ("j", "down"):
                    P["i"] = min(len(gs) - 1, P["i"] + 1)
                elif name in ("k", "up"):
                    P["i"] = max(0, P["i"] - 1)
                elif name == "a":
                    g = self.goal_form()
                    if g:
                        with self.edit():
                            g["id"] = max([x["id"] for x in gs] + [0]) + 1
                            gs.append(g)
                        P["i"] = len(gs) - 1
                        self.say("goal added", "ok")
                elif name == "e" and gs:
                    g = self.goal_form(gs[P["i"]])
                    if g:
                        with self.edit():
                            gs[P["i"]] = g
                elif name in ("m", "enter", "space") and gs:
                    g = gs[P["i"]]
                    if g["kind"] == "manual":
                        self.milestone_menu(g)
                    elif name == "enter":
                        self.query = g.get("query", "")
                        self.set_view("all")
                        return True
                elif name == "d" and gs:
                    if self.confirm("delete goal %s?" % clip(gs[P["i"]]["name"], 30)):
                        with self.edit():
                            del gs[P["i"]]
            return False

        self.screen_loop(render, handle)

    def draw_projects_tab(self, H, W, td, P, health_role):
        names = project_names(self.store)
        P["i"] = max(0, min(P["i"], len(names) - 1))
        if not names:
            msg = "no projects yet. give a task @project, or press a here"
            self.put(H // 2, max(2, (W - cell_len(msg)) // 2), msg, self.attr("dim"))
        nw = min(24, max(10, W // 4))
        bw = max(6, min(14, W - nw - 50))
        self.put(1, 2, "project", self.attr("dim"))
        self.put(1, 4 + nw + bw, "done   health      due      eta", self.attr("dim"))
        detail = H >= 20
        rows_vis = max(1, min(len(names), H - 12 if detail else H - 3))
        first = max(0, min(P["i"] - rows_vis // 2, len(names) - rows_vis))
        stats = {}
        for r in range(rows_vis):
            i = first + r
            if i >= len(names):
                break
            st = project_stats(self.store, names[i], td)
            stats[i] = st
            y = 2 + r
            on = i == P["i"]
            bg = "sel_bg" if on else "bg"
            if on:
                self.fill(y, 0, W, self.attr("fg", bg))
            self.put(y, 0, self.sym["cursor"] if on else " ", self.attr("accent", bg, bold=True))
            self.put(y, 2, pad(clip("@" + st["name"], nw), nw), self.attr("project", bg, bold=on))
            self.put(y, 3 + nw, self.progress_bar(st["frac"], bw), self.attr("ok" if st["frac"] >= 1 else "accent2", bg))
            self.put(y, 4 + nw + bw, pad("%d/%d" % (st["done"], st["total"]), 7), self.attr("fg", bg))
            self.put(y, 11 + nw + bw, pad(st["health"], 11), self.attr(health_role.get(st["health"], "fg"), bg, bold=True))
            self.put(y, 22 + nw + bw, pad(st["due"][5:] if st["due"] else "-", 9), self.attr("dim", bg))
            self.put(y, 31 + nw + bw, st["eta"].strftime("%m-%d") if st["eta"] else "-", self.attr("dim", bg))
        if names and detail:
            st = project_stats(self.store, names[P["i"]], td)
            y0 = 2 + rows_vis + 1
            self.put(y0, 2, "@" + st["name"], self.attr("project", bold=True))
            if st["desc"]:
                self.put(y0 + 1, 2, clip(st["desc"], W - 6), self.attr("fg"))
            vel = "%.1f tasks/week" % (st["velocity"] * 7) if st["velocity"] else "no recent completions"
            items = [("open", "%d" % st["open"]), ("overdue", "%d" % st["overdue"]), ("blocked", "%d" % st["blocked"]),
                     ("snoozed", "%d" % st["snoozed"]), ("tracked", fmt_duration(st["tracked"]) if st["tracked"] else "0m"),
                     ("est left", fmt_duration(st["est_left"]) if st["est_left"] else "0m"), ("pace", vel),
                     ("status", st["status"]), ("last", st["last"] or "-"),
                     ("eta", st["eta"].isoformat() if st["eta"] else "-"), ("due", st["due"] or "-")]
            colw = max(22, (W - 4) // 3)
            for k, (a, b) in enumerate(items):
                cx = 2 + (k % 3) * colw
                cy = y0 + 2 + k // 3
                if cy < H - 1:
                    self.put(cy, cx, "%-9s %s" % (a, b), self.attr("fg" if a not in ("overdue", "blocked") or b == "0" else "p3"), colw - 1)
        self.screen_foot(H, W, "j k move  enter open in list  a add  e edit  s pause  d remove empty  tab goals  q close")

    def draw_goals_tab(self, H, W, td, P, health_role):
        gs = self.store.goals
        P["i"] = max(0, min(P["i"], len(gs) - 1))
        if not gs:
            msg = "no goals yet. press a: count tasks, track hours, or a milestone checklist"
            self.put(H // 2, max(2, (W - cell_len(msg)) // 2), msg, self.attr("dim"))
        nw = min(26, max(10, W // 4))
        bw = max(6, min(16, W - nw - 52))
        rows_vis = max(1, min(len(gs), H - 12 if H >= 20 else H - 3))
        first = max(0, min(P["i"] - rows_vis // 2, len(gs) - rows_vis))
        for r in range(rows_vis):
            i = first + r
            if i >= len(gs):
                break
            g = gs[i]
            pr = goal_progress(self.store, g, td)
            status, _ = goal_pace(g, pr["frac"], td)
            y = 2 + r
            on = i == P["i"]
            bg = "sel_bg" if on else "bg"
            if on:
                self.fill(y, 0, W, self.attr("fg", bg))
            self.put(y, 0, self.sym["cursor"] if on else " ", self.attr("accent", bg, bold=True))
            self.put(y, 2, pad(clip(g["name"], nw), nw), self.attr("fg", bg, bold=on))
            self.put(y, 3 + nw, self.progress_bar(pr["frac"], bw), self.attr("ok" if pr["frac"] >= 1 else "accent2", bg))
            self.put(y, 4 + nw + bw, pad("%d%%" % round(pr["frac"] * 100), 5), self.attr("fg", bg))
            self.put(y, 9 + nw + bw, pad(pr["label"], 18), self.attr("dim", bg))
            role = {"done": "ok", "ahead": "ok", "on pace": "accent2", "behind": "today", "overdue": "overdue"}.get(status, "dim")
            self.put(y, 27 + nw + bw, pad(status, 9), self.attr(role, bg, bold=True))
            self.put(y, 36 + nw + bw, g["due"][5:] if g.get("due") else "", self.attr("dim", bg))
        if gs and H >= 20:
            g = gs[P["i"]]
            pr = goal_progress(self.store, g, td)
            y0 = 2 + rows_vis + 1
            self.put(y0, 2, g["name"], self.attr("accent", bold=True))
            info = "%s goal" % g["kind"]
            if g.get("query"):
                info += "   filter: " + g["query"]
            if g.get("start"):
                info += "   from " + g["start"]
            if g.get("due"):
                info += "   due " + g["due"]
            self.put(y0 + 1, 2, clip(info, W - 4), self.attr("dim"))
            if g["kind"] == "manual":
                for k, m in enumerate(g["milestones"][:H - y0 - 4]):
                    self.put(y0 + 3 + k, 4, "%s %s" % (self.sym["check_on"] if m["done"] else self.sym["check_off"], m["t"]),
                             self.attr("done" if m["done"] else "fg"), W - 8)
            else:
                series = goal_series(self.store, g, td)
                if series:
                    width = min(len(series), W - 8)
                    pts = series[-width:]
                    mx = max(max(pts), float(g.get("target") or 1) if g["kind"] != "tasks" else 1.0, 1e-9)
                    line = "".join(BLOCKS[min(8, int(round(v / mx * 8)))] if not self.opts["ascii"] else
                                   ".:-=+*#%@"[min(8, int(round(v / mx * 8)))] for v in pts)
                    self.put(y0 + 3, 4, line, self.attr("accent2"), W - 6)
                    self.put(y0 + 4, 4, "cumulative progress per day, target line is the top", self.attr("dim"), W - 6)
        self.screen_foot(H, W, "j k move  a add  e edit  m milestones  enter open filter  d delete  tab projects  q close")

    # ----- estimate accuracy page -----

    def draw_estimates(self, H, W, days, grow):
        samples = est_samples(self.store)
        cal = calibration(samples)
        if not samples:
            self.put(3, 2, "no data yet. give tasks est:30m, track time with w or focus mode, then finish them.", self.attr("dim"))
            return
        bias = "over" if cal["median"] > 1.05 else "under" if cal["median"] < 0.95 else "close"
        word = {"over": "tasks usually take longer than planned", "under": "tasks usually finish faster than planned",
                "close": "your estimates are well calibrated"}[bias]
        self.tiles(2, [
            (str(cal["n"]), "finished with est and time", "accent2"),
            ("x%.2f" % cal["median"], "median actual / estimate", "today" if bias == "over" else "ok"),
            ("x%.2f" % cal["mean"], "mean", "fg"),
            ("%d%%" % round(cal["within"] * 100), "within 25 percent", "ok"),
        ])
        self.put(5, 2, word + (".  multiply your gut feeling by %.2f." % cal["median"] if bias != "close" else "."),
                 self.attr("accent", bold=True), W - 4)
        rows_top = 7
        by = collections.defaultdict(list)
        for sm in samples[-60:]:
            by[sm["project"] or "(none)"].append(sm["act"] / float(sm["est"]))
        proj = sorted(((k, sum(v) / len(v), len(v)) for k, v in by.items()), key=lambda r: -r[2])[:6]
        self.put(rows_top, 2, "by project (mean actual / estimate)", self.attr("accent", bold=True))
        self.hbars(rows_top + 1, 2, min(W - 6, 60), [(k, m, "x%.2f  n=%d" % (m, n)) for k, m, n in proj], "accent2", grow)
        y = rows_top + 2 + len(proj)
        self.put(y, 2, "recent tasks  (estimate vs actual)", self.attr("accent", bold=True))
        room = H - y - 3
        for k, sm in enumerate(reversed(samples[-max(0, room):])):
            if k >= room:
                break
            ratio = sm["act"] / float(sm["est"])
            role = "ok" if 0.75 <= ratio <= 1.25 else ("p3" if ratio > 1.25 else "accent2")
            bw = max(4, min(20, W - 70))
            n = int(min(2.0, ratio) / 2.0 * bw * grow)
            bar = ("#" if self.opts["ascii"] else "█") * n
            self.put(y + 1 + k, 2, pad(clip(sm["title"], max(10, W - bw - 36)), max(10, W - bw - 36)), self.attr("fg"))
            cx = 2 + max(10, W - bw - 36) + 1
            self.put(y + 1 + k, cx, pad("%s / %s" % (fmt_duration(sm["est"]), fmt_duration(sm["act"])), 16), self.attr("dim"))
            self.put(y + 1 + k, cx + 17, pad(bar, bw), self.attr(role))
            self.put(y + 1 + k, cx + 18 + bw, "x%.2f" % ratio, self.attr(role, bold=True))

    def est_hint(self, secs):
        cal = calibration(est_samples(self.store))
        if cal["n"] >= 5 and abs(cal["median"] - 1.0) >= 0.1 and secs:
            return "likely ~%s (x%.2f)" % (fmt_duration(int(secs * cal["median"])), cal["median"])
        return ""


    # ----- settings: storage and live editing -----

    def save_user_settings(self):
        ok = save_settings_file(self.settings_path, self.user_settings)
        for k in self.user_settings:
            self.state.pop(k, None)
        save_state(self.state)
        return ok

    def sv_get(self, it):
        if it.get("get"):
            return it["get"]()
        return self.opts.get(it["key"])

    def sv_set(self, it, val):
        if it.get("set"):
            it["set"](val)
        else:
            self.user_settings[it["key"]] = copy.deepcopy(val)
        self.apply_config()

    def sv_changed(self, it):
        if it.get("changed"):
            return it["changed"]()
        return it.get("key") in self.user_settings

    def sv_reset(self, it):
        if it.get("reset"):
            it["reset"]()
        elif it.get("key"):
            self.user_settings.pop(it["key"], None)
            self.state.pop(it["key"], None)
        self.apply_config()

    def sv_choices(self, it):
        c = it.get("choices", [])
        return list(c(self) if callable(c) else c)

    # custom theme colors
    def sv_color_theme(self, create):
        themes = copy.deepcopy(self.opts.get("themes", {}))
        cur = self.opts["theme"]
        if cur not in themes:
            if not create:
                return themes, cur
            base = cur if cur in THEMES else "tokyonight"
            name = base + "-custom"
            themes[name] = {"inherit": base}
            cur = name
        return themes, cur

    def sv_set_color(self, role, val):
        themes, cur = self.sv_color_theme(True)
        themes[cur][role] = val
        self.user_settings["themes"] = themes
        self.user_settings["theme"] = cur

    def sv_reset_color(self, role):
        themes, cur = self.sv_color_theme(False)
        if cur in themes and role in themes[cur]:
            del themes[cur][role]
            self.user_settings["themes"] = themes

    def sv_color_changed(self, role):
        return role in self.user_settings.get("themes", {}).get(self.opts["theme"], {})

    # key bindings
    def sv_keys_of(self, action):
        k = self.opts.get("keys", {}).get(action)
        if isinstance(k, str):
            k = [k]
        return list(k if isinstance(k, list) else DEFAULT_KEYS.get(action, []))

    def sv_set_keys(self, action, keys):
        table = copy.deepcopy(self.opts.get("keys", {}))
        for other in list(DEFAULT_KEYS):
            if other != action:
                cur = self.sv_keys_of(other)
                clash = [k for k in cur if k in keys]
                if clash:
                    table[other] = [k for k in cur if k not in keys]
        table[action] = keys
        self.user_settings["keys"] = table

    def sv_reset_keys(self, action):
        table = copy.deepcopy(self.opts.get("keys", {}))
        table.pop(action, None)
        self.user_settings["keys"] = table

    def sv_symbol_set(self, name, val):
        table = dict(self.opts.get("symbols", {}))
        table[name] = val
        self.user_settings["symbols"] = table

    def sv_symbol_reset(self, name):
        table = dict(self.opts.get("symbols", {}))
        table.pop(name, None)
        self.user_settings["symbols"] = table

    def sv_dynamic(self, kind):
        out = []
        if kind == "colors":
            for role in THEME_ROLES:
                out.append({"key": None, "label": role.replace("_", " ").title(), "kind": "color", "desc": ROLE_DOC.get(role, ""),
                            "get": lambda role=role: self.theme.get(role, ""),
                            "set": lambda v, role=role: self.sv_set_color(role, v),
                            "reset": lambda role=role: self.sv_reset_color(role),
                            "changed": lambda role=role: self.sv_color_changed(role)})
        elif kind == "symbols":
            base = ASCII_SYMBOLS if self.opts["ascii"] else UNICODE_SYMBOLS
            for name in UNICODE_SYMBOLS:
                out.append({"key": None, "label": name.replace("_", " ").title(), "kind": "text",
                            "desc": "Glyph for %s. Default: %s" % (name.replace("_", " "), base[name]),
                            "get": lambda name=name: self.sym.get(name, ""),
                            "set": lambda v, name=name: self.sv_symbol_set(name, v),
                            "reset": lambda name=name: self.sv_symbol_reset(name),
                            "changed": lambda name=name: name in self.user_settings.get("symbols", {})})
        elif kind == "keys":
            order = []
            for a in ACTION_DOC:
                if a in DEFAULT_KEYS and a not in order:
                    order.append(a)
            for a in order:
                out.append({"key": None, "label": a.replace("_", " ").title(), "kind": "keys", "desc": ACTION_DOC.get(a, ""),
                            "get": lambda a=a: ", ".join(self.sv_keys_of(a)) or "none",
                            "set": lambda v, a=a: self.sv_set_keys(a, v),
                            "reset": lambda a=a: self.sv_reset_keys(a),
                            "changed": lambda a=a: a in self.user_settings.get("keys", {}),
                            "default": ", ".join(DEFAULT_KEYS.get(a, []))})
        return out

    # ----- settings: sub editors -----

    def order_editor(self, title, available, current, required=()):
        items = [c for c in current if c in available] + [a for a in available if a not in current]
        on = {c for c in current if c in available} | set(required)
        idx = 0
        while True:
            self.backdrop()
            H, W = self.scr.getmaxyx()
            w = min(W - 4, 54)
            h = min(H - 2, len(items) + 6)
            x, y = (W - w) // 2, max(1, (H - h) // 2)
            self.box(y, x, h, w, title)
            vis = h - 5
            first = max(0, min(idx - vis // 2, len(items) - vis))
            for r in range(vis):
                i = first + r
                if i >= len(items):
                    break
                sel = i == idx
                a = self.attr("accent", "sel_bg", bold=True) if sel else self.attr("fg")
                if sel:
                    self.fill(y + 2 + r, x + 1, w - 2, a)
                lock = " (required)" if items[i] in required else ""
                self.put(y + 2 + r, x + 3, "[%s] %s%s" % ("v" if items[i] in on else " ", items[i], lock), a, w - 6)
            self.put(y + h - 2, x + 2, "space toggle  J K move  enter accept  esc cancel", self.attr("dim"), w - 4)
            self.scr.refresh()
            name, ch = self.read_key()
            if name in ("down", "j", "ctrl-n"):
                idx = (idx + 1) % len(items)
            elif name in ("up", "k", "ctrl-p"):
                idx = (idx - 1) % len(items)
            elif name in ("space", "x"):
                if items[idx] not in required:
                    on.symmetric_difference_update({items[idx]})
            elif name in ("J", "alt-j") and idx + 1 < len(items):
                items[idx], items[idx + 1] = items[idx + 1], items[idx]
                idx += 1
            elif name in ("K", "alt-k") and idx > 0:
                items[idx], items[idx - 1] = items[idx - 1], items[idx]
                idx -= 1
            elif name == "enter":
                return [i for i in items if i in on]
            elif name in ("esc", "ctrl-c", "q"):
                return None

    def field_display(self, rec, fld):
        v = rec.get(fld[0])
        kind = fld[2]
        if kind == "bool":
            return "yes" if v else "no"
        if kind == "tri":
            return "unset" if v in (None, "") else ("yes" if v else "no")
        if kind == "list":
            return ", ".join(v) if v else ""
        if kind == "lines":
            return "%d lines" % len(v) if v else ""
        if kind == "multiline":
            return "%d lines" % len(str(v).split("\n")) if v else ""
        return "" if v in (None, "") else str(v)

    def field_edit(self, rec, fld):
        """Edit one field of a record. Returns False if cancelled."""
        key, label, kind = fld[0], fld[1], fld[2]
        extra = fld[3] if len(fld) > 3 else None
        cur = rec.get(key)
        if kind == "bool":
            rec[key] = not cur
        elif kind == "tri":
            i = self.menu(label, ["unset", "yes", "no"])
            if i is None:
                return False
            rec[key] = None if i == 0 else (i == 1)
        elif kind == "choice":
            ch = list(self.sort_names() if extra == "sorts" else extra or [])
            i = self.menu(label, ["(none)"] + ch)
            if i is None:
                return False
            rec[key] = "" if i == 0 else ch[i - 1]
        elif kind == "list":
            t = self.prompt(label + "  (comma separated)", ", ".join(cur or []))
            if t is None:
                return False
            rec[key] = [x.strip() for x in t.split(",") if x.strip()]
        elif kind == "lines":
            t = self.edit_text(label, "\n".join(cur or []), footer="one entry per line")
            if t is None:
                return False
            rec[key] = [x.strip() for x in t.split("\n") if x.strip()]
        elif kind == "multiline":
            t = self.edit_text(label, cur or "")
            if t is None:
                return False
            rec[key] = t.rstrip()
        elif kind == "int":
            t = self.prompt(label, str(cur or ""))
            if t is None:
                return False
            try:
                rec[key] = int(t.strip()) if t.strip() else 0
            except ValueError:
                self.say("that is not a number", "err")
                return False
        elif kind == "color":
            t = self.prompt(label + "  (#rrggbb, 0-255, name or theme role)", str(cur or ""))
            if t is None:
                return False
            if t.strip() and not color_valid(t):
                self.say("not a valid color", "err")
                return False
            rec[key] = t.strip()
        else:
            if extra:
                ch = list(extra)
                i = self.menu(label, ch + ["(type your own)"])
                if i is None:
                    return False
                if i < len(ch):
                    rec[key] = ch[i]
                    return True
            t = self.prompt(label, str(cur or ""))
            if t is None:
                return False
            rec[key] = t.strip() if key in ("name", "key") else t
        return True

    def record_form(self, rec, fields, commit):
        idx = 0
        while True:
            labels = ["%-24s %s" % (f[1], clip(self.field_display(rec, f), 40)) for f in fields] + ["back"]
            i = self.menu(clip(str(rec.get(fields[0][0], "new")), 30), labels, idx)
            if i is None or i == len(fields):
                return
            idx = i
            if self.field_edit(rec, fields[i]):
                commit()

    def records_editor(self, title, recs, fields, commit):
        idx = 0
        f0 = fields[0][0]
        f1 = fields[1][0] if len(fields) > 1 else None

        def summary(r):
            s_ = str(r.get(f0) or "(unnamed)")
            if f1 and r.get(f1):
                s_ += "    " + clip(str(r[f1]), 32)
            return s_

        while True:
            labels = [summary(r) for r in recs] + ["+ add new", "done"]
            i = self.menu(title, labels, idx)
            if i is None or i == len(labels) - 1:
                return recs
            idx = i
            if i == len(recs):
                rec = {}
                if not self.field_edit(rec, fields[0]) or not rec.get(f0):
                    continue
                recs.append(rec)
                commit(recs)
                self.record_form(rec, fields, lambda: commit(recs))
                idx = len(recs) - 1
                continue
            rec = recs[i]
            j = self.menu(summary(rec), ["edit fields", "move up", "move down", "delete"])
            if j == 0:
                self.record_form(rec, fields, lambda: commit(recs))
            elif j == 1 and i > 0:
                recs[i - 1], recs[i] = recs[i], recs[i - 1]
                idx = i - 1
            elif j == 2 and i < len(recs) - 1:
                recs[i + 1], recs[i] = recs[i], recs[i + 1]
                idx = i + 1
            elif j == 3 and self.confirm("delete %s?" % clip(summary(rec), 30)):
                del recs[i]
                idx = max(0, i - 1)
            commit(recs)

    def sv_edit_records(self, it):
        cur = self.sv_get(it)
        label = it["label"]
        if it.get("dict"):
            vk = it.get("vkind", "text")
            names = it.get("names")
            fields = [("name", it.get("klabel", "Name"), "text", names), ("value", it.get("vlabel", "Value"), vk)]
            recs = [{"name": k, "value": v} for k, v in (cur or {}).items()]

            def commit(rs):
                out = {}
                for r in rs:
                    if r.get("name") and r.get("value") not in ("", None):
                        v = r["value"]
                        out[r["name"]] = v
                self.sv_set(it, out)

            self.records_editor(label, recs, fields, commit)
            commit(recs)
        else:
            fields = RECORD_FIELDS[it["fields"]]
            recs = [dict(r) for r in (cur or []) if isinstance(r, dict)]

            def commit(rs):
                self.sv_set(it, [clean_record(r, fields) for r in rs if r.get(fields[0][0])])

            self.records_editor(label, recs, fields, commit)
            commit(recs)

    def sv_edit(self, it):
        kind = it["kind"]
        cur = self.sv_get(it)
        label = it["label"]
        if kind == "bool":
            self.sv_set(it, not cur)
        elif kind == "choice":
            ch = self.sv_choices(it)
            if not ch:
                return
            start = ch.index(cur) if cur in ch else 0
            orig = cur
            i = self.menu(label, ch, start, on_move=lambda j: self.sv_set(it, ch[j]))
            if i is None:
                self.sv_set(it, orig)
            else:
                self.sv_set(it, ch[i])
        elif kind in ("int", "float"):
            t = self.prompt("%s  (%s to %s)" % (label, it["min"], it["max"]), str(cur))
            if t is None:
                return
            try:
                v = int(t) if kind == "int" else float(t)
            except ValueError:
                self.say("that is not a number", "err")
                return
            self.sv_set(it, max(it["min"], min(it["max"], v)))
        elif kind == "text":
            t = self.prompt(label, str(cur or ""))
            if t is not None:
                self.sv_set(it, t)
        elif kind == "multiline":
            t = self.edit_text(label, cur or "", footer=it["desc"])
            if t is not None:
                self.sv_set(it, t.rstrip())
        elif kind == "order":
            res = self.order_editor(label, it["available"], list(cur or []), it.get("required", ()))
            if res is not None:
                self.sv_set(it, res)
        elif kind == "strlist":
            t = self.prompt(label + "  (comma separated)", ", ".join(str(x) for x in (cur or [])))
            if t is None:
                return
            vals = [x.strip() for x in t.split(",")] if t.strip() else []
            if it.get("count") and len(vals) != it["count"]:
                self.say("needs exactly %d values" % it["count"], "err")
                return
            self.sv_set(it, vals)
        elif kind == "color":
            t = self.prompt(label + "  (#rrggbb, 0-255, or a color name)", str(cur or ""))
            if t is None:
                return
            if not color_valid(t):
                self.say("not a valid color", "err")
                return
            self.sv_set(it, t.strip())
        elif kind == "keys":
            t = self.prompt(label + "  (comma separated, none to unbind)", str(cur if cur != "none" else ""))
            if t is not None:
                self.sv_set(it, parse_key_list(t))
        elif kind == "records":
            self.sv_edit_records(it)
        elif kind == "action":
            getattr(self, "sv_action_" + it["run"])()

    def sv_control(self, it):
        """Return (text, role, swatch color or None) for the value box of a setting."""
        kind = it["kind"]
        v = self.sv_get(it) if kind != "action" else None
        arrow = "v" if self.opts["ascii"] else "▼"
        if kind == "bool":
            return ("[%s]" % ("v" if v else " "), "accent2" if v else "dim", None)
        if kind == "choice":
            ch = self.sv_choices(it)
            wid = min(18, max([len(str(c)) for c in ch] + [6]))
            return ("[%s %s]" % (pad(str(v), wid), arrow), "accent2", None)
        if kind in ("int", "float"):
            return ("[ %s ]" % v, "accent2", None)
        if kind == "multiline":
            n = len(str(v).split("\n")) if v else 0
            return ("[ %s ]" % ("%d lines, edit..." % n if n else "empty, edit..."), "accent2", None)
        if kind in ("order", "strlist"):
            return ("[%s]" % (", ".join(str(x) for x in v) if v else "default"), "accent2", None)
        if kind == "color":
            return ("[%s]" % v, "accent2", v if isinstance(v, str) and v.startswith("#") else None)
        if kind == "keys":
            return ("[%s]" % v, "accent2", None)
        if kind == "records":
            n = len(v or [])
            return ("[ %d %s, edit... ]" % (n, "entry" if n == 1 else "entries"), "accent2", None)
        if kind == "action":
            return ("[ %s ]" % it.get("button", "Run"), "accent2", None)
        return ("[%s]" % (v if v not in ("", None) else "(empty)"), "accent2" if v else "dim", None)

    # advanced actions
    def sv_action_open_config(self):
        self.open_in_editor(self.cfg_path)
        self.sv_action_reload_files()

    def sv_action_open_settings(self):
        if not os.path.exists(self.settings_path):
            save_settings_file(self.settings_path, self.user_settings)
        self.open_in_editor(self.settings_path)
        self.sv_action_reload_files()

    def sv_action_reload_files(self):
        self.cfg = load_config(self.cfg_path, lambda m: self.say(m, "err"), self.args.profile)
        self.user_settings = load_settings(self.settings_path)
        self.apply_config()
        self.say("files reloaded", "ok")

    def sv_action_reset_all(self):
        if self.confirm("remove every change made in the settings panel?"):
            self.user_settings = {}
            self.apply_config()
            self.say("all settings reset", "ok")

    # ----- settings: the panel -----

    def act_settings(self, search=""):
        tree = build_settings_tree()
        S = {"focus": "tree", "node": 0, "item": 0, "top": 0, "tree_top": 0, "search": search, "btn": 2,
             "hits": [], "snap": copy.deepcopy(self.user_settings), "click": (0.0, None),
             "open": {n["name"] for n in tree if n["children"]}}

        def visible():
            out = []
            for n in tree:
                out.append((n, 0))
                if n["children"] and n["name"] in S["open"]:
                    out.extend((c, 1) for c in n["children"])
            return out

        def node_items(n):
            return self.sv_dynamic(n["dyn"]) if n["dyn"] else n["items"]

        def current_items():
            if S["search"]:
                found = []
                toks = S["search"].lower().split()
                for n in [x for t in tree for x in [t] + t["children"]]:
                    for it in node_items(n):
                        label = it["label"].lower()
                        hay = "%s %s %s %s" % (label, it.get("key") or "", it["desc"].lower(), n["name"].lower())
                        if all(tk in hay for tk in toks):
                            rank = 0 if all(tk in label for tk in toks) else 1
                            found.append((rank, dict(it, _path=n["name"])))
                found.sort(key=lambda r: r[0])
                return [f for _, f in found]
            vis = visible()
            S["node"] = max(0, min(S["node"], len(vis) - 1))
            return node_items(vis[S["node"]][0])

        def dirty():
            return self.user_settings != S["snap"]

        def card_desc(it):
            return ("[%s] %s" % (it["_path"], it["desc"])) if it.get("_path") else it["desc"]

        def card_layout(items, cw_):
            hs = []
            for it in items:
                nd = len(wrap(card_desc(it), max(10, cw_ - 4))) or 1
                hs.append(3 + nd)
            return hs

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            S["hits"] = []
            if H < 14 or W < 60:
                self.put(0, 0, "terminal too small for settings (esc closes)", self.attr("err"))
                return
            ascii_ = self.opts["ascii"]
            self.box(0, 0, H, W, "Settings [%s]" % (self.args.profile or "User"))
            self.put(H - 1, 0, self.sym["corner_bl"] + self.sym["hline"] * (W - 2), self.attr("border"))
            with contextlib.suppress(curses.error):
                self.scr.addstr(H - 1, W - 1, self.sym["corner_br"], self.attr("border"))
            key_attr = self.attr("fg", "sel_bg", bold=True)
            x = self.put(1, 2, "Press ", self.attr("dim"))
            x = self.put(1, x, " / ", key_attr)
            if S["search"]:
                self.put(1, x, " search: %s   (esc clears)" % S["search"], self.attr("today", bold=True))
            else:
                self.put(1, x, " to search settings...", self.attr("dim"))
            lw = 22 if W < 90 else 28
            top, bot = 3, H - 4
            for yy in range(top, bot + 1):
                self.put(yy, lw, self.sym["vline"], self.attr("border"))
            self.put(H - 3, 1, self.sym["hline"] * (W - 2), self.attr("border"))
            # tree
            vis = visible()
            S["node"] = max(0, min(S["node"], len(vis) - 1))
            rows = bot - top + 1
            if S["node"] < S["tree_top"]:
                S["tree_top"] = S["node"]
            if S["node"] >= S["tree_top"] + rows:
                S["tree_top"] = S["node"] - rows + 1
            for r in range(rows):
                i = S["tree_top"] + r
                if i >= len(vis):
                    break
                n, depth = vis[i]
                on = i == S["node"] and not S["search"]
                if n["children"]:
                    mark = ("v" if ascii_ else "▼") if n["name"] in S["open"] else (">" if ascii_ else "▶")
                else:
                    mark = " "
                label = "%s%s %s" % ("   " if depth else "", mark, n["name"])
                if on:
                    a = self.attr("bg", "accent", bold=True) if S["focus"] == "tree" else self.attr("accent", "sel_bg", bold=True)
                    self.fill(top + r, 1, lw - 1, a)
                else:
                    a = self.attr("fg")
                self.put(top + r, 2, clip(label, lw - 3), a, lw - 3)
                S["hits"].append(("node", 1, top + r, lw, top + r + 1, i))
            # right pane
            items = current_items()
            rx = lw + 2
            cwid = W - rx - 2
            title = ("Search results" if S["search"] else vis[S["node"]][0]["name"])
            self.put(top, rx, title, self.attr("accent", bold=True), cwid)
            blurb = "" if S["search"] else vis[S["node"]][0].get("blurb", "")
            ytop = top + 2
            if blurb:
                self.put(top + 1, rx, clip(blurb, cwid), self.attr("dim"), cwid)
            if not S["search"] and vis[S["node"]][0]["children"] and not items:
                self.put(ytop, rx, "Sections:", self.attr("dim"))
                for k, c in enumerate(vis[S["node"]][0]["children"]):
                    self.put(ytop + 1 + k, rx + 2, c["name"], self.attr("fg"))
                self.put(ytop + 2 + len(vis[S["node"]][0]["children"]), rx, "right or enter opens them", self.attr("dim"))
            S["item"] = max(0, min(S["item"], len(items) - 1)) if items else 0
            if S["search"] and not items:
                self.put(ytop, rx, "nothing matches", self.attr("dim"))
            hs = card_layout(items, cwid)
            avail = bot - ytop + 1
            # scroll so that the selected card is fully visible
            if S["top"] > S["item"]:
                S["top"] = S["item"]
            while S["top"] < S["item"] and sum(hs[S["top"]:S["item"] + 1]) > avail:
                S["top"] += 1
            S["top"] = max(0, min(S["top"], max(0, len(items) - 1)))
            lab_w = min(26, max([cell_len(it["label"]) for it in items] + [8]))
            yy = ytop
            for i in range(S["top"], len(items)):
                it, hgt = items[i], hs[i]
                if yy + hgt > bot + 1:
                    break
                sel = i == S["item"]
                brd = self.attr("accent" if sel and S["focus"] == "cards" else ("accent2" if sel else "border"))
                s_ = self.sym
                self.put(yy, rx, s_["corner_tl"] + s_["hline"] * (cwid - 2) + s_["corner_tr"], brd)
                self.put(yy + hgt - 1, rx, s_["corner_bl"] + s_["hline"] * (cwid - 2) + s_["corner_br"], brd)
                for k in range(1, hgt - 1):
                    self.put(yy + k, rx, s_["vline"], brd)
                    self.put(yy + k, rx + cwid - 1, s_["vline"], brd)
                    if sel:
                        self.fill(yy + k, rx + 1, cwid - 2, self.attr("fg", "sel_bg"))
                bg = "sel_bg" if sel else "bg"
                text, role, swatch = self.sv_control(it)
                self.put(yy + 1, rx + 2, pad(it["label"], lab_w), self.attr("fg", bg, bold=True))
                cx = self.put(yy + 1, rx + 2 + lab_w, " : ", self.attr("dim", bg))
                cx = self.put(yy + 1, cx, text, self.attr(role, bg, bold=True), rx + cwid - 3 - cx)
                if swatch:
                    self.put(yy + 1, cx + 1, "██" if not ascii_ else "##", self.attr(swatch, bg), 2)
                if self.sv_changed(it):
                    self.put(yy + 1, rx + cwid - 8, "(user)", self.attr("accent2", bg), 7)
                for k, ln in enumerate(wrap(card_desc(it), max(10, cwid - 4)) or [""]):
                    self.put(yy + 2 + k, rx + 2, ln, self.attr("dim", bg), cwid - 4)
                S["hits"].append(("card", rx, yy, rx + cwid, yy + hgt, i))
                yy += hgt
            # footer
            fx = 2
            hints = [("up/dn" if ascii_ else "↑↓", "Navigate"), ("Tab", "Next"), ("Enter", "Edit"),
                     ("/", "Search"), ("Esc", "Close")]
            labels = ["User", "Reset", "Save*" if dirty() else "Save", "Cancel"]
            bx = W - 3 - sum(cell_len(l_) + 5 for l_ in labels)
            for k, lab in hints:
                need = cell_len(k) + 2 + cell_len(lab) + 2
                if fx + need > bx - 1:
                    break
                fx = self.put(H - 2, fx, " %s " % k, key_attr)
                fx = self.put(H - 2, fx, lab + "  ", self.attr("dim"))
            for bi, l_ in enumerate(labels):
                txt = "[ %s ]" % l_
                focus = S["focus"] == "buttons" and S["btn"] == bi
                a = self.attr("bg", "accent", bold=True) if focus else self.attr("fg" if bi != 2 or not dirty() else "today", bold=True)
                self.put(H - 2, bx, txt, a)
                S["hits"].append(("btn", bx, H - 2, bx + cell_len(txt), H - 1, bi))
                bx += cell_len(txt) + 2

        def do_save():
            ok = self.save_user_settings()
            S["snap"] = copy.deepcopy(self.user_settings)
            self.say("settings saved to " + self.settings_path if ok else "could not write settings", "ok" if ok else "err", 4)

        def revert():
            self.user_settings = copy.deepcopy(S["snap"])
            self.apply_config()

        def close_flow():
            if S["search"]:
                S["search"] = ""
                S["item"] = S["top"] = 0
                return False
            if dirty():
                i = self.menu("unsaved changes", ["Save and close", "Discard changes", "Keep editing"])
                if i is None or i == 2:
                    return False
                if i == 0:
                    do_save()
                else:
                    revert()
            return True

        def reset_current():
            items = current_items()
            if items:
                it = items[min(S["item"], len(items) - 1)]
                if it["kind"] == "action":
                    return
                self.sv_reset(it)
                self.say("reset: " + it["label"])

        def edit_current():
            items = current_items()
            if items:
                self.sv_edit(items[min(S["item"], len(items) - 1)])

        def press(bi):
            if bi == 0:
                self.say("saved to " + self.settings_path, "dim", 4)
            elif bi == 1:
                reset_current()
            elif bi == 2:
                do_save()
            else:
                if dirty() and not self.confirm("discard unsaved changes?"):
                    return False
                revert()
                return True
            return False

        def move(delta):
            items = current_items()
            if items:
                S["item"] = max(0, min(len(items) - 1, S["item"] + delta))

        def handle(name, ch):
            vis = visible()
            if name == "ctrl-s":
                do_save()
                return False
            if name == "ctrl-c":
                return close_flow()
            if name == "esc" or (name == "q" and S["focus"] == "tree" and not S["search"]):
                return close_flow()
            if name == "/":
                q = self.prompt("search settings", S["search"], hist="settings")
                if q is not None:
                    S["search"] = q.strip()
                    S["item"] = S["top"] = 0
                    S["focus"] = "cards" if S["search"] else "tree"
                return False
            if name == "tab":
                order = ["tree", "cards", "buttons"] if not S["search"] else ["cards", "buttons"]
                S["focus"] = order[(order.index(S["focus"]) + 1) % len(order)] if S["focus"] in order else order[0]
                return False
            if name == "shift-tab":
                order = ["tree", "cards", "buttons"] if not S["search"] else ["cards", "buttons"]
                S["focus"] = order[(order.index(S["focus"]) - 1) % len(order)] if S["focus"] in order else order[0]
                return False
            if S["focus"] == "tree" and not S["search"]:
                n = vis[S["node"]][0]
                if name in ("down", "j"):
                    S["node"] = min(len(vis) - 1, S["node"] + 1)
                    S["item"] = S["top"] = 0
                elif name in ("up", "k"):
                    S["node"] = max(0, S["node"] - 1)
                    S["item"] = S["top"] = 0
                elif name in ("right", "l", "enter", "space"):
                    if n["children"]:
                        if name in ("enter", "space"):
                            S["open"].symmetric_difference_update({n["name"]})
                        elif n["name"] not in S["open"]:
                            S["open"].add(n["name"])
                        else:
                            S["node"] += 1
                            S["item"] = S["top"] = 0
                    else:
                        S["focus"] = "cards"
                elif name in ("left", "h"):
                    if n["children"] and n["name"] in S["open"]:
                        S["open"].discard(n["name"])
                    elif not n["children"]:
                        for k, (m, d) in enumerate(vis):
                            if d == 0 and m["children"] and n in m["children"]:
                                S["node"] = k
                                break
                elif name in ("g", "home"):
                    S["node"] = 0
                elif name in ("G", "end"):
                    S["node"] = len(vis) - 1
                return False
            if S["focus"] == "buttons":
                if name in ("left", "h"):
                    S["btn"] = (S["btn"] - 1) % 4
                elif name in ("right", "l"):
                    S["btn"] = (S["btn"] + 1) % 4
                elif name in ("enter", "space"):
                    return press(S["btn"])
                elif name in ("up", "k"):
                    S["focus"] = "cards"
                return False
            # cards
            if name in ("down", "j"):
                move(1)
            elif name in ("up", "k"):
                move(-1)
            elif name in ("pgdn", "ctrl-d"):
                move(4)
            elif name in ("pgup", "ctrl-u"):
                move(-4)
            elif name in ("g", "home"):
                S["item"] = 0
            elif name in ("G", "end"):
                move(10 ** 6)
            elif name in ("enter", "space", "l", "right"):
                edit_current()
            elif name in ("left", "h") and not S["search"]:
                S["focus"] = "tree"
            elif name in ("r", "delete", "backspace"):
                reset_current()
            return False

        def on_mouse():
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                return False
            up = getattr(curses, "BUTTON4_PRESSED", 0)
            down = getattr(curses, "BUTTON5_PRESSED", 0)
            if up and bstate & up:
                move(-1)
                return False
            if down and bstate & down:
                move(1)
                return False
            if not bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
                return False
            for kind, x0, y0, x1, y1, pl in S["hits"]:
                if not (x0 <= mx < x1 and y0 <= my < y1):
                    continue
                now = time.time()
                again = S["click"][1] == (kind, pl) and now - S["click"][0] < 0.5
                S["click"] = (now, (kind, pl))
                if kind == "btn":
                    S["focus"], S["btn"] = "buttons", pl
                    return press(pl)
                if kind == "node":
                    vis = visible()
                    S["search"] = ""
                    S["node"], S["item"], S["top"] = pl, 0, 0
                    n = vis[pl][0]
                    if n["children"]:
                        S["open"].symmetric_difference_update({n["name"]})
                    S["focus"] = "tree" if n["children"] else "cards"
                    return False
                if kind == "card":
                    already = S["item"] == pl and S["focus"] == "cards"
                    S["focus"], S["item"] = "cards", pl
                    if already or again:
                        edit_current()
                    return False
            return False

        self.backdrop = render
        try:
            while True:
                render()
                self.scr.refresh()
                name, ch = self.read_key()
                if name in ("tick", "resize"):
                    continue
                if name == "mouse":
                    if on_mouse():
                        break
                    continue
                if handle(name, ch):
                    break
        finally:
            self.backdrop = self.draw
            self.tick_override = None
            self.rebuild()
        self.scr.clear()


    # ----- input dispatch -----

    def handle_mouse(self):
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return
        g = self.geo
        if not g:
            return
        up = getattr(curses, "BUTTON4_PRESSED", 0)
        down = getattr(curses, "BUTTON5_PRESSED", 0)
        if bstate & up:
            self.move_cursor(-3)
            return
        if down and bstate & down:
            self.move_cursor(3)
            return
        if not bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
            return
        for x0, x1, ty, name in self.detail_hits:
            if ty == my and x0 <= mx < x1:
                self.act_detail_tab(name=name)
                return
        if g["sw"] and mx < g["sw"]:
            items = self.sidebar_items()
            r = my - g["list_y"]
            if 0 <= r < len(items) and not items[r]["head"]:
                self.set_view(items[r]["key"])
                self.focus = "sidebar"
            return
        if g["list_x"] <= mx < g["list_x"] + g["list_w"] and g["list_y"] <= my < g["list_y"] + g["list_h"]:
            i = self.top + (my - g["list_y"])
            if 0 <= i < len(self.rows):
                self.focus = "list"
                self.cur = i
                self.cur_id = self.rows[i][0]["id"]
                now = time.time()
                if mx <= g["list_x"] + 4 and "check" in self.opts["columns"]:
                    self.act_toggle()
                elif self.last_click[1] == i and now - self.last_click[0] < 0.45:
                    self.act_edit()
                self.last_click = (now, i)

    def resolve_chord(self, name):
        if self.pending:
            seq = self.pending + " " + name
            self.pending = ""
            if seq in self.keymap:
                return self.keymap[seq]
            if seq in self.chord_prefixes:
                self.pending = seq
            return None
        if name in self.chord_prefixes:
            self.pending = name
            return None
        return self.keymap.get(name)

    def dispatch(self, name):
        if name == "mouse":
            self.handle_mouse()
            return
        if name in ("tick", "resize"):
            return
        action = self.resolve_chord(name)
        if action is None:
            return
        if action.startswith("act:"):
            acts = self.custom_actions()
            n = int(action[4:])
            if n < len(acts):
                self.run_action(acts[n])
            return
        if action.startswith("tpl:"):
            tpls = self.opts.get("templates", [])
            n = int(action[4:])
            if n < len(tpls):
                self.run_template(tpls[n])
            return
        if self.focus == "sidebar" and action in ("up", "down", "top", "bottom", "expand", "edit", "toggle", "collapse"):
            keys = [i["key"] for i in self.sidebar_items() if not i["head"]]
            if self.view not in keys:
                return
            idx = keys.index(self.view)
            if action == "up":
                self.set_view(keys[max(0, idx - 1)])
            elif action == "down":
                self.set_view(keys[min(len(keys) - 1, idx + 1)])
            elif action == "top":
                self.set_view(keys[0])
            elif action == "bottom":
                self.set_view(keys[-1])
            else:
                self.focus = "list"
            return
        h = self.height_hint()
        simple = {
            "up": lambda: self.move_cursor(-1),
            "down": lambda: self.move_cursor(1),
            "top": lambda: self.move_cursor(0, True),
            "bottom": lambda: self.move_cursor(len(self.rows) - 1, True),
            "pgup": lambda: self.move_cursor(-h),
            "pgdn": lambda: self.move_cursor(h),
            "toggle": self.act_toggle,
            "add": self.act_add,
            "add_top": lambda: self.act_add(at_top=True),
            "add_child": lambda: self.act_add(child=True),
            "edit": self.act_edit,
            "notes": self.act_notes,
            "delete": self.act_delete,
            "prio_up": lambda: self.act_prio(1),
            "prio_down": lambda: self.act_prio(-1),
            "due": self.act_due,
            "tags": self.act_tags,
            "project": self.act_project,
            "repeat": self.act_repeat,
            "move_up": lambda: self.act_move(-1),
            "move_down": lambda: self.act_move(1),
            "fold": lambda: self.act_fold("toggle"),
            "collapse": lambda: self.act_fold("collapse"),
            "expand": lambda: self.act_fold("expand"),
            "search": self.act_search,
            "sort": self.act_sort,
            "undo": self.do_undo,
            "redo": self.do_redo,
            "select": self.act_select,
            "select_all": self.act_select_all,
            "theme": self.act_theme,
            "palette": self.act_palette,
            "help": self.act_help,
            "clear_done": self.act_clear_done,
            "hide_done": lambda: self.toggle_opt("show_done"),
            "toggle_sidebar": lambda: self.toggle_opt("sidebar"),
            "toggle_detail": self.act_toggle_detail,
            "view_next": lambda: self.cycle_view(1),
            "view_prev": lambda: self.cycle_view(-1),
            "redraw": self.scr.clear,
            "find": self.act_find,
            "links": self.act_links,
            "link_add": self.act_link_add,
            "back": self.act_back,
            "track": self.act_track,
            "focus_mode": self.act_focus,
            "stats": self.act_stats,
            "calendar": self.act_calendar,
            "note_add": self.act_note_add,
            "deps": self.act_deps,
            "snooze": self.act_snooze,
            "journal": self.act_journal,
            "habits": self.act_habits,
            "projects": self.act_projects,
            "template": self.act_template,
            "actions_menu": self.act_actions_menu,
            "detail_down": lambda: self.act_detail_scroll(3),
            "detail_up": lambda: self.act_detail_scroll(-3),
            "detail_tab": self.act_detail_tab,
            "duplicate": self.act_duplicate,
            "yank": self.act_yank,
            "settings": self.act_settings,
        }
        if action == "quit":
            self.running = False
        elif action == "focus":
            self.focus = "sidebar" if self.focus == "list" and self.geo.get("sw") else "list"
        elif action == "clear_filter":
            if self.selected:
                self.selected.clear()
            elif self.query:
                self.query = ""
            elif self.focus == "sidebar":
                self.focus = "list"
        elif action in simple:
            simple[action]()

    def height_hint(self):
        return max(1, self.geo.get("list_h", 10) - 1)

    def do_undo(self):
        self.say("undone" if self.store.undo() else "nothing to undo")
        self.store.save()

    def do_redo(self):
        self.say("redone" if self.store.redo() else "nothing to redo")
        self.store.save()

    def act_select(self):
        t = self.current()
        if not t:
            return
        if t["id"] in self.selected:
            self.selected.discard(t["id"])
        else:
            self.selected.add(t["id"])
        self.move_cursor(1)

    def act_select_all(self):
        ids = {r[0]["id"] for r in self.rows}
        self.selected = set() if self.selected >= ids else ids

    def run(self):
        curses.curs_set(0)
        curses.use_default_colors()
        if self.opts.get("mouse", True):
            with contextlib.suppress(curses.error):
                curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        self.scr.keypad(True)
        with contextlib.suppress(Exception):
            import termios
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            attrs[0] &= ~(termios.IXON | termios.IXOFF)
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        self.wake_check()
        start = self.opts.get("start_screen", "list")
        starters = {"journal": self.act_journal, "habits": self.act_habits, "projects": self.act_projects,
                    "stats": self.act_stats, "calendar": self.act_calendar,
                    "agenda": lambda: self.act_calendar("agenda")}
        if start in starters:
            starters[start]()
        while self.running:
            self.wake_check()
            self.draw()
            name, _ = self.read_key()
            self.dispatch(name)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(prog="synth", description="synth. a fullscreen terminal todo list")
    ap.add_argument("--data", help="path to the todos json file")
    ap.add_argument("--config", help="path to the config toml")
    ap.add_argument("--theme", help="theme to start with")
    ap.add_argument("--view", help="view to start in (all, today, upcoming, inbox, done)")
    ap.add_argument("--profile", help="also load config-NAME.toml from the config directory")
    ap.add_argument("--habits", action="store_true", help="print habits done today as done/total and exit")
    ap.add_argument("--count", action="store_true", help="print the number of open tasks and exit")
    ap.add_argument("--due-count", action="store_true", help="print the number of open tasks due today or overdue")
    ap.add_argument("--tracking", action="store_true", help="print the task being tracked and exit")
    ap.add_argument("--list-themes", action="store_true", help="print theme names and exit")
    ap.add_argument("--print-config", action="store_true", help="print the default config and exit")
    ap.add_argument("--version", action="version", version="synth " + VERSION)
    args = ap.parse_args(argv)

    if args.print_config:
        sys.stdout.write(CONFIG_TEMPLATE)
        return 0
    if args.list_themes:
        print("\n".join(THEMES))
        return 0

    data_path = args.data or os.environ.get("SYNTH_DATA") or DATA_PATH
    cfg_path = args.config or os.environ.get("SYNTH_CONFIG") or CONFIG_PATH
    store = Store(data_path)

    if args.count or args.due_count:
        td = today()
        f = compile_query("is:open due:now" if args.due_count else "is:open", store)
        print(sum(1 for t in store.tasks if f(t, td) and not is_snoozed(t, td)))
        return 0

    if args.habits:
        d_, t_ = habit_summary(store, today())
        print("%d/%d" % (d_, t_))
        return 0

    if args.tracking:
        a = store.active
        if a:
            t = store.get(a["id"])
            try:
                secs = int((dt.datetime.now() - dt.datetime.fromisoformat(a["start"])).total_seconds())
            except ValueError:
                secs = 0
            print("%s %s" % (fmt_duration(secs, True), t["title"] if t else ""))
        return 0

    if not sys.stdout.isatty():
        sys.stderr.write("synth needs a terminal\n")
        return 1

    warnings = []
    cfg = load_config(cfg_path, warnings.append, args.profile)
    state = load_state()
    os.environ.setdefault("ESCDELAY", "25")

    def run(scr):
        app = App(scr, cfg, store, state, cfg_path, args)
        for w in warnings:
            app.say(w, "err", 6)
        app.run()

    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
