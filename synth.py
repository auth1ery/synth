#!/usr/bin/env python3
"""synth: a fullscreen, hackable terminal todo list.

Run `synth` to open the TUI. Press ? inside for every key binding.
Config lives in ~/.config/synth/config.toml, data in ~/.local/share/synth.
"""

import argparse
import base64
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
import select
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import unicodedata

try:
    import ssl
except ImportError:  # a Python built without TLS can still run synth
    ssl = None

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
    "changes": ["W"],
    "git": ["ctrl-g"],
    "review": ["R"],
    "bulk": ["M"],
    "dump": ["Q"],
    "whatnow": ["."],
    "graph": ["m"],
    "travel": ["ctrl-t"],
    "duplicate": ["alt-y"],
    "yank": ["y"],
    "settings": [","],
    "irc": ["ctrl-k"],
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
    "changes": "what changed (timeline of edits)",
    "git": "git menu: TODOs, branches, commits, data sync",
    "irc": "IRC chat, talk while you work",
    "review": "weekly review",
    "bulk": "bulk edit the selection",
    "dump": "brain dump: paste notes, review, import as tasks",
    "whatnow": "what now? the best task for the time and energy you have",
    "graph": "dependency graph (map)",
    "travel": "time travel through your data history in git",
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
    "header_momentum": True,
    "history": True,
    "ics_sources": [],
    "ics_refresh": 30,
    "sync_output": True,
    "git_sync": False,
    "git_push": False,
    "git_commit_delay": 5,
    "git_auto_done": True,
    "git_refresh": 5,
    "todo_markers": ["TODO", "FIXME", "HACK", "XXX"],
    "review_nudge": True,
    "header_clock": False,
    "header_left": ["app", "view", "sort", "query", "selection"],
    "header_right": ["timer", "irc", "overdue", "momentum", "habits", "clock", "progress"],
    "header_style": "plain",
    "header_text": "",
    "clock_12h": False,
    "clock_seconds": False,
    "header_date": "%a %b %d",
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
    "irc_networks": [],
    "irc_dock": False,
    "irc_layout": "off",
    "irc_sidebar": True,
    "irc_dock_lines": 4,
    "irc_show_joins": True,
    "irc_nick_colors": True,
    "irc_time": "%H:%M",
    "irc_bell": True,
    "hints": [],
    "include": [],
    "detail_tab": "notes",
    "detail_sections": ["notes", "info", "links", "history"],
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
    "detail_tab": ["notes", "info", "links", "history"],
    "note_stamp": None,
    "irc_time": None,
    "irc_layout": ["off", "right", "bottom"],
    "clock_format": None,
    "header_style": ["plain", "divided", "pills"],
    "header_text": None,
    "header_date": None,
}

SORTS = ["manual", "priority", "due", "created", "alpha"]  # custom sorts are added from [sorts]
BOOL_OPTS = ["sync_output", "git_sync", "git_push", "git_auto_done", "review_nudge", "clock_12h", "clock_seconds", "header_momentum", "history", "snooze_hide", "notes_inline", "header_habits", "header_clock", "header_progress", "header_info", "irc_dock", "irc_sidebar", "irc_show_joins", "irc_nick_colors", "irc_bell",
             "sidebar_counts", "mouse",
             "sidebar", "ascii", "transparent", "exact_colors", "animations", "show_done", "cascade_done",
             "confirm_delete", "focus_auto", "focus_bell"]
INT_OPTS = ["irc_dock_lines", "ics_refresh", "git_commit_delay", "git_refresh", "indent", "sidebar_width", "detail_size", "scrolloff", "focus_work", "focus_break", "focus_long", "focus_rounds"]
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
    "git": "⎇",
    "up": "▲",
    "down": "▼",
    "flat": "▬",
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
    "git": "g",
    "up": "+",
    "down": "-",
    "flat": "=",
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
# detail_sections = ["notes", "info", "links", "history"]   # tabs of the detail pane, press I to cycle
# detail_tab = "notes"       # tab to open with
# notes_editor = "builtin"   # builtin (ctrl-s saves) or external ($VISUAL / $EDITOR)
# note_stamp = "%Y-%m-%d %H:%M"   # stamp used by the quick note key
# notes_inline = false       # show the first line of notes after the title
# snooze_hide = true         # snoozed tasks leave every view except Snoozed
# blocked_done = "warn"      # finishing a blocked task: warn, allow or deny
# journal_template = "# {weekday}, {date}\\n\\n## Done\\n{done}\\n\\n## Notes\\n"
#   variables: {date} {weekday} {done} {done_count} {time} {open} {overdue} {habits}
# start_screen = "list"      # list, journal, habits, projects, stats, calendar, agenda

# ---- git, calendars, review ----
# git_sync = false           # commit the data folder to git after every change
# git_push = false           # pull on start and push after commits (needs a remote named origin)
# git_commit_delay = 5       # seconds to wait so a burst of edits becomes one commit
# git_auto_done = true       # complete tasks when their branch is merged, PR merged or issue closed
# git_refresh = 5            # minutes between checks of linked branches, commits and issues (0 = off)
# todo_markers = ["TODO", "FIXME", "HACK", "XXX"]
# ics_sources = ["~/calendar.ics", "https://example.com/me.ics"]   # calendar events
# ics_refresh = 30           # minutes between downloads of web calendars
# review_nudge = true        # remind you when the weekly review is a week old
# sync_output = true         # draw frames as synchronized updates (less flicker)

# ---- make it yours ----
# indent = 2                 # spaces per subtask level
# border_style = "round"     # round, square, double, heavy, ascii
# mouse = true
# header_info = true         # sort and hide-done text in the header
# header_progress = true     # progress bar
# header_habits = true       # habits done today
# header_momentum = true     # streak and weekly trend in the header
# history = true             # record a per-task timeline of changes
# header_left = ["app", "view", "sort", "query", "selection"]   # top bar widgets, left side
# header_right = ["timer", "irc", "overdue", "momentum", "habits", "clock", "progress"]
#   widgets: app view sort query selection timer progress momentum habits clock date open overdue due_today greeting week text
# header_style = "plain"     # plain, divided, pills
# header_text = ""           # shown by the text widget
# clock_12h = false          # 3:07 PM instead of 15:07
# clock_seconds = false
# clock_format = "%H:%M"     # anything else overrides clock_12h and clock_seconds
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


WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NATURAL_DUE_RE = re.compile(
    r"(?:\s+(?:by|on|before|due|until))?\s+(today|tonight|tomorrow|tmrw|next week|next (?:%s)|%s|in \d+ (?:day|days|week|weeks))\s*$"
    % ("|".join(WEEKDAY_NAMES), "|".join(WEEKDAY_NAMES)), re.I)


def natural_due(title, td=None):
    """Split a trailing date phrase off a title. Returns (title, iso date or None)."""
    td = td or today()
    m = NATURAL_DUE_RE.search(title)
    if not m or not title[:m.start()].strip():
        return title, None
    word = m.group(1).lower()
    d = None
    if word in ("today", "tonight"):
        d = td
    elif word in ("tomorrow", "tmrw"):
        d = td + dt.timedelta(days=1)
    elif word == "next week":
        d = td + dt.timedelta(days=7 - td.weekday())
    elif word.startswith("next "):
        d = parse_date(word[5:][:3], td)
        if d and d <= td + dt.timedelta(days=7 - td.weekday() - 1):
            d += dt.timedelta(days=7)
    elif word.startswith("in "):
        n = int(word.split()[1])
        d = td + dt.timedelta(days=n * (7 if word.endswith(("week", "weeks")) else 1))
    else:
        d = parse_date(word[:3], td)
    if d is None:
        return title, None
    return title[:m.start()].rstrip(), d.isoformat()


BULLET_RE = re.compile(r"^(?:[-*+•]\s+|\d+[.)]\s+)")
CHECK_RE = re.compile(r"^\[([ xX])\]\s*")


def parse_dump(text, project=""):
    """Turn pasted notes into task items. One task per line; indentation makes subtasks;
    markdown bullets and checkboxes are understood; '# Heading' sets the project."""
    items, stack, heading = [], [], ""
    for raw in text.replace("\t", "    ").split("\n"):
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        hm = re.match(r"^#{1,6}\s+(.+)$", line)
        if hm:
            heading = re.sub(r"\s+", "-", hm.group(1).strip().rstrip(":"))
            stack = []
            continue
        line = BULLET_RE.sub("", line)
        done = False
        cm = CHECK_RE.match(line)
        if cm:
            done = cm.group(1) in "xX"
            line = line[cm.end():]
        p = parse_quick(line)
        if p["due"] is UNSET:
            p["title"], due = natural_due(p["title"])
            if due:
                p["due"] = due
        if not p["title"]:
            continue
        while stack and stack[-1] >= indent:
            stack.pop()
        depth = len(stack)
        stack.append(indent)
        if not p["project"]:
            p["project"] = heading or project
        p["depth"], p["done"] = depth, done
        items.append(p)
    return items


def apply_parsed_task(t, p, new):
    if p["title"]:
        t["title"] = p["title"]
    t["tags"] = list(p["tags"])
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


def create_from_items(store, items, tags=None):
    """Add parsed items to the store, keeping the nesting. Returns the new tasks."""
    stack, out = [], []
    for it in items:
        while stack and stack[-1][0] >= it["depth"]:
            stack.pop()
        t = store.add(it["title"], parent=stack[-1][1]["id"] if stack else None)
        apply_parsed_task(t, it, True)
        for g in tags or []:
            if g not in t["tags"]:
                t["tags"].append(g)
        if it.get("done"):
            t["done"], t["done_at"] = True, now_iso()
        stack.append((it["depth"], t))
        out.append(t)
    return out


def cli_add(argv):
    ap = argparse.ArgumentParser(prog="synth add", description="add tasks without opening the app. Reads stdin when piped.")
    ap.add_argument("text", nargs="*", help="task text with the usual syntax (#tag @project !2 due:fri), or - for stdin")
    ap.add_argument("-p", "--project", default="", help="project for tasks that have none")
    ap.add_argument("-t", "--tag", action="append", default=[], help="tag to add (repeatable)")
    ap.add_argument("-q", "--quiet", action="store_true", help="print nothing")
    ap.add_argument("--data", help="path to the todos json file")
    ap.add_argument("--config", help="path to the config toml")
    ap.add_argument("--profile", help="also load config-NAME.toml")
    a = ap.parse_args(argv)
    text = " ".join(a.text)
    if a.text == ["-"] or (not text.strip() and not sys.stdin.isatty()):
        text = sys.stdin.read()
    if not text.strip():
        sys.stderr.write("synth add: nothing to add\n")
        return 1
    items = parse_dump(text, a.project)
    if not items:
        sys.stderr.write("synth add: nothing to add\n")
        return 1
    cfg_path = a.config or os.environ.get("SYNTH_CONFIG") or CONFIG_PATH
    store = Store(a.data or os.environ.get("SYNTH_DATA") or DATA_PATH)
    opts = load_config(cfg_path, lambda w: sys.stderr.write(w + "\n"), a.profile)
    sp = os.path.join(os.path.dirname(cfg_path), "settings%s.json" % (("-" + a.profile) if a.profile else ""))
    for k, v in load_settings(sp).items():
        if k in DEFAULTS:
            opts[k] = v
    sy = DataSync(os.path.dirname(store.path))
    if opts.get("git_sync") and sy.enabled():
        sy.push = bool(opts.get("git_push"))
        store.on_save = lambda lines: sy.mark(lines, delay=0)
    before = {t["id"]: task_sig(t) for t in store.tasks}
    made = create_from_items(store, items, [g.lower().lstrip("#") for g in a.tag])
    store.record_changes(before)
    store.save()
    sy.finish()
    if not a.quiet:
        for t in made:
            print("added #%d %s" % (t["id"], t["title"]))
    return 0


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
        "deps": [], "snooze": "", "git": {}, "src": {}, "gh": {},
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
        self.history = []
        self.change_lines = []
        self.on_save = None
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
        self.history = [e for e in data.get("history", []) if isinstance(e, dict) and "id" in e and "t" in e and "k" in e]

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".todos-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 2, "next_id": self.next_id, "tasks": self.tasks, "done_log": self.done_log,
                           "time_log": self.time_log, "active": self.active, "habits": self.habits,
                           "projects": self.projects, "journal": self.journal, "goals": self.goals,
                           "history": self.history}, fh, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)
            self.mtime = os.path.getmtime(self.path)
            if self.on_save:
                lines, self.change_lines = self.change_lines, []
                self.on_save(lines)
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
        self.undo_stack.append((copy.deepcopy(self.tasks), self.next_id, copy.deepcopy(self.done_log), copy.deepcopy((self.habits, self.projects, self.journal, self.goals, self.history))))
        del self.undo_stack[:-200]
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append((copy.deepcopy(self.tasks), self.next_id, copy.deepcopy(self.done_log), copy.deepcopy((self.habits, self.projects, self.journal, self.goals, self.history))))
        self.tasks, self.next_id, self.done_log, ex = self.undo_stack.pop()
        self.habits, self.projects, self.journal, self.goals, self.history = ex
        self.invalidate()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append((copy.deepcopy(self.tasks), self.next_id, copy.deepcopy(self.done_log), copy.deepcopy((self.habits, self.projects, self.journal, self.goals, self.history))))
        self.tasks, self.next_id, self.done_log, ex = self.redo_stack.pop()
        self.habits, self.projects, self.journal, self.goals, self.history = ex
        self.invalidate()
        return True

    def record_changes(self, before):
        """Append history events by comparing task signatures taken before an edit."""
        stamp = now_iso()
        live = set()
        for t in self.tasks:
            live.add(t["id"])
            old = before.get(t["id"])
            if old is None:
                self.history.append({"t": stamp, "id": t["id"], "k": "created", "d": t["title"]})
                self.change_lines.append("created #%d %s" % (t["id"], clip(t["title"], 60)))
                continue
            for k, d in diff_sig(old, t):
                self.history.append({"t": stamp, "id": t["id"], "k": k, "d": d})
                label = HIST_LABEL.get(k, k)
                self.change_lines.append("%s #%d %s%s" % (label, t["id"], clip(t["title"], 50),
                                                         (": " + clip(d, 50)) if d and k not in ("done", "reopen") else ""))
        gone = [i for i in before if i not in live]
        for i in gone:
            self.change_lines.append("deleted #%d %s" % (i, clip(before[i]["title"], 50)))
        if gone:
            self.history = [e for e in self.history if e["id"] in live]
        del self.history[:-HISTORY_CAP]

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


HISTORY_CAP = 6000


def task_sig(t):
    return {"title": t["title"], "done": bool(t["done"]), "prio": t["prio"], "due": t["due"],
            "project": t["project"], "tags": list(t["tags"]), "snooze": t.get("snooze", ""),
            "deps": list(t.get("deps", [])), "notes": t["notes"], "est": t.get("est", 0),
            "repeat": t["repeat"], "branch": (t.get("git") or {}).get("branch", "")}


def diff_sig(old, t):
    """Return a list of (kind, detail) describing how task t differs from old."""
    new = task_sig(t)
    out = []
    if old["done"] != new["done"]:
        out.append(("done" if new["done"] else "reopen", ""))
    if old["title"] != new["title"]:
        out.append(("title", "%s -> %s" % (old["title"], new["title"])))
    if old["prio"] != new["prio"]:
        out.append(("prio", "%d -> %d" % (old["prio"], new["prio"])))
    if old["due"] != new["due"]:
        out.append(("due", "%s -> %s" % (old["due"] or "none", new["due"] or "none")))
    if old["project"] != new["project"]:
        out.append(("project", "%s -> %s" % (old["project"] or "none", new["project"] or "none")))
    if old["tags"] != new["tags"]:
        add = [g for g in new["tags"] if g not in old["tags"]]
        rem = [g for g in old["tags"] if g not in new["tags"]]
        out.append(("tags", " ".join(["+#" + g for g in add] + ["-#" + g for g in rem])))
    if old["snooze"] != new["snooze"]:
        out.append(("snooze", ("until " + new["snooze"]) if new["snooze"] else "cleared"))
    if old["deps"] != new["deps"]:
        add = [d for d in new["deps"] if d not in old["deps"]]
        rem = [d for d in old["deps"] if d not in new["deps"]]
        out.append(("deps", " ".join(["+#%d" % d for d in add] + ["-#%d" % d for d in rem])))
    if old["notes"] != new["notes"]:
        if not old["notes"].strip():
            out.append(("notes", "notes added"))
        elif not new["notes"].strip():
            out.append(("notes", "notes cleared"))
        else:
            delta = len(new["notes"]) - len(old["notes"])
            out.append(("notes", "notes edited (%+d chars)" % delta))
    if old["est"] != new["est"]:
        out.append(("est", "%s -> %s" % (fmt_duration(old["est"]) if old["est"] else "none",
                                         fmt_duration(new["est"]) if new["est"] else "none")))
    if old["repeat"] != new["repeat"]:
        out.append(("repeat", new["repeat"] or "cleared"))
    if old.get("branch", "") != new["branch"]:
        out.append(("branch", ("linked " + new["branch"]) if new["branch"] else "unlinked"))
    return out


HIST_LABEL = {"created": "created", "done": "completed", "reopen": "reopened", "title": "renamed",
              "prio": "priority", "due": "due date", "project": "project", "tags": "tags",
              "snooze": "snoozed", "deps": "dependencies", "notes": "notes", "est": "estimate",
              "repeat": "repeat", "branch": "branch"}


def history_for(store, tid):
    """Timeline for one task: a synthetic created entry when none was recorded, then events."""
    ev = [e for e in store.history if e["id"] == tid]
    t = store.get(tid)
    if t and not any(e["k"] == "created" for e in ev):
        ev.insert(0, {"t": t["created"], "id": tid, "k": "created", "d": ""})
    ev.sort(key=lambda e: e["t"])
    return ev


def momentum_info(iso_days, td, weeks=8):
    """Streak, rolling 7 day trend against the 7 days before, and weekly totals.

    iso_days is an iterable with one iso date per completed task.
    """
    c = collections.Counter(iso_days)
    cur, best = streak_info(c.keys(), td) if c else (0, 0)
    last = sum(c.get((td - dt.timedelta(days=i)).isoformat(), 0) for i in range(7))
    prev = sum(c.get((td - dt.timedelta(days=i)).isoformat(), 0) for i in range(7, 14))
    if last == prev:
        trend = 0
    else:
        trend = 1 if last > prev else -1
    wk = []
    for w in range(weeks - 1, -1, -1):
        wk.append(sum(c.get((td - dt.timedelta(days=w * 7 + i)).isoformat(), 0) for i in range(7)))
    return {"streak": cur, "best": best, "last7": last, "prev7": prev, "trend": trend, "weeks": wk}


# ---------------------------------------------------------------------------
# git helpers (pure functions plus thin subprocess wrappers)
# ---------------------------------------------------------------------------

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b(?:\([^)]*\))?[\s:\[-]*(.*)$")
TODO_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".mypy_cache", ".tox"}


def git_run(args, cwd, timeout=10):
    """Run git. Returns (returncode, text). Never raises."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C"))
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stdout + r.stderr))


def git_root(path):
    if not path or not os.path.isdir(os.path.expanduser(path)):
        return None
    rc, out = git_run(["rev-parse", "--show-toplevel"], os.path.expanduser(path))
    return out.strip() if rc == 0 and out.strip() else None


def git_current_branch(cwd):
    rc, out = git_run(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    name = out.strip()
    return name if rc == 0 and name and name != "HEAD" else ""


def git_branches(cwd):
    rc, out = git_run(["for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd)
    return [b for b in out.split("\n") if b.strip()] if rc == 0 else []


def git_rev(cwd, ref):
    rc, out = git_run(["rev-parse", "--verify", "--quiet", ref], cwd)
    return out.strip() if rc == 0 else ""


def git_default_branch(cwd):
    rc, out = git_run(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd)
    if rc == 0 and out.strip():
        return out.strip().split("/", 1)[-1]
    have = git_branches(cwd)
    for name in ("main", "master", "trunk", "develop"):
        if name in have:
            return name
    return git_current_branch(cwd)


def git_is_ancestor(cwd, a, b):
    return git_run(["merge-base", "--is-ancestor", a, b], cwd)[0] == 0


def git_log(cwd, n=40):
    rc, out = git_run(["log", "-n", str(n), "--format=%h%x09%s"], cwd)
    rows = []
    for ln in out.split("\n") if rc == 0 else []:
        if "\t" in ln:
            sha, subj = ln.split("\t", 1)
            rows.append((sha, subj))
    return rows


def git_slug(title, tid):
    words = re.findall(r"[a-z0-9]+", title.lower())[:6]
    return "synth/%d-%s" % (tid, "-".join(words) or "task")


def todo_clean(text):
    text = text.strip()
    for tail in ("*/", "-->", '"""', "'''", "#}", "--}}"):
        if text.endswith(tail):
            text = text[:-len(tail)].strip()
    return text


def parse_todo_line(line):
    """Return (kind, text) for a source line holding a marker, else None."""
    m = TODO_RE.search(line)
    if not m:
        return None
    text = todo_clean(m.group(2))
    if not text:
        return None
    return m.group(1), text


def todo_key(path, kind, text):
    import hashlib
    return "%s|%s" % (path, hashlib.sha1(("%s %s" % (kind, text)).encode("utf-8", "replace")).hexdigest()[:10])


def scan_todos(root, markers=None, limit=400):
    """Find TODO style markers in a folder. Uses git grep inside a repo, a plain walk otherwise."""
    markers = [m for m in (markers or ["TODO", "FIXME", "HACK", "XXX"]) if re.fullmatch(r"[A-Z]{2,12}", str(m))]
    if not markers:
        return []
    root = os.path.expanduser(root)
    out = []
    pat = r"\b(%s)\b" % "|".join(markers)
    if git_root(root) is not None:
        rc, text = git_run(["grep", "-n", "-I", "--untracked", "--exclude-standard", "-E", pat], root, timeout=20)
        if rc not in (0, 1):
            text = ""
        for ln in text.split("\n"):
            parts = ln.split(":", 2)
            if len(parts) < 3 or not parts[1].isdigit():
                continue
            hit = parse_todo_line(parts[2])
            if hit and hit[0] in markers:
                out.append({"file": parts[0], "line": int(parts[1]), "kind": hit[0], "text": hit[1],
                            "key": todo_key(parts[0], hit[0], hit[1])})
            if len(out) >= limit:
                break
        return out
    rx = re.compile(pat)
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in TODO_SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            full = os.path.join(base, fn)
            try:
                if os.path.getsize(full) > 512 * 1024:
                    continue
                with open(full, "r", encoding="utf-8") as fh:
                    for n, ln in enumerate(fh, 1):
                        if rx.search(ln):
                            hit = parse_todo_line(ln)
                            if hit and hit[0] in markers:
                                rel = os.path.relpath(full, root)
                                out.append({"file": rel, "line": n, "kind": hit[0], "text": hit[1],
                                            "key": todo_key(rel, hit[0], hit[1])})
                                if len(out) >= limit:
                                    return out
            except (OSError, UnicodeDecodeError):
                continue
    return out


CLOSE_RE = re.compile(r"\b(?:closes|close|fixes|fix|done|finishes|resolves)\s+synth:(\d+)", re.I)
MENTION_RE = re.compile(r"\bsynth:(\d+)", re.I)


def parse_commit_refs(subject, body=""):
    """Return {task id: closes?} for synth:ID mentions in a commit message."""
    text = subject + "\n" + body
    refs = {int(i): False for i in MENTION_RE.findall(text)}
    for i in CLOSE_RE.findall(text):
        refs[int(i)] = True
    return refs


def git_mentions(cwd):
    """Commits that mention synth:ID. Returns [(sha, subject, {id: closes})]."""
    rc, out = git_run(["log", "--all", "-n", "300", "-i", "-E", "--grep", r"synth:[0-9]+",
                       "--format=%h%x1f%s%x1f%b%x1e"], cwd, timeout=15)
    rows = []
    for rec in out.split("\x1e") if rc == 0 else []:
        parts = rec.strip("\n").split("\x1f")
        if len(parts) >= 2 and parts[0].strip():
            refs = parse_commit_refs(parts[1], parts[2] if len(parts) > 2 else "")
            if refs:
                rows.append((parts[0].strip(), parts[1], refs))
    return rows


def git_probe(job):
    """Check one linked branch. job: {id, repo, branch, base}. Returns a state string."""
    repo, branch = job["repo"], job["branch"]
    tip = git_rev(repo, "refs/heads/" + branch)
    if not tip:
        return "missing"
    if tip == job.get("base"):
        return "active"
    default = git_default_branch(repo)
    if branch == default:
        return "active"
    for ref in (default, "origin/" + default):
        if git_rev(repo, ref) and git_is_ancestor(repo, tip, ref):
            return "merged"
    return "active"


def gh_run(args, cwd, timeout=25):
    """Run the GitHub CLI. Returns (returncode, text). 127 when gh is missing."""
    if not shutil.which("gh"):
        return 127, "the GitHub CLI (gh) is not installed"
    try:
        r = subprocess.run(["gh"] + list(args), cwd=cwd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=dict(os.environ, GH_PROMPT_DISABLED="1", NO_COLOR="1"))
    except (OSError, subprocess.SubprocessError):
        return 127, "could not run gh"
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout))


def parse_gh_items(text, kind):
    """Normalize gh --json output. Returns [{number, title, url, state, kind, labels, draft}]."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict) or "number" not in d:
            continue
        labels = [l.get("name", "") if isinstance(l, dict) else str(l) for l in d.get("labels") or []]
        out.append({"number": int(d["number"]), "title": str(d.get("title", "")), "url": str(d.get("url", "")),
                    "state": str(d.get("state", "OPEN")).lower(), "kind": kind, "labels": [x for x in labels if x],
                    "draft": bool(d.get("isDraft", False))})
    return out


def gh_list(cwd, kind, mine=True, state="open", limit=100):
    """List issues or pull requests of the repo in cwd. Returns (items, error text)."""
    cmd = "issue" if kind == "issue" else "pr"
    fields = "number,title,url,state,labels" + (",isDraft" if kind == "pr" else "")
    args = [cmd, "list", "--state", state, "--limit", str(limit), "--json", fields]
    if mine:
        args += ["--assignee", "@me"] if kind == "issue" else ["--author", "@me"]
    rc, out = gh_run(args, cwd)
    if rc != 0:
        return [], out.strip().split("\n")[-1][:100]
    return parse_gh_items(out, kind), ""


def gh_done_state(kind, state):
    """True when a linked issue or PR counts as finished."""
    return state == "merged" if kind == "pr" else state in ("closed", "merged")


try:
    import zoneinfo
except ImportError:
    zoneinfo = None

ICS_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def ics_unfold(text):
    out = []
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ln[:1] in (" ", "\t") and out:
            out[-1] += ln[1:]
        else:
            out.append(ln)
    return out


def ics_unescape(v):
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def ics_prop(line):
    """Split 'NAME;P=V:value' into (name, params dict, value)."""
    if ":" not in line:
        return None
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def ics_datetime(value, params):
    """Return (naive local datetime, all_day) or (None, False)."""
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
            return dt.datetime.strptime(value[:8], "%Y%m%d"), True
        if value.endswith("Z"):
            d = dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
            return d.astimezone().replace(tzinfo=None), False
        d = dt.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None, False
    tzid = params.get("TZID")
    if tzid and zoneinfo is not None:
        try:
            return d.replace(tzinfo=zoneinfo.ZoneInfo(tzid)).astimezone().replace(tzinfo=None), False
        except (KeyError, ValueError, OSError):
            pass
    return d, False


def ics_duration(v):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def parse_ics(text):
    """Parse VEVENTs. Returns a list of event dicts (recurrence rules are kept, not expanded)."""
    events, cur = [], None
    for line in ics_unfold(text):
        up = line.strip().upper()
        if up == "BEGIN:VEVENT":
            cur = {"uid": "", "summary": "", "location": "", "start": None, "end": None, "all_day": False,
                   "rrule": None, "exdates": set(), "rid": None, "dur": None, "status": ""}
            continue
        if up == "END:VEVENT":
            if cur and cur["start"] is not None and cur["status"] != "CANCELLED":
                if cur["end"] is None:
                    cur["end"] = cur["start"] + (cur["dur"] or (dt.timedelta(days=1) if cur["all_day"] else dt.timedelta()))
                events.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        pr = ics_prop(line)
        if not pr:
            continue
        name, params, value = pr
        if name == "UID":
            cur["uid"] = value.strip()
        elif name == "SUMMARY":
            cur["summary"] = ics_unescape(value).strip()
        elif name == "LOCATION":
            cur["location"] = ics_unescape(value).strip()
        elif name == "STATUS":
            cur["status"] = value.strip().upper()
        elif name == "DTSTART":
            cur["start"], cur["all_day"] = ics_datetime(value, params)
        elif name == "DTEND":
            cur["end"], _ = ics_datetime(value, params)
        elif name == "DURATION":
            cur["dur"] = ics_duration(value)
        elif name == "RECURRENCE-ID":
            cur["rid"], _ = ics_datetime(value, params)
        elif name == "EXDATE":
            for v in value.split(","):
                d, _ = ics_datetime(v, params)
                if d is not None:
                    cur["exdates"].add(d)
        elif name == "RRULE":
            rule = {}
            for part in value.split(";"):
                k, _, v = part.partition("=")
                rule[k.upper()] = v
            cur["rrule"] = rule
    return events


def _nth_weekday(year, month, weekday, n):
    """n-th weekday of a month (n=-1 is the last). Returns a date or None."""
    if n > 0:
        first = dt.date(year, month, 1)
        d = first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
        return d if d.month == month else None
    last = add_months(dt.date(year, month, 1), 1) - dt.timedelta(days=1)
    d = last - dt.timedelta(days=(last.weekday() - weekday) % 7 + 7 * (-n - 1))
    return d if d.month == month else None


def rrule_dates(start, rule, limit):
    """Yield occurrence start datetimes of a recurrence rule until limit (a datetime)."""
    freq = rule.get("FREQ", "")
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        until, _ = ics_datetime(rule["UNTIL"], {})
        if until is not None and len(rule["UNTIL"]) == 8:
            until += dt.timedelta(days=1) - dt.timedelta(seconds=1)
    byday = []
    for tok in rule.get("BYDAY", "").split(","):
        m = re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", tok.strip())
        if m:
            byday.append((int(m.group(1)) if m.group(1) else 0, ICS_DAYS[m.group(2)]))
    bymd = [int(x) for x in rule.get("BYMONTHDAY", "").split(",") if re.fullmatch(r"-?\d+", x.strip())]
    tm = start.time()
    emitted = 0
    for k in range(0, 6000):
        cands = []
        if freq == "DAILY":
            cands = [start.date() + dt.timedelta(days=k * interval)]
        elif freq == "WEEKLY":
            monday = start.date() - dt.timedelta(days=start.weekday()) + dt.timedelta(weeks=k * interval)
            days = sorted({d for _, d in byday}) or [start.weekday()]
            cands = [monday + dt.timedelta(days=d) for d in days]
        elif freq == "MONTHLY":
            base = add_months(start.date().replace(day=1), k * interval)
            if byday:
                cands = [x for x in (_nth_weekday(base.year, base.month, wd, n or 1) for n, wd in byday) if x]
            else:
                for md in bymd or [start.day]:
                    last = add_months(base, 1) - dt.timedelta(days=1)
                    day = md if md > 0 else last.day + md + 1
                    if 1 <= day <= last.day:
                        cands.append(base.replace(day=day))
            cands.sort()
        elif freq == "YEARLY":
            try:
                cands = [start.date().replace(year=start.year + k * interval)]
            except ValueError:
                cands = []
        else:
            return
        for d in cands:
            occ = dt.datetime.combine(d, tm)
            if occ < start:
                continue
            if until is not None and occ > until:
                return
            if occ > limit:
                return
            yield occ
            emitted += 1
            if count is not None and emitted >= count:
                return


def expand_events(events, d0, d1):
    """Occurrences overlapping [d0, d1] (dates), sorted. Each: summary start end all_day location uid."""
    lo = dt.datetime.combine(d0, dt.time())
    hi = dt.datetime.combine(d1, dt.time()) + dt.timedelta(days=1)
    overrides = {(e["uid"], e["rid"]) for e in events if e["rid"] is not None}
    out = []

    def add(e, start):
        end = start + (e["end"] - e["start"])
        if end > lo and start < hi:
            out.append({"summary": e["summary"] or "(no title)", "start": start, "end": end, "all_day": e["all_day"],
                        "location": e["location"], "uid": e["uid"]})

    for e in events:
        if e["rrule"] and e["rid"] is None:
            for occ in rrule_dates(e["start"], e["rrule"], hi):
                if occ in e["exdates"] or (e["uid"], occ) in overrides:
                    continue
                add(e, occ)
        else:
            add(e, e["start"])
    out.sort(key=lambda o: (o["start"], o["summary"]))
    return out


def next_event(occ, now):
    """(ongoing occurrence or None, next timed occurrence or None) at time now."""
    ongoing = nxt = None
    for o in occ:
        if o["all_day"]:
            continue
        if o["start"] <= now < o["end"]:
            ongoing = ongoing or o
        elif o["start"] > now:
            nxt = o
            break
    return ongoing, nxt


ENERGY_LEVELS = ["low", "medium", "high"]
LOW_TAGS = {"quick", "easy", "admin", "chore", "low-energy"}
HIGH_TAGS = {"deep", "focus", "hard", "creative", "high-energy"}


def whatnow_rank(store, td, minutes=None, energy="medium", median=1.0, project=""):
    """Rank open tasks for right now. Returns [(score, task, reasons)] best first.

    minutes is the time available (None for unknown), energy is low, medium or high,
    median scales estimates by how long your tasks really take."""
    waiting = collections.Counter()
    open_parents = set()
    for t in store.tasks:
        if t["done"]:
            continue
        for d in t.get("deps", []):
            waiting[d] += 1
        if t["parent"] is not None:
            open_parents.add(t["parent"])
    out = []
    for t in store.tasks:
        if t["done"] or is_snoozed(t, td) or blockers(store, t) or t["id"] in open_parents:
            continue
        est = t.get("est", 0) or 0
        adj = est * (median if median and est else 1.0)
        if minutes is not None and adj > minutes * 60 * 1.1:
            continue
        score, why = 0.0, []
        if t["prio"]:
            score += 2.0 * t["prio"]
            why.append({1: "low priority", 2: "medium priority", 3: "high priority"}.get(t["prio"], "priority"))
        if t["due"]:
            days = (dt.date.fromisoformat(t["due"]) - td).days
            if days < 0:
                score += 6 + min(4.0, -days * 0.4)
                why.append("overdue %dd" % -days)
            elif days == 0:
                score += 5
                why.append("due today")
            elif days == 1:
                score += 3
                why.append("due tomorrow")
            elif days <= 7:
                score += 1.5
                why.append("due in %dd" % days)
        n = waiting.get(t["id"], 0)
        if n:
            score += 1.5 * min(3, n)
            why.append("unblocks %d" % n)
        try:
            age = (td - dt.date.fromisoformat(t["created"][:10])).days
        except ValueError:
            age = 0
        if age >= 30:
            score += 0.5
        if minutes is not None and est:
            ratio = min(1.1, adj / (minutes * 60.0))
            score += 1.5 * ratio
            why.append("fits in %s" % fmt_duration(int(adj)))
        elif est:
            why.append("about %s" % fmt_duration(int(adj)))
        tags = set(t["tags"])
        short = bool(est) and adj <= 1200
        if energy == "low":
            if short or tags & LOW_TAGS:
                score += 2.0
                why.append("easy on low energy")
            if t["prio"] >= 3 and not short:
                score -= 1.0
            if tags & HIGH_TAGS:
                score -= 2.0
        elif energy == "high":
            if tags & HIGH_TAGS or (t["prio"] >= 2 and (adj >= 1800 or not est)):
                score += 2.0
                why.append("worth your best energy")
            if tags & LOW_TAGS:
                score -= 1.0
        if project and t["project"] == project:
            score += 1.0
            why.append("same project as your current work")
        out.append((score, t, why))
    out.sort(key=lambda r: (-r[0], r[1]["due"] or "9999", -r[1]["prio"], r[1]["created"]))
    return out


def dep_graph(store, show_done=False):
    """Layered layout of the dependency graph. Prerequisites sit left of what they unblock.

    Returns {"comps": [{"nodes": {key: {layer, y, dummy}}, "edges": [(a, b)]}], "crit": set of ids,
    "crit_edges": set of (a, b), "dependents": {id: transitive count}, "bott": id or None, "layers": n,
    "crit_secs": seconds, "height": rows}. Real nodes are task ids, long edges pass through dummy keys."""
    tasks = {t["id"]: t for t in store.tasks}
    inc = set()
    for t in store.tasks:
        if t["done"]:
            continue
        ds = [d for d in t.get("deps", []) if d in tasks and (show_done or not tasks[d]["done"])]
        if ds:
            inc.add(t["id"])
            inc.update(ds)
    res = {"comps": [], "crit": set(), "crit_edges": set(), "dependents": {}, "bott": None, "layers": 0,
           "crit_secs": 0, "height": 0}
    if not inc:
        return res
    order = [t["id"] for t in store.tasks if t["id"] in inc]
    preds = {i: [d for d in tasks[i].get("deps", []) if d in inc and d != i] for i in order}
    succs = {i: [] for i in order}
    for b, ps in preds.items():
        for a in ps:
            succs[a].append(b)
    layer, left = {}, set(order)
    indeg = {i: len(preds[i]) for i in order}
    queue = [i for i in order if indeg[i] == 0]
    while queue:
        i = queue.pop(0)
        layer[i] = 1 + max([layer[p] for p in preds[i] if p in layer] or [-1])
        left.discard(i)
        for b in succs[i]:
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)
    for i in left:
        layer[i] = 0
    edges = [(a, b) for b in order for a in preds[b] if layer[a] < layer[b]]
    # critical path: longest chain by estimate (30 minutes when unknown)
    w = {i: (tasks[i].get("est") or 1800) for i in order}
    best, prev = {}, {}
    for i in sorted(order, key=lambda x: layer[x]):
        cand = [(best[p], p) for p in preds[i] if p in best and layer[p] < layer[i]]
        top = max(cand) if cand else (0, None)
        best[i] = top[0] + w[i]
        prev[i] = top[1]
    end = max(order, key=lambda x: best[x])
    chain = []
    cur = end
    while cur is not None:
        chain.append(cur)
        cur = prev[cur]
    res["crit"] = set(chain)
    res["crit_edges"] = {(chain[k + 1], chain[k]) for k in range(len(chain) - 1)}
    res["crit_secs"] = best[end]
    # transitive dependents
    for i in order:
        seen, stack = set(), list(succs[i])
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack.extend(succs[x])
        res["dependents"][i] = len(seen)
    top_n = max(res["dependents"].values())
    if top_n > 0:
        res["bott"] = max(order, key=lambda x: (res["dependents"][x], -layer[x]))
    # components
    parent = {i: i for i in order}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in edges:
        parent[find(a)] = find(b)
    groups = collections.OrderedDict()
    for i in order:
        groups.setdefault(find(i), []).append(i)
    y_base, layers_max = 0, 0
    for members in sorted(groups.values(), key=lambda m: -len(m)):
        ms = set(members)
        nodes = {i: {"layer": layer[i], "y": 0, "dummy": False} for i in members}
        cedges = []
        for a, b in edges:
            if a not in ms:
                continue
            chain_keys = [a] + [("v", a, b, l) for l in range(layer[a] + 1, layer[b])] + [b]
            for k in chain_keys[1:-1]:
                nodes[k] = {"layer": k[3], "y": 0, "dummy": True}
            for k in range(len(chain_keys) - 1):
                cedges.append((chain_keys[k], chain_keys[k + 1], (a, b)))
        nl = max(n["layer"] for n in nodes.values()) + 1
        lays = [[] for _ in range(nl)]
        idx = {i: n for n, i in enumerate(order)}
        for k in sorted(nodes, key=lambda k: (idx[k] if not isinstance(k, tuple) else idx[k[1]] + 0.5)):
            lays[nodes[k]["layer"]].append(k)
        pin = collections.defaultdict(list)
        pout = collections.defaultdict(list)
        for a, b, _o in cedges:
            pin[b].append(a)
            pout[a].append(b)
        pos = {k: n for lay in lays for n, k in enumerate(lay)}
        for sweep in range(4):
            rng = range(1, nl) if sweep % 2 == 0 else range(nl - 2, -1, -1)
            for l in rng:
                nb = pin if sweep % 2 == 0 else pout
                lays[l].sort(key=lambda k: (sum(pos[x] for x in nb[k]) / float(len(nb[k])) if nb[k] else pos[k], pos[k]))
                for n, k in enumerate(lays[l]):
                    pos[k] = n
        for l in range(nl):
            last = -2
            for k in lays[l]:
                want = [nodes[x]["y"] for x in pin[k]] if l > 0 else []
                y = int(round(sum(want) / float(len(want)))) if want else last + 2
                if y % 2:
                    y += 1
                y = max(y, last + 2)
                nodes[k]["y"] = y
                last = y
        h = max(n["y"] for n in nodes.values()) + 1
        for n in nodes.values():
            n["y"] += y_base
        res["comps"].append({"nodes": nodes, "edges": cedges, "y0": y_base, "height": h})
        y_base += h + 2
        layers_max = max(layers_max, nl)
    res["layers"] = layers_max
    res["height"] = y_base
    return res


GRAPH_BITS = {"L": 1, "R": 2, "U": 4, "D": 8}
GRAPH_CHARS = {1: "─", 2: "─", 3: "─", 4: "│", 8: "│", 12: "│", 10: "┌", 9: "┐", 6: "└", 5: "┘",
               11: "┬", 7: "┴", 14: "├", 13: "┤", 15: "┼"}
GRAPH_ASCII = {k: ("-" if k in (1, 2, 3) else "|" if k in (4, 8, 12) else "+") for k in GRAPH_CHARS}


def graph_route(cells, x0, y0, x1, y1, xm, crit):
    """Draw an orthogonal edge into a cell map: right to xm, vertical to y1, right to x1."""
    pts = [(x0, y0), (xm, y0), (xm, y1), (x1, y1)]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx = (bx > ax) - (bx < ax)
        dy = (by > ay) - (by < ay)
        x, y = ax, ay
        while (x, y) != (bx, by):
            nx, ny = x + dx, y + dy
            for (cx, cy, bit) in ((x, y, GRAPH_BITS["R"] if dx > 0 else GRAPH_BITS["L"] if dx < 0 else GRAPH_BITS["D"] if dy > 0 else GRAPH_BITS["U"]),
                                  (nx, ny, GRAPH_BITS["L"] if dx > 0 else GRAPH_BITS["R"] if dx < 0 else GRAPH_BITS["U"] if dy > 0 else GRAPH_BITS["D"])):
                m, c = cells.get((cx, cy), (0, False))
                cells[(cx, cy)] = (m | bit, c or crit)
            x, y = nx, ny


def data_versions(directory, fname, limit=200):
    """Commits that touched the data file. Returns [{sha, when, subject}], newest first."""
    rc, out = git_run(["log", "-n", str(limit), "--format=%H%x1f%aI%x1f%s", "--", fname], directory, timeout=20)
    rows = []
    for ln in out.split("\n") if rc == 0 else []:
        parts = ln.split("\x1f")
        if len(parts) == 3 and parts[0]:
            rows.append({"sha": parts[0], "when": parts[1], "subject": parts[2]})
    return rows


def data_at(directory, sha, fname):
    """The data file as it was in a commit, or None."""
    rc, out = git_run(["show", "%s:%s" % (sha, fname)], directory, timeout=20)
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def filled_tasks(data):
    """Tasks of a stored version with every field present."""
    out = []
    for raw in data.get("tasks", []):
        t = blank_task(raw.get("id", 0), "")
        t.update(raw)
        out.append(t)
    return out


def version_diff(old_tasks, store):
    """Compare an old version with the live store.

    Returns {"deleted": [old task], "changed": [(old task, now task, [(kind, text)])], "added": [now task]}."""
    now = {t["id"]: t for t in store.tasks}
    then = {t["id"]: t for t in old_tasks}
    deleted = [t for t in old_tasks if t["id"] not in now]
    added = [t for t in store.tasks if t["id"] not in then]
    changed = []
    for t in old_tasks:
        cur = now.get(t["id"])
        if cur is None:
            continue
        d = diff_sig(task_sig(t), cur)
        if d:
            changed.append((t, cur, d))
    return {"deleted": deleted, "changed": changed, "added": added}


RESTORE_FIELDS = ["title", "done", "done_at", "prio", "due", "tags", "project", "notes", "repeat", "est", "deps", "snooze"]


def change_summary(lines):
    """Commit message for a batch of change lines."""
    lines = [x for x in lines if x]
    if not lines:
        return "synth: update"
    if len(lines) == 1:
        return "synth: " + lines[0]
    return "synth: %d changes\n\n%s" % (len(lines), "\n".join("- " + x for x in lines[:40]))


# ---------------------------------------------------------------------------
# IRC client (protocol layer, no curses in here)
# ---------------------------------------------------------------------------

IRC_MAX_LINES = 500
IRC_CAPS = ("server-time", "multi-prefix", "sasl")
IRC_SERVER = "*"  # buffer key of the server buffer


def irc_parse(line):
    """Parse one raw IRC line into a dict: tags, nick, user, host, prefix, cmd, params."""
    out = {"tags": {}, "nick": "", "user": "", "host": "", "prefix": "", "cmd": "", "params": []}
    line = line.rstrip("\r\n")
    if line.startswith("@"):
        raw, _, line = line.partition(" ")
        for item in raw[1:].split(";"):
            k, _, v = item.partition("=")
            out["tags"][k] = (v.replace("\\:", ";").replace("\\s", " ").replace("\\\\", "\\")
                              .replace("\\r", "\r").replace("\\n", "\n"))
    line = line.lstrip(" ")
    if line.startswith(":"):
        pre, _, line = line.partition(" ")
        pre = pre[1:]
        out["prefix"] = pre
        nick, _, rest = pre.partition("!")
        user, _, host = rest.partition("@")
        if not rest and "@" in pre:
            nick, _, host = pre.partition("@")
        out["nick"], out["user"], out["host"] = nick, user, host
    line = line.lstrip(" ")
    head, sep, trailing = line.partition(" :")
    parts = head.split()
    if not parts and not sep:
        return out
    out["cmd"] = parts[0].upper() if parts else ""
    out["params"] = parts[1:] + ([trailing] if sep else [])
    return out


def irc_clean(text):
    """Remove characters that would let user text break out of a protocol line."""
    return text.replace("\r", " ").replace("\n", " ").replace("\0", "")


def irc_sasl_plain(account, password):
    """AUTHENTICATE payload chunks for SASL PLAIN (400 characters each, a final + if exact)."""
    raw = ("\0%s\0%s" % (account, password)).encode("utf-8")
    b = base64.b64encode(raw).decode("ascii")
    chunks = [b[i:i + 400] for i in range(0, len(b), 400)] or ["+"]
    if len(b) % 400 == 0 and b:
        chunks.append("+")
    return chunks


def irc_split(text, limit=400):
    """Split text into pieces of at most limit bytes, preferring spaces, never inside a character."""
    out = []
    text = irc_clean(text)
    while len(text.encode("utf-8")) > limit:
        cut = len(text)
        while len(text[:cut].encode("utf-8")) > limit:
            cut -= 1
        sp = text.rfind(" ", 0, cut)
        if sp > cut // 2:
            cut = sp
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text or not out:
        out.append(text)
    return [p.strip() for p in out if p.strip()]


def irc_mentioned(text, nick):
    if not nick:
        return False
    return re.search(r"(?<![\w\-\[\]\\`^{}|])" + re.escape(nick) + r"(?![\w\-\[\]\\`^{}|])", text, re.I) is not None


def irc_color_index(nick, n):
    h = 0
    for ch in nick.lower():
        h = (h * 31 + ord(ch)) & 0xFFFFFF
    return h % max(1, n)


def irc_strip_format(text):
    """Remove mIRC colour and style codes."""
    text = re.sub(r"\x03(\d{1,2}(,\d{1,2})?)?", "", text)
    text = re.sub(r"\x04[0-9A-Fa-f]{0,6}(,[0-9A-Fa-f]{6})?", "", text)
    return re.sub(r"[\x02\x0f\x11\x16\x1d\x1e\x1f]", "", text)


def irc_server_time(tag):
    try:
        d = dt.datetime.strptime(tag[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        return d.timestamp()
    except (ValueError, TypeError):
        return None


def irc_env_name(name):
    return "SYNTH_IRC_PASSWORD_" + re.sub(r"[^A-Za-z0-9]", "_", name or "").upper()


class IrcBuffer:
    def __init__(self, name, kind):
        self.name, self.kind = name, kind  # kind: server, channel, query
        self.lines = collections.deque(maxlen=IRC_MAX_LINES)
        self.unread = 0
        self.mentions = 0
        self.topic = ""
        self.nicks = {}
        self.joined = False
        self.want = False


class IrcClient:
    """One connection. A reader thread fills buffers; the UI reads them under client.lock."""

    def __init__(self, cfg, password=None, opener=None):
        self.cfg = dict(cfg)
        self.name = self.cfg.get("name") or self.cfg.get("host") or "irc"
        self.password = password
        self.lock = threading.RLock()
        self.send_lock = threading.Lock()
        self.buffers = collections.OrderedDict()
        self.status = "offline"
        self.nick = self.cfg.get("nick") or "synth"
        self.rev = 0
        self.alerts = collections.deque(maxlen=50)
        self.viewing = None
        self.sock = None
        self.thread = None
        self.stop_ev = threading.Event()
        self.opener = opener
        self.prefix_modes, self.prefix_chars = "ov", "@+"
        self.chantypes = "#&"
        self.chanmodes = ["beI", "k", "l", "imnpst"]
        self.caps_ls = set()
        self.sasl_state = None
        self.autojoined = False
        self.reply_ctx = IRC_SERVER
        self.last_rx = time.time()
        self.buf(IRC_SERVER, "server")

    # ----- buffers -----

    def buf(self, name, kind=None):
        key = IRC_SERVER if name == IRC_SERVER else name.lower()
        with self.lock:
            b = self.buffers.get(key)
            if b is None:
                if kind is None:
                    kind = "channel" if name[:1] in self.chantypes else "query"
                b = self.buffers[key] = IrcBuffer(name, kind)
                if key != IRC_SERVER:
                    self.buffers.move_to_end(key)
            return b

    def add(self, key, kind, nick, text, ts=None, hl=False):
        with self.lock:
            b = self.buf(key)
            b.lines.append((ts or time.time(), kind, nick, text))
            watching = self.viewing == (IRC_SERVER if key == IRC_SERVER else key.lower())
            if not watching and kind in ("msg", "action", "notice"):
                b.unread += 1
                if hl:
                    b.mentions += 1
            if hl and not watching:
                self.alerts.append((self.name, b.name, nick, text))
            self.rev += 1

    def info(self, text, key=IRC_SERVER, kind="info"):
        self.add(key, kind, "", text)

    def view(self, key):
        with self.lock:
            self.viewing = key
            b = self.buffers.get(key)
            if b:
                b.unread = b.mentions = 0
            self.rev += 1

    def totals(self):
        with self.lock:
            return (sum(b.unread for b in self.buffers.values()),
                    sum(b.mentions for b in self.buffers.values()))

    # ----- connection -----

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="irc-" + self.name)
        self.thread.start()

    def stop(self, message="synth"):
        self.stop_ev.set()
        with contextlib.suppress(Exception):
            self.send("QUIT :" + irc_clean(message))
        s = self.sock
        if s is not None:
            with contextlib.suppress(Exception):
                time.sleep(0.15)
                s.close()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(1.5)
        self.status = "offline"
        self.rev += 1

    def _open(self):
        if self.opener:
            return self.opener(self.cfg)
        host = self.cfg.get("host", "")
        port = int(self.cfg.get("port") or (6697 if self.cfg.get("tls", True) else 6667))
        raw = socket.create_connection((host, port), timeout=20)
        if not self.cfg.get("tls", True):
            return raw
        if ssl is None:
            raise OSError("this Python has no ssl module")
        ctx = ssl.create_default_context()
        if not self.cfg.get("verify", True):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx.wrap_socket(raw, server_hostname=host)

    def _run(self):
        delay = 5
        while not self.stop_ev.is_set():
            started = time.time()
            try:
                self._session()
            except Exception as e:  # network errors, TLS errors, anything
                self.info("connection failed: %s" % (str(e) or e.__class__.__name__), kind="error")
            self.status = "offline"
            self.sock = None
            with self.lock:
                for b in self.buffers.values():
                    b.joined = False
                self.rev += 1
            if self.stop_ev.is_set() or not self.cfg.get("reconnect", True):
                break
            delay = 5 if time.time() - started > 60 else min(120, delay * 2)
            self.info("reconnecting in %ds" % delay)
            if self.stop_ev.wait(delay):
                break

    def _creds_ok(self):
        if self.cfg.get("auth", "sasl") == "none" or not self.password:
            return False
        if not self.cfg.get("tls", True) and not self.cfg.get("plain_auth"):
            return False
        return True

    def _session(self):
        self.status = "connecting"
        self.sasl_state = None
        self.autojoined = False
        self.caps_ls = set()
        self.nick = self.cfg.get("nick") or "synth"
        self.rev += 1
        self.info("connecting to %s" % self.cfg.get("host", ""))
        sock = self._open()
        sock.settimeout(30)
        self.sock = sock
        self.last_rx = time.time()
        self.status = "registering"
        if self.cfg.get("auth", "sasl") != "none" and self.password and not self._creds_ok():
            self.info("password not sent: this network is not using TLS", kind="error")
        self.send("CAP LS 302")
        self.send("NICK " + self.nick)
        user = re.sub(r"[^\w\-.]", "", self.cfg.get("user") or self.nick) or "synth"
        real = irc_clean(self.cfg.get("realname") or "synth")
        self.send("USER %s 0 * :%s" % (user, real))
        data = b""
        while not self.stop_ev.is_set():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                idle = time.time() - self.last_rx
                if idle > 300:
                    raise OSError("ping timeout")
                if idle > 120:
                    self.send("PING :synth")
                continue
            if not chunk:
                self.info("disconnected")
                return
            self.last_rx = time.time()
            data += chunk
            while b"\n" in data:
                raw, _, data = data.partition(b"\n")
                line = raw.decode("utf-8", "replace").rstrip("\r")
                if line:
                    try:
                        self.handle(line)
                    except Exception as e:
                        self.info("protocol error: %s" % e, kind="error")
            if len(data) > 65536:
                raise OSError("line too long")

    # ----- sending -----

    def send(self, line):
        line = irc_clean(line)
        raw = line.encode("utf-8")[:510] + b"\r\n"
        s = self.sock
        if s is None:
            return False
        try:
            with self.send_lock:
                s.sendall(raw)
            return True
        except OSError:
            return False

    def privmsg(self, key, text, action=False):
        """Send text to a buffer's target, splitting long text; echoes into the buffer."""
        b = self.buffers.get(key)
        if b is None or b.kind == "server":
            return "not in a channel or query; use /join or /msg"
        if self.status != "online":
            return "not connected"
        for piece in irc_split(text):
            if action:
                self.send("PRIVMSG %s :\x01ACTION %s\x01" % (b.name, piece))
                self.add(key, "action", self.nick, piece)
            else:
                self.send("PRIVMSG %s :%s" % (b.name, piece))
                self.add(key, "own", self.nick, piece)
        return None

    def command(self, key, text):
        """Run a protocol level slash command. Returns (error or None, buffer key to switch to or None)."""
        cmd, _, rest = text.lstrip("/").partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        if cmd in ("join", "j"):
            if not rest:
                return "usage: /join #channel [key]", None
            first = rest.split()[0]
            if first[:1] not in self.chantypes:
                rest = "#" + rest
                first = rest.split()[0]
            self.send("JOIN " + rest)
            b = self.buf(first, "channel")
            b.want = True
            return None, first.lower()
        if cmd in ("part", "leave"):
            b = self.buffers.get(key)
            if not b or b.kind != "channel":
                return "not in a channel", None
            b.want = False
            self.send("PART %s :%s" % (b.name, irc_clean(rest or "bye")))
            return None, None
        if cmd in ("msg", "m", "query", "q"):
            target, _, body = rest.partition(" ")
            if not target:
                return "usage: /msg nick text", None
            b = self.buf(target)
            if body.strip():
                err = self.privmsg(b.name.lower(), body.strip())
                if err:
                    return err, None
            return None, b.name.lower()
        if cmd in ("me", "action"):
            return self.privmsg(key, rest, action=True), None
        if cmd == "nick":
            if not rest:
                return "usage: /nick newnick", None
            self.send("NICK " + rest.split()[0])
            return None, None
        if cmd == "topic":
            b = self.buffers.get(key)
            if not b or b.kind != "channel":
                return "not in a channel", None
            self.send("TOPIC %s :%s" % (b.name, rest) if rest else "TOPIC " + b.name)
            return None, None
        if cmd == "names":
            b = self.buffers.get(key)
            if b and b.kind == "channel":
                self.send("NAMES " + b.name)
            return None, None
        if cmd == "whois":
            if not rest:
                return "usage: /whois nick", None
            self.reply_ctx = key
            self.send("WHOIS " + rest.split()[0])
            return None, None
        if cmd in ("raw", "quote"):
            self.send(rest)
            return None, None
        if cmd in ("ns", "nickserv", "cs", "chanserv", "hs", "bs", "memoserv", "ms"):
            svc = {"ns": "NickServ", "cs": "ChanServ", "hs": "HostServ", "bs": "BotServ", "ms": "MemoServ", "memoserv": "MemoServ"}.get(cmd, cmd.capitalize())
            if not rest:
                return "usage: /%s command" % cmd, None
            self.send("PRIVMSG %s :%s" % (svc, rest))  # never echoed, it may hold a password
            self.info("sent to %s" % svc)
            return None, IRC_SERVER
        if cmd == "identify":
            if not rest:
                return "usage: /identify password", None
            self.send("PRIVMSG NickServ :IDENTIFY %s" % rest)
            self.info("sent to NickServ")
            return None, IRC_SERVER
        if cmd == "away":
            self.send("AWAY :" + rest if rest else "AWAY")
            return None, None
        return "unknown command: /" + cmd, None

    # ----- receiving -----

    def _autojoin(self):
        if self.autojoined or self.status != "online":
            return
        self.autojoined = True
        names = []
        for c in self.cfg.get("channels") or []:
            c = str(c).strip()
            if c:
                names.append(c)
        with self.lock:
            for b in self.buffers.values():
                if b.kind == "channel" and b.want and not any(n.split()[0].lower() == b.name.lower() for n in names):
                    names.append(b.name)
        for n in names:
            if n[:1] not in self.chantypes:
                n = "#" + n
            self.send("JOIN " + n)
            self.buf(n.split()[0], "channel").want = True

    def _finish_caps(self):
        self.send("CAP END")

    def handle(self, line):
        m = irc_parse(line)
        cmd, p = m["cmd"], m["params"]
        ts = irc_server_time(m["tags"].get("time", "")) if "time" in m["tags"] else None
        me = self.nick
        if cmd == "PING":
            self.send("PONG :" + (p[0] if p else ""))
        elif cmd == "CAP":
            self._cap(p)
        elif cmd == "AUTHENTICATE":
            if p and p[0] == "+" and self.sasl_state == "auth":
                acct = self.cfg.get("account") or self.cfg.get("nick") or self.nick
                for chunk in irc_sasl_plain(acct, self.password or ""):
                    self.send("AUTHENTICATE " + chunk)
        elif cmd == "900":
            self.info("logged in as %s" % (p[2] if len(p) > 2 else "?"))
        elif cmd == "903":
            self.sasl_state = "done"
            self.info("SASL login ok")
            self._finish_caps()
        elif cmd in ("902", "904", "905", "906", "907"):
            self.sasl_state = "failed"
            self.info("SASL login failed (%s). Check your account name and password." % cmd, kind="error")
            self._finish_caps()
        elif cmd == "001":
            self.status = "online"
            if p:
                self.nick = p[0]
            self.info(p[-1] if p else "connected")
            self.rev += 1
            auth = self.cfg.get("auth", "sasl")
            need_ns = auth == "nickserv" or (auth == "sasl" and self.sasl_state is None)
            if need_ns and self._creds_ok():
                acct = self.cfg.get("account") or self.nick
                self.send("PRIVMSG NickServ :IDENTIFY %s %s" % (acct, self.password))
                self.info("identifying with NickServ")
                threading.Timer(3.0, self._autojoin).start()
            else:
                self._autojoin()
        elif cmd == "005":
            for tok in p[1:-1]:
                k, _, v = tok.partition("=")
                if k == "PREFIX":
                    mm = re.match(r"\(([^)]*)\)(.*)", v)
                    if mm and len(mm.group(1)) == len(mm.group(2)):
                        self.prefix_modes, self.prefix_chars = mm.group(1), mm.group(2)
                elif k == "CHANTYPES" and v:
                    self.chantypes = v
                elif k == "CHANMODES":
                    self.chanmodes = (v.split(",") + ["", "", "", ""])[:4]
        elif cmd == "433" and self.status != "online":
            self.nick = self.nick + "_"
            self.send("NICK " + self.nick)
        elif cmd == "353" and len(p) >= 4:
            b = self.buf(p[2], "channel")
            with self.lock:
                for n in p[3].split():
                    pre = ""
                    while n and n[0] in self.prefix_chars:
                        pre += n[0]
                        n = n[1:]
                    if n:
                        b.nicks[n] = pre[:1]
                self.rev += 1
        elif cmd == "332" and len(p) >= 3:
            b = self.buf(p[1], "channel")
            b.topic = p[2]
            self.add(p[1].lower(), "info", "", "topic: " + irc_strip_format(p[2]))
        elif cmd == "TOPIC" and p:
            b = self.buf(p[0], "channel")
            b.topic = p[1] if len(p) > 1 else ""
            self.add(p[0].lower(), "info", "", "%s set the topic: %s" % (m["nick"], irc_strip_format(b.topic)), ts)
        elif cmd == "JOIN" and p:
            chan = p[0]
            b = self.buf(chan, "channel")
            if m["nick"].lower() == me.lower():
                b.joined, b.want = True, True
                b.nicks = {}
                self.add(chan.lower(), "join", m["nick"], "you joined " + chan, ts)
            else:
                b.nicks[m["nick"]] = ""
                self.add(chan.lower(), "join", m["nick"], "%s joined" % m["nick"], ts)
        elif cmd == "PART" and p:
            b = self.buf(p[0], "channel")
            if m["nick"].lower() == me.lower():
                b.joined = False
                b.nicks = {}
                self.add(p[0].lower(), "part", m["nick"], "you left " + p[0], ts)
            else:
                b.nicks.pop(m["nick"], None)
                self.add(p[0].lower(), "part", m["nick"], "%s left%s" % (m["nick"], (": " + p[1]) if len(p) > 1 and p[1] else ""), ts)
        elif cmd == "KICK" and len(p) >= 2:
            b = self.buf(p[0], "channel")
            b.nicks.pop(p[1], None)
            if p[1].lower() == me.lower():
                b.joined = False
            self.add(p[0].lower(), "part", m["nick"], "%s kicked %s%s" % (m["nick"], p[1], (": " + p[2]) if len(p) > 2 else ""), ts)
        elif cmd == "QUIT":
            with self.lock:
                for k, b in list(self.buffers.items()):
                    if m["nick"] in b.nicks:
                        b.nicks.pop(m["nick"], None)
                        self.add(k, "part", m["nick"], "%s quit%s" % (m["nick"], (": " + p[0]) if p and p[0] else ""), ts)
        elif cmd == "NICK" and p:
            new = p[0]
            if m["nick"].lower() == me.lower():
                self.nick = new
            with self.lock:
                for k, b in list(self.buffers.items()):
                    if m["nick"] in b.nicks:
                        b.nicks[new] = b.nicks.pop(m["nick"])
                        self.add(k, "info", "", "%s is now known as %s" % (m["nick"], new), ts)
                    elif k == m["nick"].lower() and b.kind == "query":
                        self.add(k, "info", "", "%s is now known as %s" % (m["nick"], new), ts)
        elif cmd == "MODE" and len(p) >= 2:
            if p[0][:1] in self.chantypes:
                self._chan_mode(p, m["nick"], ts)
            else:
                self.info("mode %s %s" % (p[0], " ".join(p[1:])))
        elif cmd in ("PRIVMSG", "NOTICE") and len(p) >= 2:
            self._message(m, cmd, p[0], p[1], ts)
        elif cmd == "ERROR":
            self.info("server error: " + (p[0] if p else ""), kind="error")
        elif cmd in ("311", "312", "317", "319", "330", "671") and len(p) >= 3:
            self.add(self.reply_ctx if self.reply_ctx in self.buffers else IRC_SERVER, "info", "", "whois %s: %s" % (p[1], " ".join(irc_strip_format(x) for x in p[2:])))
        elif cmd in ("318", "366", "333"):
            pass
        elif cmd in ("375", "372", "376", "252", "253", "254", "255", "265", "266", "250", "251"):
            if cmd in ("372", "375", "376") and self.cfg.get("show_motd") is not True:
                return
            self.info(" ".join(p[1:]))
        elif cmd.isdigit() and len(p) >= 2:
            kind = "error" if cmd[0] in "45" else "info"
            self.info(" ".join(irc_strip_format(x) for x in p[1:]), kind=kind)

    def _cap(self, p):
        if len(p) < 2:
            return
        sub = p[1].upper()
        names = p[-1].split() if p else []
        if sub == "LS":
            self.caps_ls.update(n.split("=")[0] for n in names)
            if len(p) > 3 and p[2] == "*":
                return
            want = [c for c in IRC_CAPS if c in self.caps_ls and (c != "sasl" or (self.cfg.get("auth", "sasl") == "sasl" and self._creds_ok()))]
            if want:
                self.send("CAP REQ :" + " ".join(want))
            else:
                self._finish_caps()
        elif sub == "ACK":
            if "sasl" in names and self.cfg.get("auth", "sasl") == "sasl" and self._creds_ok():
                self.sasl_state = "auth"
                self.send("AUTHENTICATE PLAIN")
            else:
                self._finish_caps()
        elif sub == "NAK":
            self._finish_caps()

    def _chan_mode(self, p, who, ts):
        chan, modes, args = p[0], p[1], list(p[2:])
        b = self.buf(chan, "channel")
        sign = "+"
        for ch in modes:
            if ch in "+-":
                sign = ch
                continue
            if ch in self.prefix_modes:
                if args:
                    n = args.pop(0)
                    sym = self.prefix_chars[self.prefix_modes.index(ch)]
                    if n in b.nicks:
                        b.nicks[n] = sym if sign == "+" else ""
            elif ch in self.chanmodes[0] or ch in self.chanmodes[1] or (sign == "+" and ch in self.chanmodes[2]):
                if args:
                    args.pop(0)
        self.add(chan.lower(), "info", "", "%s sets mode %s" % (who or "server", " ".join(p[1:])), ts)

    def _message(self, m, cmd, target, text, ts):
        nick = m["nick"] or ""
        me = self.nick
        from_server = not m["prefix"] or (not m["user"] and "." in m["prefix"])
        if text.startswith("\x01") and len(text) > 1:
            body = text.strip("\x01")
            word, _, arg = body.partition(" ")
            word = word.upper()
            if cmd == "PRIVMSG" and word == "ACTION":
                key = self._target_key(target, nick)
                self.add(key, "action", nick, irc_strip_format(arg), ts, hl=self._hl(target, arg))
            elif cmd == "PRIVMSG" and word == "VERSION":
                self.send("NOTICE %s :\x01VERSION synth %s\x01" % (nick, VERSION))
            elif cmd == "PRIVMSG" and word == "PING":
                self.send("NOTICE %s :\x01PING %s\x01" % (nick, arg))
            return
        text = irc_strip_format(text)
        if cmd == "NOTICE":
            if from_server or not nick:
                self.info(text)
                return
            key = target.lower() if target[:1] in self.chantypes else (nick.lower() if nick.lower() in self.buffers else IRC_SERVER)
            self.add(key, "notice", nick, text, ts, hl=False)
            if nick.lower() == "nickserv" and re.search(r"identified|recogni[sz]ed|logged in", text, re.I):
                self._autojoin()
            return
        key = self._target_key(target, nick)
        self.add(key, "msg", nick, text, ts, hl=self._hl(target, text))

    def _target_key(self, target, nick):
        if target[:1] in self.chantypes:
            self.buf(target, "channel")
            return target.lower()
        self.buf(nick, "query")
        return nick.lower()

    def _hl(self, target, text):
        return target[:1] not in self.chantypes or irc_mentioned(text, self.nick)

    # ----- helpers for the UI -----

    def nick_list(self, key):
        with self.lock:
            b = self.buffers.get(key)
            if not b:
                return []
            order = {c: i for i, c in enumerate(self.prefix_chars)}
            return sorted(b.nicks.items(), key=lambda kv: (order.get(kv[1], 99) if kv[1] else 98, kv[0].lower()))

    def snapshot(self, key):
        with self.lock:
            b = self.buffers.get(key)
            if not b:
                return None
            return {"name": b.name, "kind": b.kind, "topic": b.topic, "lines": list(b.lines),
                    "nicks": self.nick_list(key), "joined": b.joined}



class DataSync:
    """Keeps the data folder in a git repository: debounced commits, optional pull and push."""

    IGNORE = "state.json\n.todos-*\n*.tmp\n"

    def __init__(self, directory):
        self.dir = directory
        self.lock = threading.Lock()
        self.lines = []
        self.due = 0.0
        self.delay = 5.0
        self.push = False
        self.status = "off"
        self.detail = ""
        self.worker = None

    def enabled(self):
        return os.path.isdir(os.path.join(self.dir, ".git"))

    def setup(self):
        """git init the data folder when needed. Returns True when ready."""
        if self.enabled():
            self.status = "synced" if self.status == "off" else self.status
            return True
        os.makedirs(self.dir, exist_ok=True)
        if git_run(["init", "-q"], self.dir)[0] != 0:
            self.status, self.detail = "error", "git init failed"
            return False
        ig = os.path.join(self.dir, ".gitignore")
        if not os.path.exists(ig):
            with open(ig, "w", encoding="utf-8") as fh:
                fh.write(self.IGNORE)
        self.commit("synth: start tracking data")
        if self.status != "error":
            self.status = "synced"
        return True

    def has_remote(self):
        rc, out = git_run(["remote"], self.dir)
        return rc == 0 and bool(out.strip())

    def identity(self):
        args = []
        if not git_run(["config", "user.name"], self.dir)[1].strip():
            args += ["-c", "user.name=synth"]
        if not git_run(["config", "user.email"], self.dir)[1].strip():
            args += ["-c", "user.email=synth@localhost"]
        return args

    def commit(self, message):
        git_run(["add", "-A"], self.dir)
        rc, out = git_run(["status", "--porcelain"], self.dir)
        if rc != 0 or not out.strip():
            return False
        rc, out = git_run(self.identity() + ["commit", "-q", "-m", message], self.dir)
        if rc != 0:
            self.status, self.detail = "error", out.strip().split("\n")[-1][:80]
            return False
        return True

    def pull(self):
        if not (self.push and self.has_remote()):
            return True
        rc, out = git_run(["pull", "--rebase", "--autostash", "-q"], self.dir, timeout=30)
        if rc != 0:
            git_run(["rebase", "--abort"], self.dir)
            self.status, self.detail = "conflict", out.strip().split("\n")[-1][:80]
            return False
        return True

    def send(self):
        if not (self.push and self.has_remote()):
            self.status = "synced"
            return
        rc, out = git_run(["push", "-q"], self.dir, timeout=30)
        if rc != 0:
            rc2, out2 = git_run(["push", "-q", "-u", "origin", "HEAD"], self.dir, timeout=30)
            if rc2 != 0:
                self.status, self.detail = "error", out2.strip().split("\n")[-1][:80]
                return
        self.status = "synced"

    def mark(self, lines, delay=None):
        if not self.enabled():
            return
        with self.lock:
            self.lines += list(lines)
            self.due = time.time() + (self.delay if delay is None else delay)
            self.status = "pending"
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, daemon=True)
                self.worker.start()

    def _run(self):
        while True:
            with self.lock:
                wait = self.due - time.time()
            if wait > 0:
                time.sleep(min(wait, 0.5))
                continue
            self.flush()
            with self.lock:
                if time.time() >= self.due and not self.lines:
                    return

    def flush(self):
        with self.lock:
            lines, self.lines = self.lines, []
        if not lines and self.status != "pending":
            return
        if self.commit(change_summary(lines)) or self.status == "pending":
            self.status = "synced"
            self.send()
        elif self.status == "pending":
            self.status = "synced"

    def finish(self, timeout=8.0):
        """Commit anything still waiting. Called when the app quits."""
        with self.lock:
            self.due = 0.0
        w = self.worker
        if w is not None and w.is_alive():
            w.join(timeout)
        if self.lines:
            self.flush()


def last_touch(store, t):
    """Date string of the last time a task changed (history, creation or completion)."""
    stamps = [t["created"]]
    stamps += [e["t"] for e in store.history if e["id"] == t["id"]]
    return max(stamps)[:10]


def review_data(store, td, days=7, stale_days=21):
    """Everything the weekly review shows, computed from the store."""
    iso = td.isoformat()
    cut = (td - dt.timedelta(days=days - 1)).isoformat()
    prev_cut = (td - dt.timedelta(days=2 * days - 1)).isoformat()
    events = [e for e in store.done_log if e["t"][:10] >= cut]
    prev = sum(1 for e in store.done_log if prev_cut <= e["t"][:10] < cut)
    titles, seen = [], set()
    by = collections.Counter()
    for e in sorted(events, key=lambda e: e["t"], reverse=True):
        by[e.get("p") or "(none)"] += 1
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        t = store.get(e["id"])
        name = t["title"] if t else e.get("n", "")
        if name:
            titles.append((name, (t["project"] if t else e.get("p", "")) or ""))
    spent = sum(e["s"] for e in store.time_log if e["t"][:10] >= cut)
    live = [t for t in store.tasks if not t["done"] and not is_snoozed(t, td)]
    slipped = sorted((t for t in live if t["due"] and t["due"] < iso), key=lambda t: (t["due"], -t["prio"]))
    end = (td + dt.timedelta(days=days)).isoformat()
    ahead = sorted((t for t in live if t["due"] and iso <= t["due"] <= end), key=lambda t: (t["due"], -t["prio"]))
    old = (td - dt.timedelta(days=stale_days)).isoformat()
    age, stale = {}, []
    for t in live:
        if t["due"] or t.get("snooze"):
            continue
        lt = last_touch(store, t)
        if lt <= old:
            stale.append(t)
            age[t["id"]] = (td - dt.date.fromisoformat(lt)).days
    stale.sort(key=lambda t: -age[t["id"]])
    cur, _ = streak_info({e["t"][:10] for e in store.done_log}, td) if store.done_log else (0, 0)
    return {"done": len(events), "prev": prev, "time": spent, "streak": cur, "titles": titles,
            "by_project": by.most_common(), "slipped": slipped, "stale": stale, "ahead": ahead, "age": age,
            "ahead_est": sum(t.get("est", 0) for t in ahead)}


def review_text(d, td):
    lines = ["# weekly review, week ending %s" % td.isoformat(), "",
             "done: %d tasks (the 7 days before: %d)%s" % (d["done"], d["prev"], ", %s tracked" % fmt_duration(d["time"]) if d["time"] else ""),
             "streak: %d days" % d["streak"], "", "## wins"]
    lines += ["- " + t for t, _ in d["titles"][:8]] or ["- (nothing logged)"]
    lines += ["", "## loose ends", "- %d overdue, %d untouched for 3 weeks" % (len(d["slipped"]), len(d["stale"])),
              "", "## next week"]
    lines += ["- %s  %s" % (t["due"], t["title"]) for t in d["ahead"][:8]] or ["- (nothing due)"]
    lines += ["", "## notes", "went well: ", "change: "]
    return "\n".join(lines)


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
HEADER_WIDGETS = ["app", "view", "sort", "query", "selection", "timer", "progress", "momentum", "habits", "clock",
                  "date", "open", "overdue", "due_today", "greeting", "week", "text", "sync", "event", "irc"]
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
    "irc": [("name", "Name", "text"), ("host", "Server", "text"), ("port", "Port (blank for default)", "int"),
            ("nick", "Nick", "text"), ("auth", "Login method", "choice", ["sasl", "nickserv", "none"]),
            ("account", "NickServ account", "text"), ("password_cmd", "Password command", "text"),
            ("channels", "Channels to join", "list"), ("autoconnect", "Connect when synth starts", "bool"),
            ("insecure", "No TLS (passwords are never sent)", "bool"), ("noverify", "Skip certificate check", "bool"),
            ("noreconnect", "Do not reconnect", "bool"), ("user", "Username", "text"), ("realname", "Real name", "text")],
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
        _s("detail_sections", "Detail Tabs", "order", "Tabs of the detail pane, in order.", available=["notes", "info", "links", "history"],
           required=["notes"]),
        _s("detail_tab", "Default Tab", "choice", "Tab that opens first.", choices=["notes", "info", "links", "history"]),
    ]
    header = [
        _s("header_left", "Top Bar, Left Widgets", "order", "Widgets on the left of the top bar, in order. Widgets that do not fit are skipped.",
           available=HEADER_WIDGETS, required=[]),
        _s("header_right", "Top Bar, Right Widgets", "order", "Widgets on the right of the top bar, in order.",
           available=HEADER_WIDGETS, required=[]),
        _s("sync_output", "Flicker-free Drawing", "bool", "Draw each frame as one synchronized update. Turn off if your terminal prints stray characters."),
        _s("header_style", "Top Bar Style", "choice", "plain, divided (separator lines) or pills (each widget on its own background).",
           choices=["plain", "divided", "pills"]),
        _s("clock_12h", "12 Hour Clock", "bool", "Show the clock as 3:07 PM instead of 15:07."),
        _s("clock_seconds", "Clock Seconds", "bool", "Include seconds in the clock."),
        _s("clock_format", "Custom Clock Format", "text", "strftime format. Anything other than %H:%M overrides the two options above."),
        _s("header_date", "Top Bar Date Format", "text", "strftime format for the date widget."),
        _s("header_text", "Custom Text", "text", "Text for the text widget, for example a motto or your name."),
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
    gitset = [
        _s("git_sync", "Track Data in Git", "bool", "Commit your todo data to git after every change, with a message listing what changed."),
        _s("git_push", "Push and Pull", "bool", "Pull when synth starts and push after each commit. Needs a remote named origin in the data folder."),
        _s("git_commit_delay", "Commit Delay (seconds)", "int", "Wait this long after the last change so a burst becomes one commit.", min=1, max=300),
        _s("git_auto_done", "Complete From Git", "bool", "Mark a task done when its linked branch is merged or a commit says closes synth:ID."),
        _s("git_refresh", "Check Git Every (minutes)", "int", "How often linked branches and commits are checked. 0 turns the timer off.", min=0, max=240),
        _s("todo_markers", "TODO Markers", "strlist", "Comment markers the TODO scanner looks for, comma separated."),
        _s(None, "Track Data Folder Now", "action", "Run git init in the data folder and start committing.", run="git_setup", button="Set up"),
    ]
    ircset = [
        _s("irc_networks", "Networks", "records",
           "IRC servers. Login is SASL or NickServ with your account. The password is never saved: give a Password command (for example pass show irc/libera), set the SYNTH_IRC_PASSWORD_<NAME> environment variable, or synth asks when you connect.",
           fields="irc"),
        _s("irc_layout", "Chat Pane", "choice", "Split the main screen: chat on the right, on the bottom, or off. ctrl-s inside chat cycles it.", choices=["off", "right", "bottom"]),
        _s("irc_dock_lines", "Bottom Pane Lines", "int", "How many message lines the bottom chat pane shows.", min=1, max=12),
        _s("irc_sidebar", "Chat in Sidebar", "bool", "List chat buffers in the left sidebar (click one to open it)."),
        _s("irc_show_joins", "Show Joins and Parts", "bool", "Show who joins, leaves and quits."),
        _s("irc_nick_colors", "Colored Nicks", "bool", "Give each nick its own color."),
        _s("irc_time", "Time Format", "text", "strftime format of message times, for example %H:%M or %I:%M %p."),
        _s("irc_bell", "Ring Bell on Mentions", "bool", "Ring the terminal bell when someone mentions you or sends a private message."),
        _s(None, "Open IRC", "action", "Open the chat screen.", run="irc_open", button="Open"),
        _s(None, "Add Libera.Chat", "action", "Set up a network with a few questions.", run="irc_add_libera", button="Add"),
    ]
    calendar = [
        _s("ics_sources", "Calendar Files", "strlist", "Paths or URLs of .ics calendars (webcal:// works). Events show in the calendar and agenda, the event widget and What Now."),
        _s("ics_refresh", "Refresh Every (minutes)", "int", "How often web calendars are downloaded again.", min=1, max=1440),
    ]
    review = [
        _s("review_nudge", "Review Reminder", "bool", "Remind you on start when the last weekly review is a week old."),
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
        _node("Git", gitset),
        _node("IRC", ircset),
        _node("Weekly Review", review),
        _node("Calendar Events", calendar),
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
        self.sync = DataSync(os.path.dirname(store.path))
        self.git_thread = None
        self.git_results = []
        self.git_next = time.time() + 3
        self.git_force = False
        self.ics_raw, self.ics_occ, self.ics_loaded = [], [], None
        self.ics_day, self.ics_started, self.ics_next, self.ics_thread = "", False, 0.0, None
        store.on_save = self.on_store_save
        self.anims = {}
        self.irc = {}
        self.irc_pw = {}
        self.irc_sel = ("", IRC_SERVER)
        self.irc_hist = []
        self.irc_in = {"buf": [], "pos": 0, "hi": 0, "cand": None}
        self.irc_scroll = 0
        self.irc_mh = 10
        self.irc_hits = []
        self.irc_side = []
        self.irc_last_layout = ""
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
        if getattr(self, "sync", None) is not None:
            self.sync.delay = max(1.0, float(self.opts.get("git_commit_delay", 5) or 5))
            self.sync.push = bool(self.opts.get("git_push"))
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
        before = {t["id"]: task_sig(t) for t in self.store.tasks} if self.opts.get("history", True) else None
        yield
        self.store.invalidate()
        if before is not None:
            self.store.record_changes(before)
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
        apply_parsed_task(t, p, new)

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

    COMMANDS = ["issues", "prs", "settings", "journal", "habits", "projects", "goals", "note", "snooze", "deps", "template", "run", "theme", "sort", "view", "filter", "set", "export", "clear", "reload", "config",
                "add", "stats", "changes", "review", "git", "todos", "sync", "bulk", "dump", "now", "graph", "travel", "calendar", "agenda", "events", "focus", "track", "find", "links", "irc", "help", "quit", "w", "q"]

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
        elif cmd == "events":
            self.act_calendar("agenda")
        elif cmd == "stats":
            self.act_stats()
        elif cmd in ("changes", "history"):
            self.act_changes()
        elif cmd == "review":
            self.act_review()
        elif cmd == "bulk":
            self.act_bulk()
        elif cmd == "dump":
            self.act_dump()
        elif cmd in ("now", "whatnow"):
            self.act_whatnow()
        elif cmd in ("graph", "map"):
            self.act_graph()
        elif cmd in ("travel", "timetravel"):
            self.act_travel()
        elif cmd == "irc":
            self.act_irc(arg)
        elif cmd == "git":
            self.act_git()
        elif cmd == "todos":
            self.act_git_todos()
        elif cmd in ("issues", "prs"):
            self.act_gh_import("issue" if cmd == "issues" else "pr")
        elif cmd == "sync":
            if self.sync.enabled():
                self.act_sync_now()
            else:
                self.act_sync_setup()
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

    def present(self):
        """Flush the screen inside a synchronized update so terminals never show half a frame."""
        sync = self.opts.get("sync_output", True) and not os.environ.get("SYNTH_NO_SYNC")
        if sync:
            with contextlib.suppress(OSError, ValueError):
                os.write(sys.__stdout__.fileno(), b"\x1b[?2026h")
        try:
            self.scr.refresh()
        finally:
            if sync:
                with contextlib.suppress(OSError, ValueError):
                    os.write(sys.__stdout__.fileno(), b"\x1b[?2026l")

    def input_pending(self):
        try:
            return bool(select.select([sys.stdin], [], [], 0)[0])
        except (OSError, ValueError):
            return False

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
                if self.irc:
                    self.irc_poll()
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

    def prompt(self, title, initial="", live=None, complete=None, hist=None, secret=False):
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
            disp = ["*"] * len(buf) if secret else buf
            start = 0
            while cell_len("".join(disp[start:pos])) >= inner:
                start += 1
            shown = "".join(disp[start:])
            self.fill(y + 1, x + 2, inner, self.attr("fg", "sel_bg"))
            self.put(y + 1, x + 2, shown, self.attr("fg", "sel_bg"), inner)
            cx = x + 2 + cell_len("".join(disp[start:pos]))
            under = disp[pos] if pos < len(disp) else " "
            self.put(y + 1, cx, under, self.attr("fg", "sel_bg", reverse=True))
            for i, (ln, role) in enumerate(lines):
                self.put(y + 2 + i, x + 2, clip(ln, inner), self.attr(role))
            self.put(y + 2 + len(lines), x + 2, "enter accept  esc cancel", self.attr("dim"))
            self.present()
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
            self.present()
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
            self.present()
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
            self.present()
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
            ("SCREENS AND TOOLS", ["journal", "habits", "projects", "calendar", "stats", "changes", "review", "git", "bulk", "dump", "whatnow", "graph", "travel", "focus_mode", "track", "irc",
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

    def clock_text(self):
        o = self.opts
        fmt = o.get("clock_format") or "%H:%M"
        now = dt.datetime.now()
        if fmt != "%H:%M":
            return now.strftime(fmt)
        if o.get("clock_12h"):
            txt = now.strftime("%I:%M:%S %p" if o.get("clock_seconds") else "%I:%M %p")
            return txt.lstrip("0")
        return now.strftime("%H:%M:%S" if o.get("clock_seconds") else "%H:%M")

    def header_lists(self):
        o = self.opts
        left = [w for w in (o.get("header_left") or []) if w in HEADER_WIDGETS]
        right = [w for w in (o.get("header_right") or []) if w in HEADER_WIDGETS]
        # legacy switches from older config files
        if not o.get("header_info", True):
            left = [w for w in left if w != "sort"]
        for key, name in (("header_progress", "progress"), ("header_habits", "habits"), ("header_momentum", "momentum")):
            if not o.get(key, True):
                right = [w for w in right if w != name]
        if o.get("header_clock") and "clock" not in left + right:
            right.append("clock")
        return left, right

    def header_widget(self, name):
        """Return (text, role, bold) for one top bar widget, or None to hide it."""
        o, s = self.opts, self.sym
        td = today()
        if name == "app":
            return self.s("app_name", "synth."), "accent", True
        if name == "view":
            return self.view_label(self.view), "accent2", True
        if name == "sort":
            info = "sort:" + self.view_opt("sort")
            if not self.view_opt("show_done"):
                info += "  hide-done"
            return info, "dim", False
        if name == "query":
            return ("/" + self.query, "today", True) if self.query else None
        if name == "selection":
            return ("%d selected" % len(self.selected), "accent2", True) if self.selected else None
        if name == "timer":
            act = self.store.active
            if not act:
                return None
            tt = self.store.get(act["id"])
            frames = SPINNER_ASCII if o["ascii"] else SPINNER
            spin = frames[int(time.time() * 5) % 4] if o.get("animations") else s["track"]
            return "%s %s %s" % (spin, fmt_duration(self.active_elapsed(), True), clip(tt["title"] if tt else "?", 24)), "today", True
        if name == "progress":
            total, done = self.keep_count, self.keep_done
            if not total:
                return None
            filled = int(round(10 * self.bar_disp))
            return "%s %d/%d" % (s["bar_on"] * filled + s["bar_off"] * (10 - filled), done, total), "ok", False
        if name == "momentum":
            mi = self.momentum()
            if not (mi["streak"] or mi["last7"]):
                return None
            arrow = {1: s["up"], -1: s["down"], 0: s["flat"]}[mi["trend"]]
            txt = "%dd %s %d" % (mi["streak"], arrow, mi["last7"]) if mi["streak"] else "%s %d" % (arrow, mi["last7"])
            return txt, "ok" if mi["trend"] >= 0 else "today", False
        if name == "habits":
            if not self.store.habits:
                return None
            hd, ht = habit_summary(self.store, td)
            return ("habits %d/%d" % (hd, ht), "ok" if hd == ht else "accent2", False) if ht else None
        if name == "clock":
            return self.clock_text(), "dim", False
        if name == "date":
            return td.strftime(o.get("header_date") or "%a %b %d"), "dim", False
        if name in ("open", "overdue", "due_today"):
            iso = td.isoformat()
            live = [t for t in self.store.tasks if not t["done"]]
            if name == "open":
                return "%d open" % len(live), "fg", False
            if name == "overdue":
                n = sum(1 for t in live if t["due"] and t["due"] < iso)
                return ("%d overdue" % n, "overdue", True) if n else None
            n = sum(1 for t in live if t["due"] == iso)
            return ("%d today" % n, "today", False) if n else None
        if name == "greeting":
            h = dt.datetime.now().hour
            return "good " + ("morning" if h < 12 else "afternoon" if h < 18 else "evening"), "accent2", False
        if name == "week":
            return "week %d" % td.isocalendar()[1], "dim", False
        if name == "event":
            now = dt.datetime.now()
            ongoing, nxt = next_event(self.ics_occ, now)
            if ongoing:
                return "now: %s until %s" % (clip(ongoing["summary"], 24), ongoing["end"].strftime("%H:%M")), "today", True
            if nxt and (nxt["start"] - now) < dt.timedelta(hours=12):
                mins = int((nxt["start"] - now).total_seconds() // 60)
                when = ("in %dm" % mins) if mins < 60 else nxt["start"].strftime("%H:%M")
                return "%s %s" % (clip(nxt["summary"], 24), when), "today" if mins <= 15 else "accent2", mins <= 15
            return None
        if name == "sync":
            if not (o.get("git_sync") and self.sync.enabled()):
                return None
            st = self.sync.status
            glyph = {"synced": s["check_on"], "pending": s["bullet"], "conflict": s["blocked"], "error": s["blocked"]}.get(st, s["bullet"])
            return "git %s %s" % (glyph, st), {"synced": "ok", "pending": "accent2"}.get(st, "overdue"), False
        if name == "irc":
            on = [c for c in self.irc.values() if c.status == "online"]
            un = men = 0
            for c in self.irc.values():
                a, b = c.totals()
                un, men = un + a, men + b
            if men:
                return "irc @%d" % men, "today", True
            if un:
                return "irc %d" % un, "accent2", False
            return ("irc", "dim", False) if on else None
        if name == "text":
            return (o.get("header_text") or None) and (o["header_text"], "accent2", False)
        return None

    def draw_header(self, W):
        left, right = self.header_lists()
        style = self.opts.get("header_style", "plain")
        sep_ch = self.sym["vline"]

        def build(names):
            out = []
            for n in names:
                w = self.header_widget(n)
                if w and w[0]:
                    out.append(w)
            return out

        def paint(x, w, first):
            text, role, bold = w
            if style == "pills":
                seg = " %s " % text
                self.put(0, x, seg, self.attr(role, "sel_bg", bold=bold))
                return x + cell_len(seg) + 1
            if style == "divided" and not first:
                self.put(0, x, sep_ch, self.attr("border", "bar_bg"))
                x += 1
            seg = " %s " % text
            self.put(0, x, seg, self.attr(role, "bar_bg", bold=bold))
            return x + cell_len(seg) + (0 if style == "divided" else 0)

        def width_of(w, first):
            extra = 1 if (style == "pills" or (style == "divided" and not first)) else 0
            return cell_len(w[0]) + 2 + extra

        x, first = 0, True
        lw = build(left)
        for w in lw:
            if x + width_of(w, first) > W - 2:
                continue
            x = paint(x, w, first)
            first = False
        rw = build(right)
        fit, used = [], 0
        for w in reversed(rw):
            need = width_of(w, False) + (1 if style == "plain" else 0)
            if x + used + need + 2 > W:
                continue
            fit.append(w)
            used += need
        fit.reverse()
        rx = W - used
        first = True
        for w in fit:
            rx = paint(rx, w, first)
            first = False

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
        pane, main_w = None, W
        lay = self.irc_layout() if self.irc else "off"
        if lay == "right" and W - list_x >= 100:
            pw_ = min(max(36, W // 3), 64)
            pane = (body_y, W - pw_, body_h, pw_, "right")
            main_w = W - pw_ - 1
        elif lay in ("right", "bottom") and H >= 18:
            ph_ = max(1, min(int(o.get("irc_dock_lines", 4)), 12)) + 2
            body_h -= ph_
            pane = (H - 1 - ph_, 0, ph_, W, "bottom")
        self.irc_hits = []
        self.irc_side = []
        if pane is None:
            if self.irc:
                self.irc_sync_view(False)
            if self.focus == "chat":
                self.focus = "list"
        dw = dh = 0
        if o["detail"] == "right" and main_w - list_x >= 72:
            dw = min(o["detail_size"], main_w - list_x - 36)
        elif o["detail"] == "bottom" and body_h >= 16:
            dh = min(o["detail_size"] if o["detail_size"] < 20 else 9, body_h - 8)
        list_w = main_w - list_x - (dw + 1 if dw else 0)
        list_h = body_h - (dh + 1 if dh else 0)
        self.geo = {"list_x": list_x, "list_y": body_y, "list_w": list_w, "list_h": list_h, "sw": sw}

        # header
        hb = self.attr("fg", "bar_bg")
        self.fill(0, 0, W, hb)
        total, done = self.keep_count, self.keep_done
        target = (done / float(total)) if total else 0.0
        if o.get("animations"):
            self.bar_disp += (target - self.bar_disp) * 0.3
            if abs(target - self.bar_disp) < 0.01:
                self.bar_disp = target
            self.bar_busy = abs(target - self.bar_disp) > 0.0
        else:
            self.bar_disp, self.bar_busy = target, False
        self.draw_header(W)

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

        if pane is not None:
            if pane[4] == "right":
                for r in range(body_h):
                    self.put(body_y + r, main_w, s["vline"], self.attr("border"))
            self.irc_draw_pane(*pane)

        # footer
        fb = self.attr("fg", "bar_bg")
        self.fill(H - 1, 0, W, fb)
        right = ""
        if self.selected:
            right = "%d selected " % len(self.selected)
        if self.pending:
            right = "%s ... " % self.pending + right
        where = {"sidebar": "side", "chat": "chat"}.get(self.focus, "list")
        right += "[%s] %d/%d" % (where, min(self.cur + 1, len(self.rows)), len(self.rows))
        left_w = max(0, W - cell_len(right) - 4)
        if self.msg and time.time() < self.msg_until:
            self.put(H - 1, 1, self.msg, self.attr(self.msg_kind, "bar_bg", bold=True), left_w)
        else:
            hint = "chat: enter send  tab nick  ctrl-n/p buffer  ctrl-f fullscreen  ctrl-s layout  esc tasks" if self.focus == "chat" else self.hint_line()
            self.put(H - 1, 1, hint, self.attr("dim", "bar_bg"), left_w)
        self.put(H - 1, W - cell_len(right) - 2, right, self.attr("accent2", "bar_bg"))
        self.present()

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
        if self.irc and self.opts.get("irc_sidebar", True):
            self.draw_sidebar_chat(y, h, w, min(len(items), h))

    def draw_sidebar_chat(self, y, h, w, used):
        r = used + 1
        if r >= h - 1:
            return
        un = men = 0
        for c in self.irc.values():
            a, b = c.totals()
            un, men = un + a, men + b
        total = ("%d!" % men) if men else (str(un) if un else "")
        self.put(y + r, 1, "CHAT", self.attr("dim", bold=True))
        if total:
            self.put(y + r, w - 1 - len(total), total, self.attr("today" if men else "dim", bold=bool(men)))
        r += 1
        pane_on = self.irc_layout() != "off"
        for c in self.irc.values():
            if r >= h:
                return
            glyph = {"online": "o" if self.opts["ascii"] else "●", "offline": "-" if self.opts["ascii"] else "○"}.get(c.status, "~" if self.opts["ascii"] else "◌")
            self.put(y + r, 1, clip("%s %s" % (glyph, c.name), w - 2), self.attr("accent2" if c.status == "online" else "dim", bold=True))
            self.irc_side.append((y + r, c.name, IRC_SERVER))
            r += 1
            with c.lock:
                keys = [k for k in c.buffers if k != IRC_SERVER]
            for k in keys:
                if r >= h:
                    return
                b = c.buffers[k]
                active = pane_on and (c.name, k) == self.irc_sel
                bg = "sel_bg" if active else "bg"
                if active:
                    self.fill(y + r, 0, w, self.attr("fg", bg))
                tail = (" %d!" % b.mentions) if b.mentions else ((" %d" % b.unread) if b.unread else "")
                role = "today" if b.mentions else ("fg" if (b.unread or active) else "dim")
                self.put(y + r, 2, clip(b.name, w - 3 - len(tail)), self.attr(role, bg, bold=bool(b.unread) or active))
                if tail:
                    self.put(y + r, w - len(tail) - 1, tail, self.attr(role, bg))
                self.irc_side.append((y + r, c.name, k))
                r += 1

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
        # narrow list: shrink tags and project first, then drop the least useful columns so nothing spills out
        while w - 2 - used < 16 and (fixed["tags"] > 8 or fixed["project"] > 8):
            key = "tags" if fixed["tags"] >= fixed["project"] else "project"
            fixed[key] -= 1
            used -= 1
        for drop in ("created", "id", "snooze", "deps", "est", "time", "project", "tags", "due"):
            if w - 2 - used >= 16:
                break
            if drop in cols and fixed[drop] > 0:
                used -= fixed[drop] + 1
                cols = [c for c in cols if c != drop]
        tag_w, proj_w = fixed["tags"], fixed["project"]
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
                    gb = t.get("git") or {}
                    if gb.get("branch") or gb.get("commits") or t.get("src") or t.get("gh"):
                        suffix += " " + self.sym["git"]
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
        names = [n for n in self.opts.get("detail_sections", []) if n in ("notes", "info", "links", "history")]
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
            gi = t.get("git") or {}
            if gi.get("branch"):
                row("branch", "%s (%s)" % (gi["branch"], gi.get("state", "active")), "ok" if gi.get("state") == "merged" else "accent2")
            for cm in (gi.get("commits") or [])[:4]:
                row("commit", cm, "dim")
            gh = t.get("gh") or {}
            if gh.get("number"):
                row("github", "%s #%d (%s)" % ("PR" if gh.get("kind") == "pr" else "issue", gh["number"], gh.get("state", "open")),
                    "ok" if gh_done_state(gh.get("kind", "issue"), gh.get("state", "open")) else "accent2")
            if t.get("src"):
                row("source", "%s:%s" % (t["src"].get("file", "?"), t["src"].get("line", "?")), "dim")
            lines.append(("", "fg", False))
            row("id", str(t["id"]), "dim")
            row("created", t["created"].replace("T", " ")[:16], "dim")
            if t["done_at"]:
                row("finished", t["done_at"].replace("T", " ")[:16], "dim")
        elif tab == "history":
            evs = history_for(self.store, t["id"])
            if not evs:
                lines.append(("No history yet.", "dim", False))
            last_day = ""
            for e in reversed(evs):
                day = e["t"][:10]
                if day != last_day:
                    head(day)
                    last_day = day
                txt = "%s %s" % (e["t"][11:16], HIST_LABEL.get(e["k"], e["k"]))
                if e["d"] and e["k"] != "created":
                    txt += "  " + e["d"]
                role = "ok" if e["k"] == "done" else "fg"
                for i, ln in enumerate(wrap(txt, w - 2) or [""]):
                    lines.append((("%s " % self.sym["bullet"] if i == 0 else "  ") + ln, role, False))
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
        if self.irc and any(c.status != "offline" for c in self.irc.values()):
            return 500 if not (self.anims or self.bar_busy) else 40
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
            self.present()
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
        tabs = ["overview", "time", "heatmap", "estimates", "momentum"]
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
                self.present()
                name, _ = self.read_key()
                if name in ("q", "esc", "ctrl-c") or self.keymap.get(name) == "stats":
                    return
                if name in ("tab", "l", "right"):
                    S["tab"] = (S["tab"] + 1) % len(tabs)
                    S["t0"] = time.time()
                elif name in ("shift-tab", "h", "left"):
                    S["tab"] = (S["tab"] - 1) % len(tabs)
                    S["t0"] = time.time()
                elif name in ("1", "2", "3", "4", "5"):
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
        self.put(H - 1, 1, "tab or h/l switch   1-5 jump   r range   q close", self.attr("dim", "bar_bg"), W - 2)
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
        elif tab == 4:
            self.draw_momentum(H, W, grow)
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
        ev_by = {}
        for n in range(0, 91):
            d = td + dt.timedelta(days=n)
            evs = self.events_on(d)
            if evs:
                ev_by[d.isoformat()] = evs
        for k in sorted({x for x in by if tiso <= x <= horizon} | set(ev_by)):
            date = dt.date.fromisoformat(k)
            rows.append(("head", self.date_heading(date, td), date))
            rows += [("event", o, date) for o in ev_by.get(k, [])]
            rows += [("task", t) for t in by.get(k, [])]
        nodate = [t for t in self.store.tasks if not t["due"] and not t["done"] and t["parent"] is None]
        if nodate:
            rows.append(("head", "No date (%d)" % len(nodate), None))
            rows += [("task", t) for t in nodate[:20]]
        return rows

    def cal_event_row(self, y, x, w, o, date):
        lab = self.event_label(o, date)
        cx = self.put(y, x + 1, pad(lab, 11), self.attr("accent", bold=True))
        txt = o["summary"] + (("  " + o["location"]) if o["location"] else "")
        self.put(y, cx + 1, txt, self.attr("fg"), max(1, x + w - cx - 2))

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
                if chh > 1 and self.ics_occ and self.events_on(d):
                    self.put(cy, cx + 3, "~", self.attr("accent", bg, bold=True))
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
            if r[0] == "event":
                self.cal_event_row(3 + i, px, pw, r[1], r[2])
            else:
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
            elif r[0] == "event":
                self.cal_event_row(y, x, w, r[1], r[2])
            else:
                self.cal_task_row(y, x, w, r[1], ri == cur_row, show_due=False)

    def act_calendar(self, mode="month"):
        td = today()
        S = {"mode": mode, "sel": td, "focus": "grid" if mode == "month" else "list", "idx": 0, "top": 0}
        ws = 6 if self.opts.get("week_start") == "sun" else 0

        def compute():
            by = self.due_map()
            if S["mode"] == "month":
                rows = [("event", o, S["sel"]) for o in self.events_on(S["sel"])]
                rows += [("task", t) for t in by.get(S["sel"].isoformat(), [])]
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
                hint = "h/j/k/l day   [ ] month   t today   enter tasks   a add   i event to task   v agenda   q close"
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
                self.present()
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
                    elif name == "i":
                        self.pick_event_task(S["sel"])
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
                elif name == "i":
                    self.pick_event_task(cdate or td)
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
             "iso": now_iso(), "running": True, "rounds": 0, "logged": 0, "rounds_per": rounds_per, "parked": []}
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
                self.present()
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
                elif name == "p":
                    self.focus_park(t, F)
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
        msg = "focus ended: %s logged, %d round%s" % (fmt_duration(F["logged"]), F["rounds"], "" if F["rounds"] == 1 else "s")
        if F["parked"]:
            msg += ", %d thought%s parked in the inbox" % (len(F["parked"]), "" if len(F["parked"]) == 1 else "s")
        self.say(msg, "ok", 6)

    def focus_park(self, t, F):
        """Parking lot: capture a stray thought as an inbox task without leaving focus."""
        text = self.prompt("parking lot: what just came to mind?", hist="park")
        if not text or not text.strip():
            return
        p = parse_quick(text)
        if not p["title"]:
            return
        with self.edit():
            n = self.store.add(p["title"])
            apply_parsed_task(n, p, True)
            if "parked" not in n["tags"]:
                n["tags"].append("parked")
            note = "parked at %s while focusing on: %s" % (dt.datetime.now().strftime("%H:%M"), t["title"])
            n["notes"] = (n["notes"].rstrip() + "\n" if n["notes"].strip() else "") + note
            if not p["project"]:
                n["project"] = ""
        F["parked"].append(n["id"])
        self.say("parked: " + clip(p["title"], 40), "ok", 3)

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
        if F.get("parked"):
            last = self.store.get(F["parked"][-1])
            center(H - 3 if H >= 18 else H - 2, "parked %d%s" % (len(F["parked"]), (": " + clip(last["title"], max(10, W - 24))) if last else ""),
                   self.attr("accent2"))
        self.put(H - 1, 1, "space pause   n skip   + - 5 min   r restart   p park a thought   x done   q leave", self.attr("dim"), W - 2)
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
            self.present()
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
                self.present()
                name, ch = self.read_key()
                if name in ("tick", "resize", "mouse"):
                    continue
                if handle(name, ch):
                    return
        finally:
            self.backdrop = self.draw
            self.tick_override = None

    # ----- IRC -----

    IRC_NICK_ROLES = ["accent", "accent2", "ok", "today", "p1", "p2", "p3", "tag", "project"]
    IRC_HELP = [
        "/join #chan   /part   /msg nick text   /me action   /nick NEW   /topic [text]   /names   /whois nick",
        "/ns, /cs  talk to NickServ or ChanServ (never echoed)   /identify PASSWORD   /away [text]   /raw LINE",
        "/connect [net]   /disconnect   /close  close this buffer   /next  /prev   /clear   /exit  leave this screen",
        "/share  send the selected task to this chat   /todo [nick]  make a task from the last message",
        "/task TEXT  quick add a task (same syntax as the add prompt)   //text  sends a line starting with /",
        "keys: tab complete nick, ctrl-n / ctrl-p or alt-1..9 switch buffer, pgup / pgdn scroll, esc back to your tasks",
    ]

    def irc_nets(self):
        return [n for n in (self.opts.get("irc_networks") or []) if isinstance(n, dict) and n.get("host")]

    def irc_net_cfg(self, rec):
        tls = not rec.get("insecure")
        try:
            port = int(rec.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        chans = rec.get("channels") or []
        if isinstance(chans, str):
            chans = [c.strip() for c in chans.split(",") if c.strip()]
        auth = rec.get("auth") or ("sasl" if (rec.get("account") or rec.get("password_cmd")) else "none")
        return {"name": str(rec.get("name") or rec["host"]), "host": str(rec["host"]), "tls": tls,
                "port": port or (6697 if tls else 6667), "verify": not rec.get("noverify"),
                "reconnect": not rec.get("noreconnect"),
                "nick": str(rec.get("nick") or os.environ.get("USER") or "synth"),
                "user": str(rec.get("user") or ""), "realname": str(rec.get("realname") or "synth user"),
                "account": str(rec.get("account") or ""), "auth": auth, "channels": list(chans)}

    def irc_password(self, cfg, rec, ask):
        """Find the password without ever writing it to disk: command, environment, then a masked prompt."""
        if cfg["auth"] == "none":
            return None
        name = cfg["name"]
        if self.irc_pw.get(name):
            return self.irc_pw[name]
        pw = None
        cmd = rec.get("password_cmd")
        if cmd:
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15,
                                   stdin=subprocess.DEVNULL)
                if r.returncode == 0 and r.stdout.strip():
                    pw = r.stdout.strip().split("\n")[0]
                else:
                    self.say("password command failed", "err")
            except (OSError, subprocess.SubprocessError):
                self.say("password command failed", "err")
        if not pw:
            pw = os.environ.get(irc_env_name(name)) or None
        if not pw and ask:
            who = cfg["account"] or cfg["nick"]
            pw = self.prompt("password for %s on %s (not saved)" % (who, name), "", secret=True) or None
        if pw:
            self.irc_pw[name] = pw
        return pw

    def irc_connect(self, rec, ask=True):
        cfg = self.irc_net_cfg(rec)
        c = self.irc.get(cfg["name"])
        if c is not None and c.thread is not None and c.thread.is_alive():
            return c
        pw = self.irc_password(cfg, rec, ask)
        if cfg["auth"] != "none" and not pw:
            if ask:
                self.say("no password, not connecting", "err")
            return None
        if c is None:
            c = self.irc[cfg["name"]] = IrcClient(cfg, password=pw)
        else:
            c.cfg, c.password = cfg, pw
        c.start()
        return c

    def irc_autostart(self):
        started = []
        for rec in self.irc_nets():
            if rec.get("autoconnect"):
                c = self.irc_connect(rec, ask=False)
                if c is not None:
                    started.append(c)
                else:
                    self.say("irc: %s needs a password, open irc to connect" % (rec.get("name") or rec["host"]), "today", 5)

    def irc_shutdown(self):
        for c in list(self.irc.values()):
            with contextlib.suppress(Exception):
                c.stop("synth")

    def irc_poll(self):
        for c in list(self.irc.values()):
            while c.alerts:
                try:
                    net, bname, nick, text = c.alerts.popleft()
                except IndexError:
                    break
                if bname[:1] in c.chantypes:
                    self.say("irc %s <%s> %s" % (bname, nick, clip(irc_strip_format(text), 70)), "today", 6)
                else:
                    self.say("irc message from %s: %s" % (nick, clip(irc_strip_format(text), 60)), "today", 6)
                if self.opts.get("irc_bell", True):
                    with contextlib.suppress(curses.error):
                        curses.beep()

    def irc_setup(self, libera=False):
        host = "irc.libera.chat" if libera else self.prompt("IRC server host", "")
        if not host or not host.strip():
            return None
        host = host.strip()
        nick = self.prompt("nick", os.environ.get("USER", ""))
        if not nick or not nick.strip():
            return None
        account = self.prompt("NickServ account (blank to connect without logging in)", nick.strip())
        if account is None:
            return None
        chans = self.prompt("channels to join, comma separated (blank for none)", "")
        if chans is None:
            return None
        rec = {"name": "libera" if libera else host, "host": host, "nick": nick.strip()}
        if account.strip():
            rec["account"], rec["auth"] = account.strip(), "sasl"
        cl = [c.strip() for c in chans.split(",") if c.strip()]
        if cl:
            rec["channels"] = cl
        nets = [n for n in (self.opts.get("irc_networks") or []) if isinstance(n, dict)] + [rec]
        self.persist("irc_networks", nets)
        self.apply_config()
        self.say("added %s, the password is asked when you connect" % rec["name"])
        return rec

    def sv_action_irc_open(self):
        self.act_irc()

    def sv_action_irc_add_libera(self):
        self.irc_setup(True)

    def irc_layout(self):
        o = self.opts
        lay = o.get("irc_layout") or ("bottom" if o.get("irc_dock") else "off")
        return lay if lay in ("right", "bottom") else "off"

    def irc_set_layout(self, mode, focus=True):
        if mode not in ("off", "right", "bottom"):
            return
        self.persist("irc_layout", mode)
        self.apply_config()
        if mode != "off":
            self.irc_last_layout = mode
            if focus:
                self.focus = "chat"
        elif self.focus == "chat":
            self.focus = "list"

    def irc_show_pane(self):
        """Make sure a chat pane is visible and give it the keyboard."""
        if self.scr.getmaxyx()[0] < 18:
            self.irc_screen()
            return
        if self.irc_layout() == "off":
            H, W = self.scr.getmaxyx()
            want = self.irc_last_layout or ("right" if W >= 100 else "bottom")
            self.irc_set_layout(want)
        self.focus = "chat"

    def act_irc(self, arg=None):
        word = (arg or "").strip().lower()
        if word in ("right", "bottom", "off"):
            if word != "off" and not self.irc:
                self.irc_start_flow()
            if word == "off" or self.irc:
                self.irc_set_layout(word)
            return
        if not self.irc_start_flow(word):
            return
        if self.irc_layout() != "off" and word != "full" and self.scr.getmaxyx()[0] >= 18:
            self.focus = "chat"
            return
        self.irc_screen()

    def irc_start_flow(self, want=""):
        """Set up and connect networks as needed. False when there is nothing to chat with."""
        if not self.irc_nets() and not self.irc:
            i = self.menu("irc: add a network", ["Libera.Chat", "Another server...", "Cancel"], 0)
            if i is None or i == 2:
                return False
            if self.irc_setup(i == 0) is None:
                return False
        nets = self.irc_nets()
        for rec in nets:
            if rec.get("autoconnect"):
                self.irc_connect(rec)
        if want and want != "full":
            pick = [r for r in nets if str(r.get("name") or r["host"]).lower() == want]
            if pick:
                self.irc_connect(pick[0])
        elif not any(c.thread and c.thread.is_alive() for c in self.irc.values()) and nets:
            if len(nets) == 1:
                self.irc_connect(nets[0])
            else:
                names = [str(r.get("name") or r["host"]) for r in nets] + ["(just look)"]
                i = self.menu("irc: connect to", names, 0)
                if i is not None and i < len(nets):
                    self.irc_connect(nets[i])
        return True

    def irc_entries(self):
        out = []
        for c in self.irc.values():
            out.append(("net", c, None))
            with c.lock:
                keys = list(c.buffers.keys())
            for k in keys:
                out.append(("buf", c, k))
        return out

    def irc_select(self, step=None, index=None, to=None):
        bufs = [(c, k) for kind, c, k in self.irc_entries() if kind == "buf"]
        if not bufs:
            return
        cur = (self.irc.get(self.irc_sel[0]), self.irc_sel[1])
        try:
            i = bufs.index(cur)
        except ValueError:
            i = 0
        if step is not None:
            i = (i + step) % len(bufs)
        elif index is not None and 0 <= index < len(bufs):
            i = index
        elif to is not None:
            for j, (c, k) in enumerate(bufs):
                if (c.name, k) == to:
                    i = j
        c, k = bufs[i]
        if (c.name, k) != self.irc_sel:
            self.irc_scroll = 0
        self.irc_sel = (c.name, k)

    def irc_sync_view(self, show=True):
        sel = self.irc_sel
        for c in self.irc.values():
            if show and c.name == sel[0] and sel[1] in c.buffers:
                if c.viewing != sel[1] or c.buffers[sel[1]].unread:
                    c.view(sel[1])
            elif c.viewing is not None:
                c.view(None)

    def irc_current(self):
        """Make sure a buffer is selected and return (client, key)."""
        if not self.irc:
            return None, IRC_SERVER
        if self.irc_sel[0] not in self.irc or self.irc_sel[1] not in self.irc[self.irc_sel[0]].buffers:
            first = next(iter(self.irc.values()))
            self.irc_sel = (first.name, IRC_SERVER)
        return self.irc[self.irc_sel[0]], self.irc_sel[1]

    def irc_add_task(self, text, notes=""):
        p = parse_quick(text)
        if not p["title"]:
            self.say("title is empty", "err")
            return None
        with self.edit():
            t = self.store.add(p["title"])
            self.add_defaults(t)
            self.apply_parsed(t, p, True)
            if notes:
                t["notes"] = notes
        self.hook("on_add", t)
        return t

    def irc_share_text(self, t):
        bits = ["[task #%d] %s" % (t["id"], t["title"])]
        extra = []
        if t.get("due"):
            extra.append("due " + str(t["due"]))
        if t.get("prio"):
            extra.append("!%d" % t["prio"])
        if t.get("project"):
            extra.append("@" + t["project"])
        extra += ["#" + x for x in t.get("tags") or []]
        if extra:
            bits.append("(" + ", ".join(extra) + ")")
        return " ".join(bits)

    def irc_submit(self, text, hist_state):
        """Handle one input line. Returns True when the screen should close."""
        sel_c = self.irc.get(self.irc_sel[0])
        key = self.irc_sel[1]
        if text.startswith("/") and not text.startswith("//"):
            cmd, _, rest = text[1:].partition(" ")
            low, rest = cmd.lower(), rest.strip()
            if low in ("exit", "leave-screen"):
                return True
            if low == "help":
                if sel_c:
                    for ln in self.IRC_HELP:
                        sel_c.info(ln, key)
                return False
            if low == "connect":
                pool = self.irc_nets()
                name = rest.lower() or (sel_c.name.lower() if sel_c else "")
                pick = [r for r in pool if str(r.get("name") or r["host"]).lower() == name]
                if not pick and len(pool) == 1 and not rest:
                    pick = pool
                if not pick:
                    self.say("no such network, add one in settings", "err")
                else:
                    self.irc_connect(pick[0])
                    self.irc_pw_cleanup()
                return False
            if low in ("next", "prev"):
                self.irc_select(step=1 if low == "next" else -1)
                return False
            if low == "task":
                t = self.irc_add_task(rest) if rest else None
                self.say("task added" if t else "usage: /task text", "ok" if t else "err")
                return False
            if sel_c is None:
                self.say("not connected, use /connect", "err")
                return False
            if low in ("disconnect", "quit"):
                sel_c.stop(rest or "synth")
                sel_c.info("disconnected")
                return low == "quit"
            if low == "clear":
                with sel_c.lock:
                    sel_c.buffers[key].lines.clear()
                    sel_c.rev += 1
                return False
            if low == "close":
                if key == IRC_SERVER:
                    self.say("the server buffer cannot be closed", "err")
                    return False
                b = sel_c.buffers.get(key)
                if b and b.kind == "channel" and b.joined:
                    sel_c.command(key, "/part")
                self.irc_select(step=-1)
                with sel_c.lock:
                    sel_c.buffers.pop(key, None)
                    sel_c.rev += 1
                return False
            if low == "share":
                t = self.current()
                if not t:
                    self.say("no task selected", "err")
                    return False
                err = sel_c.privmsg(key, self.irc_share_text(t))
                if err:
                    self.say(err, "err")
                return False
            if low == "todo":
                snap = sel_c.snapshot(key)
                pick = None
                for ts, kind, nick, body in reversed(snap["lines"] if snap else []):
                    if kind in ("msg", "action") and nick.lower() != sel_c.nick.lower() and (not rest or nick.lower() == rest.lower()):
                        pick = (ts, nick, body)
                        break
                if not pick:
                    self.say("no message to turn into a task", "err")
                    return False
                ts, nick, body = pick
                src = "from %s in %s on %s at %s" % (nick, snap["name"] if key != IRC_SERVER else "server", sel_c.name,
                                                      dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"))
                title = " ".join(irc_strip_format(body).split())
                t = self.store_task_plain(clip(title, 120), "%s\n\n%s" % (src, title) if len(title) > 120 else src)
                self.say("task added from %s" % nick, "ok")
                return False
            err, switch = sel_c.command(key, text)
            if err:
                self.say(err, "err")
            if switch:
                self.irc_sel = (sel_c.name, switch)
            return False
        if text.startswith("//"):
            text = text[1:]
        if sel_c is None:
            self.say("not connected, use /connect", "err")
            return False
        err = sel_c.privmsg(key, text)
        if err:
            self.say(err, "err")
        return False

    def irc_pw_cleanup(self):
        pass

    def store_task_plain(self, title, notes):
        """Add a task with exactly this title, without quick add parsing."""
        with self.edit():
            t = self.store.add(title)
            self.add_defaults(t)
            t["notes"] = notes
        self.hook("on_add", t)
        return t

    def irc_line_rows(self, entry, width, c):
        """Turn one buffer line into rows of (text, role, bold) segments."""
        ts, kind, nick, text = entry
        o = self.opts
        if kind in ("join", "part") and not o.get("irc_show_joins", True):
            return []
        stamp = dt.datetime.fromtimestamp(ts).strftime(o.get("irc_time") or "%H:%M") + " "
        text = irc_strip_format(text)
        colors = o.get("irc_nick_colors", True)
        nrole = self.IRC_NICK_ROLES[irc_color_index(nick, len(self.IRC_NICK_ROLES))] if colors and nick else "fg"
        mine = nick.lower() == c.nick.lower()
        if kind in ("msg", "own"):
            head = [(stamp, "dim", False), (nick, "accent" if (kind == "own" or mine) else nrole, True), ("  ", "fg", False)]
            role = "today" if (kind == "msg" and not mine and irc_mentioned(text, c.nick)) else "fg"
        elif kind == "action":
            head = [(stamp, "dim", False), ("* ", "accent2", False), (nick, nrole, True), (" ", "fg", False)]
            role = "accent2"
        elif kind == "notice":
            head = [(stamp, "dim", False), ("-%s- " % nick, "accent2", False)]
            role = "accent2"
        elif kind == "error":
            head, role = [(stamp, "dim", False), ("!! ", "err", True)], "err"
        else:
            mark = {"join": "--> ", "part": "<-- "}.get(kind, "-- ")
            head, role = [(stamp, "dim", False), (mark, "dim", False)], "dim"
        hw = sum(cell_len(t) for t, _, _ in head)
        avail = max(8, width - hw)
        chunks = wrap(text, avail) or [""]
        rows = [head + [(chunks[0], role, role == "today")]]
        for ch in chunks[1:]:
            rows.append([(" " * min(hw, 12), "fg", False), (ch, role, role == "today")])
        return rows

    def irc_tab_label(self, c, k, b):
        if k == IRC_SERVER:
            name = c.name if len(self.irc) > 1 else "server"
        else:
            name = b.name
        tail = ""
        if b.mentions:
            tail = " %d!" % b.mentions
        elif b.unread:
            tail = " %d" % b.unread
        return name + tail

    def irc_draw_pane(self, oy, ox, ph, pw, mode):
        """Draw chat into a rectangle. mode is full (the chat screen), right or bottom (split with the tasks)."""
        full = mode == "full"
        focused = full or self.focus == "chat"
        s = self.sym
        hits = self.irc_hits
        c, key = self.irc_current()
        self.irc_sync_view(True)
        snap = c.snapshot(key) if c else None
        lw = min(26, max(16, pw // 5)) if (full and pw >= 72) else 0
        nw = 0
        if full and pw >= 100 and snap and snap["kind"] == "channel":
            nw = min(20, max(14, pw // 6))
        cx = ox + lw + (1 if lw else 0)
        cw = pw - (cx - ox) - (nw + 1 if nw else 0)
        input_y = oy + ph - 1
        if lw:
            topic_y, msg_top = oy, oy + 1
            r = oy
            for kind, cc, k in self.irc_entries():
                if r >= input_y:
                    break
                if kind == "net":
                    glyph = {"online": "o" if self.opts["ascii"] else "●", "offline": "-" if self.opts["ascii"] else "○"}.get(cc.status, "~" if self.opts["ascii"] else "◌")
                    self.put(r, ox + 1, clip("%s %s" % (glyph, cc.name), lw - 1), self.attr("accent2" if cc.status == "online" else "dim", bold=True))
                else:
                    b = cc.buffers[k]
                    sel = (cc.name, k) == self.irc_sel
                    label = "server" if k == IRC_SERVER else b.name
                    tail = (" %d!" % b.mentions) if b.mentions else ((" %d" % b.unread) if b.unread else "")
                    a = self.attr("accent", "sel_bg", bold=True) if sel else self.attr("today" if b.mentions else ("fg" if b.unread else "dim"), bold=bool(b.unread))
                    if sel:
                        self.fill(r, ox, lw, a)
                    self.put(r, ox + 2, clip(label, lw - 3 - len(tail)), a)
                    if tail:
                        self.put(r, ox + lw - len(tail) - 1, tail, a)
                    hits.append(("buf", ox, r, ox + lw, r + 1, (cc.name, k)))
                r += 1
            for rr in range(oy, input_y):
                self.put(rr, ox + lw, s["vline"], self.attr("border"))
        else:
            self.fill(oy, ox, pw, self.attr("fg", "bar_bg"))
            tabs = [(cc, k, cc.buffers[k]) for kind, cc, k in self.irc_entries() if kind == "buf"]
            labels = [" %s " % self.irc_tab_label(cc, k, b) for cc, k, b in tabs]
            sel_i = next((i for i, (cc, k, _) in enumerate(tabs) if (cc.name, k) == self.irc_sel), 0)
            start = 0
            while start < sel_i and sum(cell_len(x) for x in labels[start:sel_i + 1]) > pw - 2:
                start += 1
            x = ox
            for i in range(start, len(tabs)):
                cc, k, b = tabs[i]
                w_ = cell_len(labels[i])
                if x + w_ > ox + pw:
                    break
                if i == sel_i:
                    a = self.attr("accent", "sel_bg", bold=True)
                elif b.mentions:
                    a = self.attr("today", "bar_bg", bold=True)
                elif b.unread:
                    a = self.attr("fg", "bar_bg", bold=True)
                else:
                    a = self.attr("dim", "bar_bg")
                self.put(oy, x, labels[i], a)
                hits.append(("buf", x, oy, x + w_, oy + 1, (cc.name, k)))
                x += w_
            if ph >= 8:
                topic_y, msg_top = oy + 1, oy + 2
            else:
                topic_y, msg_top = None, oy + 1
        mh = max(1, input_y - msg_top)
        self.irc_mh = mh
        if topic_y is not None:
            if snap:
                title = ("%s %s" % (c.name, c.status)) if key == IRC_SERVER else snap["name"]
                if snap["topic"]:
                    title += "  " + irc_strip_format(snap["topic"])
                self.put(topic_y, cx, clip(title, cw), self.attr("accent2", bold=True), cw)
            else:
                self.put(topic_y, cx, clip("no connection, type /connect or /help", cw), self.attr("dim"), cw)
        rows = []
        if snap:
            for entry in snap["lines"][-(mh + self.irc_scroll + 60):]:
                rows.extend(self.irc_line_rows(entry, cw, c))
        self.irc_scroll = max(0, min(self.irc_scroll, max(0, len(rows) - mh)))
        end = len(rows) - self.irc_scroll
        window = rows[max(0, end - mh):end]
        for i, row in enumerate(window):
            x = cx
            for text, role, bold in row:
                if x >= cx + cw:
                    break
                x = self.put(msg_top + (mh - len(window)) + i, x, text, self.attr(role, bold=bold), cx + cw - x)
        if self.irc_scroll:
            self.put(msg_top, cx + cw - 12, " scrolled %d " % self.irc_scroll, self.attr("today", "bar_bg"))
        hits.append(("msgs", cx, msg_top, cx + cw, msg_top + mh, None))
        if nw and snap:
            nx = ox + pw - nw
            for rr in range(oy, input_y):
                self.put(rr, nx - 1, s["vline"], self.attr("border"))
            self.put(oy, nx, "%d nicks" % len(snap["nicks"]), self.attr("dim"), nw)
            for i, (n, pre) in enumerate(snap["nicks"][:max(0, input_y - oy - 1)]):
                mine = c.nick.lower() == n.lower()
                role = "accent" if mine else (self.IRC_NICK_ROLES[irc_color_index(n, len(self.IRC_NICK_ROLES))] if self.opts.get("irc_nick_colors", True) else "fg")
                self.put(oy + 1 + i, nx, clip((pre or " ") + n, nw - 1), self.attr(role), nw - 1)
                hits.append(("nick", nx, oy + 1 + i, nx + nw, oy + 2 + i, n))
        # input line
        buf, pos = self.irc_in["buf"], self.irc_in["pos"]
        bg = "sel_bg" if focused else "bar_bg"
        label = clip("[%s] " % ("server" if key == IRC_SERVER else (snap["name"] if snap else "-")), max(6, pw // 3))
        self.fill(input_y, ox, pw, self.attr("fg", bg))
        lx = self.put(input_y, ox + 1, label, self.attr("accent" if focused else "dim", bg, bold=focused))
        avail = pw - 2 - cell_len(label)
        if not focused and not buf:
            self.put(input_y, lx, "click here or press %s to chat" % self.first_key("irc"), self.attr("dim", bg), avail)
        else:
            start = 0
            while cell_len("".join(buf[start:pos])) >= avail - 1:
                start += 1
            self.put(input_y, lx, "".join(buf[start:]), self.attr("fg", bg), avail)
            if focused:
                cxp = lx + cell_len("".join(buf[start:pos]))
                under = buf[pos] if pos < len(buf) else " "
                self.put(input_y, cxp, under, self.attr("fg", bg, reverse=True))
        hits.append(("input", ox, input_y, ox + pw, input_y + 1, None))
        hits.append(("pane", ox, oy, ox + pw, oy + ph, None))

    def irc_input_key(self, name, ch, full):
        """Edit the chat input line. Returns None, or leave, full, dock, layout for the caller to act on."""
        st = self.irc_in
        buf, pos = st["buf"], st["pos"]
        hist = self.irc_hist
        mh = max(1, self.irc_mh)
        if name != "tab":
            st["cand"] = None
        if name in ("esc", "ctrl-c"):
            return "leave"
        if name == "ctrl-f":
            return "leave" if full else "full"
        if name == "ctrl-s":
            return "dock" if full else "layout"
        if name == "enter":
            text = "".join(buf)
            st["buf"], st["pos"] = [], 0
            self.irc_scroll = 0
            if text.strip():
                if not text.startswith(("/ns", "/nickserv", "/identify", "/cs", "/chanserv", "/raw", "/quote")):
                    hist[:] = [h for h in hist if h != text][-50:] + [text]
                st["hi"] = len(hist)
                if self.irc_submit(text, None):
                    return "leave"
            return None
        if name in ("ctrl-n", "alt-down"):
            self.irc_select(step=1)
        elif name in ("ctrl-p", "alt-up"):
            self.irc_select(step=-1)
        elif name.startswith("alt-") and name[4:].isdigit():
            self.irc_select(index=int(name[4:]) - 1)
        elif name == "pgup":
            self.irc_scroll += max(1, mh - 2)
        elif name == "pgdn":
            self.irc_scroll = max(0, self.irc_scroll - max(1, mh - 2))
        elif name == "up":
            if st["hi"] > 0:
                st["hi"] -= 1
                st["buf"] = list(hist[st["hi"]])
                st["pos"] = len(st["buf"])
        elif name == "down":
            if st["hi"] < len(hist):
                st["hi"] += 1
                st["buf"] = list(hist[st["hi"]]) if st["hi"] < len(hist) else []
                st["pos"] = len(st["buf"])
        elif name == "left":
            st["pos"] = max(0, pos - 1)
        elif name == "right":
            st["pos"] = min(len(buf), pos + 1)
        elif name in ("home", "ctrl-a"):
            st["pos"] = 0
        elif name in ("end", "ctrl-e"):
            st["pos"] = len(buf)
        elif name == "backspace":
            if pos > 0:
                del buf[pos - 1]
                st["pos"] = pos - 1
        elif name == "delete":
            if pos < len(buf):
                del buf[pos]
        elif name == "ctrl-u":
            del buf[:pos]
            st["pos"] = 0
        elif name == "ctrl-k":
            del buf[pos:]
        elif name == "ctrl-w":
            j = pos
            while j > 0 and buf[j - 1] == " ":
                j -= 1
            while j > 0 and buf[j - 1] != " ":
                j -= 1
            del buf[j:pos]
            st["pos"] = j
        elif name == "tab":
            c = self.irc.get(self.irc_sel[0])
            if c:
                if st["cand"] is None:
                    j = pos
                    while j > 0 and buf[j - 1] != " ":
                        j -= 1
                    word = "".join(buf[j:pos])
                    names = [n for n, _ in c.nick_list(self.irc_sel[1])]
                    hits = sorted([n for n in names if n.lower().startswith(word.lower().rstrip(":"))], key=str.lower) if word else []
                    if hits:
                        st["cand"] = {"start": j, "end": pos, "hits": hits, "i": -1}
                cd = st["cand"]
                if cd:
                    cd["i"] = (cd["i"] + 1) % len(cd["hits"])
                    rep = cd["hits"][cd["i"]] + (": " if cd["start"] == 0 else " ")
                    buf[cd["start"]:cd["end"]] = list(rep)
                    cd["end"] = cd["start"] + len(rep)
                    st["pos"] = cd["end"]
        elif ch:
            buf.insert(pos, ch)
            st["pos"] = pos + 1
        return None

    def irc_mouse(self, full=False, ev=None):
        """Mouse over the chat pane or screen. True when the event was used."""
        if ev is None:
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                return False
        else:
            mx, my, bstate = ev
        hit = None
        for kind, x0, y0, x1, y1, pl in self.irc_hits:
            if x0 <= mx < x1 and y0 <= my < y1:
                hit = (kind, pl)
                break
        if hit is None:
            return False
        kind, pl = hit
        up = getattr(curses, "BUTTON4_PRESSED", 0)
        down = getattr(curses, "BUTTON5_PRESSED", 0)
        if up and bstate & up:
            if kind == "buf":
                self.irc_select(step=-1)
            else:
                self.irc_scroll += 3
            return True
        if down and bstate & down:
            if kind == "buf":
                self.irc_select(step=1)
            else:
                self.irc_scroll = max(0, self.irc_scroll - 3)
            return True
        if not bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
            return True
        if kind == "buf":
            self.irc_select(to=pl)
        elif kind == "nick":
            c, key = self.irc_current()
            if c and pl.lower() != c.nick.lower():
                c.buf(pl, "query")
                self.irc_select(to=(c.name, pl.lower()))
                self.say("private chat with %s" % pl, "accent2", 2)
        if not full:
            self.focus = "chat"
        return True

    def irc_screen(self):
        self.irc_current()
        st = {"dirty": True, "sig": None}

        def render():
            scr = self.scr
            scr.erase()
            H, W = scr.getmaxyx()
            if H < 8 or W < 30:
                self.put(0, 0, "terminal too small", self.attr("err"))
                return
            self.irc_hits = []
            c, _ = self.irc_current()
            right = "%s as %s  %s" % (c.name, c.nick, c.status) if c else ""
            self.screen_bar(W, "irc", right)
            self.irc_draw_pane(1, 0, H - 2, W, "full")
            self.screen_foot(H, W, "enter send  tab nick  ctrl-n/p buffer  ctrl-s dock beside tasks  esc back  /help")
            if self.msg and time.time() < self.msg_until:
                self.fill(H - 1, 0, W, self.attr("fg", "bar_bg"))
                self.put(H - 1, 1, self.msg, self.attr(self.msg_kind, "bar_bg", bold=True), W - 2)

        def revsig():
            return tuple(c.rev for c in self.irc.values()) + (self.irc_sel, self.msg)

        self.backdrop = render
        self.tick_override = 200
        try:
            while True:
                sig = revsig()
                if st["dirty"] or sig != st["sig"]:
                    render()
                    self.present()
                    st["sig"], st["dirty"] = sig, False
                name, ch = self.read_key()
                if name == "tick":
                    continue
                st["dirty"] = True
                if name == "resize":
                    continue
                if name == "mouse":
                    self.irc_mouse(full=True)
                    continue
                r = self.irc_input_key(name, ch, True)
                if r == "leave":
                    break
                if r == "dock":
                    self.irc_show_pane()
                    break
        finally:
            for c in self.irc.values():
                if c.viewing is not None:
                    c.view(None)
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
                    init = "status:%s due:%s path:%s %s" % (meta.get("status", "active"), meta.get("due", "") or "none",
                                                          meta.get("path", "") or "none", meta.get("desc", ""))
                    text = self.prompt("%s: status:active|paused due:DATE path:FOLDER then a description" % nm, init)
                    if text is not None:
                        m = {"status": "active", "due": "", "desc": [], "path": ""}
                        for tok in text.split():
                            if tok.startswith("status:") and tok[7:] in self.PROJECT_STATUS:
                                m["status"] = tok[7:]
                            elif tok.startswith("path:"):
                                m["path"] = "" if tok[5:] == "none" else tok[5:]
                            elif tok.startswith("due:"):
                                try:
                                    pd = parse_date(tok[4:], td)
                                    m["due"] = pd.isoformat() if pd else ""
                                except ValueError:
                                    pass
                            else:
                                m["desc"].append(tok)
                        with self.edit():
                            newm = {"status": m["status"], "due": m["due"], "desc": " ".join(m["desc"])}
                            if m["path"]:
                                newm["path"] = m["path"]
                            self.store.projects[nm] = newm
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

    # ----- git: data sync, linking, TODO scanning -----

    def on_store_save(self, lines):
        if self.opts.get("git_sync") and self.sync.enabled():
            self.sync.mark(lines)

    def startup_sync(self):
        """Background start: make sure the data folder is a repo and pull when asked to."""
        def work():
            if self.sync.setup() and self.sync.push:
                self.sync.pull()
        threading.Thread(target=work, daemon=True).start()

    def task_repo(self, t):
        g = t.get("git") or {}
        meta = self.store.projects.get(t["project"], {}) if t["project"] else {}
        for cand in (meta.get("path"), g.get("repo"), os.getcwd()):
            root = git_root(cand) if cand else None
            if root:
                return root
        return None

    def git_jobs(self):
        jobs = []
        for t in self.store.tasks:
            g = t.get("git") or {}
            if g.get("branch") and g.get("repo") and not t["done"]:
                jobs.append({"id": t["id"], "repo": g["repo"], "branch": g["branch"], "base": g.get("base", "")})
        repos = {m["path"] for m in self.store.projects.values() if m.get("path")}
        repos |= {(t.get("git") or {}).get("repo") for t in self.store.tasks if (t.get("git") or {}).get("repo")}
        return jobs, sorted(r for r in repos if r)

    def gh_jobs(self):
        """Open tasks linked to GitHub, grouped as {(dir, kind): [task ids]}."""
        groups = {}
        for t in self.store.tasks:
            g = t.get("gh") or {}
            if g.get("number") and g.get("dir") and not t["done"]:
                groups.setdefault((g["dir"], g.get("kind", "issue")), []).append(t["id"])
        return groups

    def git_refresh(self, force=False):
        """Start a background check of linked branches and commit references."""
        if self.git_thread is not None and self.git_thread.is_alive():
            return
        jobs, repos = self.git_jobs()
        ghg = self.gh_jobs()
        if not jobs and not repos and not ghg:
            if force:
                self.say("nothing linked to git yet", "dim")
            return
        self.git_force = force

        def work():
            res = {"states": {}, "mentions": [], "gh": {}}
            for (gdir, kind), ids in ghg.items():
                items, _err = gh_list(gdir, kind, mine=False, state="all", limit=200)
                by = {i["number"]: i["state"] for i in items}
                for tid in ids:
                    num = self.store.get(tid)["gh"]["number"]
                    if num in by:
                        res["gh"][tid] = by[num]
            for j in jobs:
                res["states"][j["id"]] = git_probe(j)
            for r in repos:
                root = git_root(r)
                if root:
                    res["mentions"] += [(root,) + row for row in git_mentions(root)]
            self.git_results.append(res)
        self.git_thread = threading.Thread(target=work, daemon=True)
        self.git_thread.start()

    def git_apply(self):
        mins = int(self.opts.get("git_refresh", 5) or 0)
        if mins and time.time() >= self.git_next:
            self.git_next = time.time() + mins * 60
            self.git_refresh()
        if not self.git_results:
            return
        res = self.git_results.pop(0)
        done_now, linked = [], 0
        with self.edit():
            for tid, state in res.get("gh", {}).items():
                t = self.store.get(tid)
                if not t:
                    continue
                t["gh"]["state"] = state
                if gh_done_state(t["gh"].get("kind", "issue"), state) and not t["done"] and self.opts.get("git_auto_done", True):
                    self.complete(t, True)
                    done_now.append(t["title"])
            for tid, state in res["states"].items():
                t = self.store.get(tid)
                if not t:
                    continue
                g = t.setdefault("git", {})
                g["state"] = state
                if state == "merged" and not t["done"] and self.opts.get("git_auto_done", True):
                    self.complete(t, True)
                    done_now.append(t["title"])
            for root, sha, subj, refs in res["mentions"]:
                for tid, closes in refs.items():
                    t = self.store.get(tid)
                    if not t:
                        continue
                    g = t.setdefault("git", {})
                    known = g.setdefault("commits", [])
                    entry = "%s %s" % (sha, subj)
                    if any(c.split(" ", 1)[0] == sha for c in known):
                        continue
                    known.insert(0, entry)
                    del known[20:]
                    g.setdefault("repo", root)
                    linked += 1
                    if closes and not t["done"] and self.opts.get("git_auto_done", True):
                        self.complete(t, True)
                        done_now.append(t["title"])
        if done_now:
            self.say("done from git: " + clip(", ".join(done_now), 60), "ok", 6)
        elif linked:
            self.say("%d commit%s linked to tasks" % (linked, "" if linked == 1 else "s"), "accent2", 4)
        elif self.git_force:
            self.say("git links are up to date", "dim")
        self.git_force = False

    def act_git(self):
        t = self.current()
        opts = []
        opts.append(("Find TODOs in a project folder", self.act_git_todos))
        opts.append(("Import my GitHub issues", lambda: self.act_gh_import("issue")))
        opts.append(("Import my GitHub pull requests", lambda: self.act_gh_import("pr")))
        if t:
            g = t.get("git") or {}
            opts.append(("Link a branch to this task", lambda: self.act_git_branch(t)))
            opts.append(("Link a commit to this task", lambda: self.act_git_commit(t)))
            opts.append(("Link a GitHub issue or PR to this task", lambda: self.act_gh_link(t)))
            if g.get("branch") or g.get("commits") or t.get("gh"):
                opts.append(("Unlink git from this task", lambda: self.act_git_unlink(t)))
            if t["project"]:
                opts.append(("Set folder for @%s" % t["project"], lambda: self.act_git_path(t["project"])))
        opts.append(("Check branches and commits now", lambda: self.git_refresh(True)))
        opts.append(("Time travel through data history", self.act_travel))
        if self.sync.enabled():
            opts.append(("Sync data now (commit%s)" % (" and push" if self.opts.get("git_push") else ""), self.act_sync_now))
        else:
            opts.append(("Track data folder in git", self.act_sync_setup))
        i = self.menu("git", [o[0] for o in opts])
        if i is not None:
            opts[i][1]()

    def act_git_path(self, project=None):
        if project is None:
            names = project_names(self.store)
            if not names:
                self.say("no projects yet", "dim")
                return
            i = self.menu("project folder for", names)
            if i is None:
                return
            project = names[i]
        cur = self.store.projects.get(project, {}).get("path", "")
        text = self.prompt("folder for @%s (git repo or source folder, empty clears)" % project, cur or os.getcwd())
        if text is None:
            return
        text = text.strip()
        if text and not os.path.isdir(os.path.expanduser(text)):
            self.say("that folder does not exist", "err")
            return
        with self.edit():
            meta = self.store.projects.setdefault(project, {})
            if text:
                meta["path"] = text
            else:
                meta.pop("path", None)
        self.say("folder saved for @" + project, "ok")

    def act_git_branch(self, t):
        repo = self.task_repo(t)
        if not repo:
            self.say("no git repo found. set a project folder with the git menu", "err")
            return
        branches = git_branches(repo)
        cur = git_current_branch(repo)
        make = git_slug(t["title"], t["id"])
        labels = ["new branch: " + make] + [("* " if b == cur else "  ") + b for b in branches]
        i = self.menu("link branch (%s)" % os.path.basename(repo), labels)
        if i is None:
            return
        if i == 0:
            if not self.confirm("create and switch to %s?" % make):
                return
            rc, out = git_run(["switch", "-c", make], repo)
            if rc != 0:
                self.say("git: " + clip(out.strip().split("\n")[-1], 60), "err", 5)
                return
            name = make
        else:
            name = branches[i - 1]
        base = git_rev(repo, "refs/heads/" + name)
        with self.edit():
            g = t.setdefault("git", {})
            g.update({"repo": repo, "branch": name, "base": base, "state": "active"})
        self.say("linked %s" % name, "ok")
        self.git_next = 0.0

    def act_git_commit(self, t):
        repo = self.task_repo(t)
        if not repo:
            self.say("no git repo found. set a project folder with the git menu", "err")
            return
        rows = git_log(repo, 40)
        if not rows:
            self.say("no commits found", "dim")
            return
        i = self.menu("link commit", ["%s  %s" % (a, clip(b, 60)) for a, b in rows])
        if i is None:
            return
        with self.edit():
            g = t.setdefault("git", {})
            g.setdefault("repo", repo)
            known = g.setdefault("commits", [])
            if not any(c.split(" ", 1)[0] == rows[i][0] for c in known):
                known.insert(0, "%s %s" % rows[i])
        self.say("commit linked", "ok")

    def gh_ready(self):
        if not shutil.which("gh"):
            self.say("the GitHub CLI (gh) is not installed. install it and run gh auth login", "err", 6)
            return False
        return True

    def act_gh_import(self, kind):
        if not self.gh_ready():
            return
        pname, path = self.pick_project_folder("GitHub %ss for" % kind)
        if not pname:
            return
        gdir = os.path.abspath(os.path.expanduser(path))
        self.say("asking GitHub...", "dim")
        self.draw()
        self.present()
        items, err = gh_list(gdir, kind, mine=True)
        if err:
            self.say("gh: " + err, "err", 6)
            return
        label = "issue" if kind == "issue" else "PR"
        rows = [{"key": "%s|%s|%d" % (gdir, kind, i["number"]), "kind": "#%d" % i["number"],
                 "text": ("[draft] " if i["draft"] else "") + i["title"], "loc": " ".join(i["labels"][:3]), "item": i}
                for i in items]

        def tracked():
            return {"%s|%s|%d" % (t["gh"].get("dir"), t["gh"].get("kind"), t["gh"].get("number")) for t in self.store.tasks if t.get("gh")}

        def make(chosen):
            for r in chosen:
                i = r["item"]
                t = self.store.add(i["title"])
                t["project"] = pname
                t["tags"] = [label.lower()] + [re.sub(r"\s+", "-", x.lower()) for x in i["labels"][:2]]
                t["notes"] = i["url"]
                t["gh"] = {"dir": gdir, "kind": kind, "number": i["number"], "url": i["url"], "state": i["state"]}
            return len(chosen)

        self.import_screen("my GitHub %ss in @%s" % (label, pname), rows, make, tracked=tracked,
                           hint="closed or merged ones complete their task")

    def act_gh_link(self, t):
        if not self.gh_ready():
            return
        gdir = self.task_repo(t)
        if not gdir:
            self.say("no git repo found. set a project folder with the git menu", "err")
            return
        self.say("asking GitHub...", "dim")
        self.draw()
        self.present()
        issues, e1 = gh_list(gdir, "issue", mine=False)
        prs, e2 = gh_list(gdir, "pr", mine=False)
        items = prs + issues
        if not items:
            self.say("gh: " + (e1 or e2 or "no open issues or PRs"), "err" if (e1 or e2) else "dim", 6)
            return
        i = self.menu("link to", ["%s #%-5d %s" % ("PR " if x["kind"] == "pr" else "iss", x["number"], clip(x["title"], 56)) for x in items])
        if i is None:
            return
        x = items[i]
        with self.edit():
            t["gh"] = {"dir": gdir, "kind": x["kind"], "number": x["number"], "url": x["url"], "state": x["state"]}
            if x["url"] and x["url"] not in t["notes"]:
                t["notes"] = (x["url"] + "\n" + t["notes"]).rstrip()
        self.say("linked %s #%d" % (x["kind"], x["number"]), "ok")
        self.git_next = 0.0

    def act_git_unlink(self, t):
        with self.edit():
            t["git"] = {}
            t["gh"] = {}
        self.say("git links removed", "ok")

    def act_sync_setup(self):
        d = self.sync.dir
        if not self.confirm("track %s in git?" % clip(d, 40)):
            return
        if self.sync.setup():
            self.opts["git_sync"] = True
            self.persist("git_sync", True)
            self.say("data folder is now a git repo", "ok")
            if not self.sync.has_remote():
                self.say("data folder is now a git repo. add a remote with git remote add origin URL, then enable Push and Pull in settings", "accent2", 8)
        else:
            self.say("could not set up git: " + self.sync.detail, "err", 5)

    def act_sync_now(self):
        self.sync.mark(["manual sync"], delay=0)
        self.say("syncing...", "dim")

    def pick_project_folder(self, title):
        """Choose a project folder. Returns (project name, folder) or (None, None)."""
        cands = sorted((n, m["path"]) for n, m in self.store.projects.items() if m.get("path"))
        view_p = self.view[2:] if self.view.startswith("p:") else ""
        names = [n for n, _ in cands]
        labels = ["%s  (%s)" % (n, clip(p, 40)) for n, p in cands] + ["another folder..."]
        i = self.menu(title, labels, names.index(view_p) if view_p in names else 0)
        if i is None:
            return None, None
        if i < len(cands):
            return cands[i]
        path = self.prompt("folder", os.getcwd())
        if not path or not os.path.isdir(os.path.expanduser(path.strip())):
            self.say("that folder does not exist", "err")
            return None, None
        path = path.strip()
        pname = self.prompt("project name for imported tasks", re.sub(r"\W+", "-", os.path.basename(os.path.abspath(os.path.expanduser(path)))).strip("-"))
        if not pname or not pname.strip():
            return None, None
        pname = pname.strip().replace(" ", "-")
        with self.edit():
            self.store.projects.setdefault(pname, {})["path"] = path
        return pname, path

    def act_git_todos(self):
        pname, path = self.pick_project_folder("find TODOs in")
        if not pname:
            return
        repo = os.path.abspath(os.path.expanduser(path))
        self.say("scanning %s..." % clip(repo, 40), "dim")
        self.draw()
        found = scan_todos(repo, self.opts.get("todo_markers"))
        found.sort(key=lambda f: (f["file"], f["line"]))
        S = {"i": 0, "top": 0, "sel": set()}

        def tracked():
            return {t["src"]["key"]: t for t in self.store.tasks
                    if (t.get("src") or {}).get("key") and t["src"].get("repo") == repo}

        def resolved():
            keys = {f["key"] for f in found}
            return [t for k, t in tracked().items() if k not in keys and not t["done"]]

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            tr = tracked()
            new = [f for f in found if f["key"] not in tr]
            self.screen_bar(W, "todos in @" + pname, "%d found  %d new  %d selected " % (len(found), len(new), len(S["sel"])))
            room = max(1, H - 3)
            S["i"] = max(0, min(S["i"], len(found) - 1))
            S["top"] = max(0, min(S["top"], max(0, len(found) - room)))
            if S["i"] < S["top"]:
                S["top"] = S["i"]
            if S["i"] >= S["top"] + room:
                S["top"] = S["i"] - room + 1
            if not found:
                self.put(2, 2, "no TODO, FIXME, HACK or XXX comments found.", self.attr("dim"))
            for r in range(room):
                k = S["top"] + r
                if k >= len(found):
                    break
                f = found[k]
                on = k == S["i"]
                known = f["key"] in tr
                mark = "[x]" if k in S["sel"] else ("[=]" if known else "[ ]")
                role = "dim" if known else "fg"
                bg = "sel_bg" if on else "bg"
                self.fill(1 + r, 0, W, self.attr(role, bg))
                x = self.put(1 + r, 2, mark + " ", self.attr("ok" if k in S["sel"] else role, bg))
                x = self.put(1 + r, x, pad(f["kind"], 5) + " ", self.attr("p3" if f["kind"] == "FIXME" else "accent2", bg, bold=True))
                loc = clip("%s:%d" % (f["file"], f["line"]), 36)
                x = self.put(1 + r, x, pad(loc, 36) + " ", self.attr("dim", bg))
                self.put(1 + r, x, f["text"], self.attr(role, bg, bold=on), W - x - 1)
            gone = len(resolved())
            hint = "j/k move  space select  a all new  enter import  r rescan  q close"
            if gone:
                hint = "%d resolved in code: c completes them   " % gone + hint
            self.screen_foot(H, W, hint)

        def handle(name, ch):
            if name in ("q", "esc", "ctrl-c"):
                return True
            if name in ("j", "down"):
                S["i"] += 1
            elif name in ("k", "up"):
                S["i"] -= 1
            elif name in ("g", "home"):
                S["i"] = 0
            elif name in ("G", "end"):
                S["i"] = len(found) - 1
            elif name in ("ctrl-d", "pagedown"):
                S["i"] += 10
            elif name in ("ctrl-u", "pageup"):
                S["i"] -= 10
            elif name == "space" and found:
                if found[S["i"]]["key"] not in tracked():
                    S["sel"] ^= {S["i"]}
                S["i"] += 1
            elif name == "a":
                tr = tracked()
                S["sel"] = {k for k, f in enumerate(found) if f["key"] not in tr}
            elif name == "enter" and found:
                tr = tracked()
                pick = sorted(S["sel"]) or [S["i"]]
                chosen = [found[k] for k in pick if found[k]["key"] not in tr]
                if not chosen:
                    self.say("already tracked", "dim")
                    return False
                with self.edit():
                    for f in chosen:
                        title = f["text"] if f["kind"] == "TODO" else "%s: %s" % (f["kind"], f["text"])
                        t = self.store.add(title[:140])
                        t["project"] = pname
                        t["tags"] = ["todo"]
                        t["notes"] = "%s:%d" % (f["file"], f["line"])
                        t["prio"] = 1 if f["kind"] == "FIXME" else 0
                        t["src"] = {"repo": repo, "file": f["file"], "line": f["line"], "key": f["key"]}
                S["sel"] = set()
                self.say("imported %d task%s" % (len(chosen), "" if len(chosen) == 1 else "s"), "ok")
            elif name == "c":
                gone = resolved()
                if gone and self.confirm("complete %d task%s whose comment is gone?" % (len(gone), "" if len(gone) == 1 else "s")):
                    with self.edit():
                        for t in gone:
                            self.complete(t, True)
                    self.say("completed %d" % len(gone), "ok")
            elif name == "r":
                found[:] = sorted(scan_todos(repo, self.opts.get("todo_markers")), key=lambda f: (f["file"], f["line"]))
                S["sel"] = set()
                self.say("rescanned", "dim")
            return False

        self.screen_loop(render, handle)

    # ----- weekly review -----

    def review_data(self):
        td = today()
        return review_data(self.store, td)

    def act_review(self):
        steps = ["wins", "slipped", "stale", "ahead", "reflect"]
        S = {"step": 0, "i": 0, "top": 0, "text": None}

        def items(d):
            return {"slipped": d["slipped"], "stale": d["stale"], "ahead": d["ahead"]}.get(steps[S["step"]], [])

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            d = self.review_data()
            self.screen_bar(W, "weekly review", "step %d of %d  %s " % (S["step"] + 1, len(steps), steps[S["step"]]))
            x = 2
            for k, nm in enumerate(steps):
                on = k == S["step"]
                x = self.put(1, x, " %d %s " % (k + 1, nm), self.attr("accent" if on else "dim", "sel_bg" if on else "bg", bold=on)) + 1
            step = steps[S["step"]]
            td = today()
            if step == "wins":
                self.tiles(3, [(str(d["done"]), "done in 7 days", "ok"), (str(d["prev"]), "the 7 days before", "dim"),
                               (fmt_duration(d["time"]) if d["time"] else "0m", "time tracked", "accent2"),
                               (str(d["streak"]), "day streak", "ok" if d["streak"] else "dim")])
                rows = d["by_project"][:6]
                self.put(7, 2, "by project", self.attr("accent", bold=True))
                self.hbars(8, 2, min(W - 6, 60), [(k, v, str(v)) for k, v in rows], "accent2", 1.0)
                y = 9 + max(1, len(rows))
                self.put(y, 2, "finished", self.attr("accent", bold=True))
                for r, (title, proj) in enumerate(d["titles"][:max(0, H - y - 3)]):
                    self.put(y + 1 + r, 4, ("%s %s" % (self.sym["check_on"], title)) + ("  @" + proj if proj else ""),
                             self.attr("done"), W - 6)
            elif step == "reflect":
                self.put(3, 2, "write the review into today's journal.", self.attr("accent", bold=True))
                self.put(4, 2, "e writes it (you can edit the text first)   saved reviews: %s" % (self.state.get("last_review") or "never"),
                         self.attr("dim"), W - 4)
                preview = review_text(d, td).split("\n")
                for r, ln in enumerate(preview[:max(0, H - 8)]):
                    self.put(6 + r, 4, ln, self.attr("fg"), W - 6)
            else:
                lst = items(d)
                blurb = {"slipped": "overdue. decide for each: do it, move it or drop it.",
                         "stale": "open for a while with no due date and no recent changes. keep, snooze or drop.",
                         "ahead": "due in the next 7 days. %s planned" % (fmt_duration(d["ahead_est"]) if d["ahead_est"] else "no estimates")}[step]
                self.put(3, 2, "%d tasks: %s" % (len(lst), blurb), self.attr("accent", bold=True), W - 4)
                room = max(1, H - 7)
                S["i"] = max(0, min(S["i"], len(lst) - 1))
                if S["i"] < S["top"]:
                    S["top"] = S["i"]
                if S["i"] >= S["top"] + room:
                    S["top"] = S["i"] - room + 1
                if not lst:
                    self.put(5, 4, "nothing here. nice.", self.attr("ok"))
                for r in range(room):
                    k = S["top"] + r
                    if k >= len(lst):
                        break
                    t = lst[k]
                    on = k == S["i"]
                    bg = "sel_bg" if on else "bg"
                    self.fill(5 + r, 0, W, self.attr("fg", bg))
                    due = t["due"] or "no date"
                    role = "overdue" if (t["due"] and t["due"] < td.isoformat()) else "dim"
                    x = self.put(5 + r, 2, pad(due, 10) + " ", self.attr(role, bg))
                    extra = ("  @" + t["project"]) if t["project"] else ""
                    age = "  %dd old" % d["age"].get(t["id"], 0) if step == "stale" else ""
                    self.put(5 + r, x, t["title"] + extra + age, self.attr("fg", bg, bold=on), W - x - 2)
            foot = "tab next step   shift-tab back   q close"
            if step in ("slipped", "stale", "ahead"):
                foot = "j/k  r reschedule  t tomorrow  w +1 week  s snooze 1w  x done  D drop   " + foot
            self.screen_foot(H, W, foot)

        def act(t, op):
            td = today()
            if op == "x":
                with self.edit():
                    self.complete(t, True)
            elif op == "t":
                with self.edit():
                    t["due"] = (td + dt.timedelta(days=1)).isoformat()
            elif op == "w":
                with self.edit():
                    t["due"] = (td + dt.timedelta(days=7)).isoformat()
            elif op == "s":
                with self.edit():
                    t["snooze"] = (td + dt.timedelta(days=7)).isoformat()
            elif op == "r":
                text = self.prompt("new due date  (fri, +3d, 12-25, none)")
                if not text:
                    return
                try:
                    nd = parse_date(text.strip(), td)
                except ValueError:
                    self.say("could not read that date", "err")
                    return
                with self.edit():
                    t["due"] = nd.isoformat() if nd else None
            elif op == "D":
                if self.confirm("delete: " + clip(t["title"], 40) + "?"):
                    with self.edit():
                        self.store.delete([t["id"]])

        def handle(name, ch):
            if name in ("q", "esc", "ctrl-c"):
                return True
            if name == "tab":
                S["step"] = (S["step"] + 1) % len(steps)
                S["i"] = S["top"] = 0
                return False
            if name == "shift-tab":
                S["step"] = (S["step"] - 1) % len(steps)
                S["i"] = S["top"] = 0
                return False
            if name in ("1", "2", "3", "4", "5"):
                S["step"], S["i"], S["top"] = int(name) - 1, 0, 0
                return False
            d = self.review_data()
            if steps[S["step"]] == "reflect":
                if name in ("e", "enter"):
                    td = today()
                    text = self.edit_text("weekly review", review_text(d, td), footer="saved to today's journal")
                    if text and text.strip():
                        iso = td.isoformat()
                        cur = self.store.journal.get(iso, "").rstrip()
                        with self.edit():
                            self.store.journal[iso] = (cur + "\n\n" if cur else "") + text.rstrip()
                        self.state["last_review"] = iso
                        self.persist("last_review", iso)
                        self.say("review saved to the journal", "ok")
                return False
            lst = items(d)
            if name in ("j", "down"):
                S["i"] += 1
            elif name in ("k", "up"):
                S["i"] -= 1
            elif name in ("x", "t", "w", "s", "r", "D") and lst:
                S["i"] = max(0, min(S["i"], len(lst) - 1))
                act(lst[S["i"]], name)
            return False

        self.screen_loop(render, handle)

    # ----- generic import picker, brain dump, bulk edit -----

    def import_screen(self, title, rows, make, tracked=None, preselect=False, hint=""):
        """Fullscreen checklist for importing things as tasks.

        rows: dicts with text (required), kind, loc, depth and key. tracked() returns keys already
        imported. make(chosen rows) creates the tasks and returns how many it made."""
        S = {"i": 0, "top": 0, "sel": set(range(len(rows))) if preselect else set()}

        def known():
            return tracked() if tracked else set()

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            tr = known()
            new = sum(1 for r in rows if r.get("key") not in tr)
            self.screen_bar(W, title, "%d found  %d new  %d selected " % (len(rows), new, len(S["sel"])))
            room = max(1, H - 3)
            S["i"] = max(0, min(S["i"], len(rows) - 1))
            S["top"] = max(0, min(S["top"], max(0, len(rows) - room)))
            if S["i"] < S["top"]:
                S["top"] = S["i"]
            if S["i"] >= S["top"] + room:
                S["top"] = S["i"] - room + 1
            if not rows:
                self.put(2, 2, "nothing found.", self.attr("dim"))
            for r in range(room):
                k = S["top"] + r
                if k >= len(rows):
                    break
                row = rows[k]
                on = k == S["i"]
                is_known = row.get("key") in tr
                role = "dim" if is_known else "fg"
                bg = "sel_bg" if on else "bg"
                self.fill(1 + r, 0, W, self.attr(role, bg))
                mark = "[x]" if k in S["sel"] else ("[=]" if is_known else "[ ]")
                x = self.put(1 + r, 2, mark + " ", self.attr("ok" if k in S["sel"] else role, bg))
                if row.get("kind"):
                    x = self.put(1 + r, x, pad(row["kind"], 6) + " ", self.attr("accent2", bg, bold=True))
                x += 2 * row.get("depth", 0)
                loc = row.get("loc", "")
                lw = min(cell_len(loc), max(0, W // 3)) if loc else 0
                self.put(1 + r, x, row["text"], self.attr(role, bg, bold=on), max(4, W - x - lw - 3))
                if loc:
                    self.put(1 + r, W - lw - 2, clip(loc, lw), self.attr("dim", bg), lw)
            self.screen_foot(H, W, (hint + "   " if hint else "") + "j/k move  space select  a all  n none  enter import  q close")

        def handle(name, ch):
            if name in ("q", "esc", "ctrl-c"):
                return True
            if name in ("j", "down"):
                S["i"] += 1
            elif name in ("k", "up"):
                S["i"] -= 1
            elif name in ("g", "home"):
                S["i"] = 0
            elif name in ("G", "end"):
                S["i"] = len(rows) - 1
            elif name in ("ctrl-d", "pagedown"):
                S["i"] += 10
            elif name in ("ctrl-u", "pageup"):
                S["i"] -= 10
            elif name == "space" and rows:
                S["sel"] ^= {S["i"]}
                S["i"] += 1
            elif name == "a":
                tr = known()
                S["sel"] = {k for k, r in enumerate(rows) if r.get("key") not in tr}
            elif name == "n":
                S["sel"] = set()
            elif name == "enter" and rows:
                tr = known()
                pick = sorted(S["sel"]) or [S["i"]]
                chosen = [rows[k] for k in pick if rows[k].get("key") not in tr]
                if not chosen:
                    self.say("nothing new selected", "dim")
                    return False
                with self.edit():
                    n = make(chosen)
                self.say("imported %d task%s" % (n, "" if n == 1 else "s"), "ok")
                return True
            return False

        self.screen_loop(render, handle)

    def act_dump(self):
        vp = self.view[2:] if self.view.startswith("p:") else ""
        text = self.edit_text("brain dump", "", footer="one per line, indent = subtask, ctrl-s to continue")
        if text is None or not text.strip():
            return
        items = parse_dump(text, vp)
        if not items:
            self.say("nothing to import", "dim")
            return
        rows = []
        for n, it in enumerate(items):
            bits = []
            if it["due"] is not UNSET and it["due"]:
                bits.append("due " + it["due"][5:])
            if it["project"]:
                bits.append("@" + it["project"])
            bits += ["#" + g for g in it["tags"]]
            if it["prio"]:
                bits.append("!" * it["prio"])
            rows.append({"key": n, "text": it["title"], "depth": it["depth"], "loc": " ".join(bits)})

        def make(chosen):
            keep = {r["key"] for r in chosen}
            made = create_from_items(self.store, [items[i] for i in sorted(keep)])
            for t in made[:1]:
                self.cur_id = t["id"]
            return len(made)

        self.import_screen("brain dump", rows, make, preselect=True)

    def select_matching(self):
        text = self.prompt("select tasks matching  (#work due:overdue !2+ ...)", "", hist="filter")
        if not text or not text.strip():
            return False
        try:
            f = compile_query(text, self.store)
        except Exception:
            self.say("could not read that filter", "err")
            return False
        td = today()
        want_done = "is:done" in text
        self.selected = {t["id"] for t in self.store.tasks if f(t, td) and (want_done or not t["done"])}
        self.say("%d selected" % len(self.selected), "ok" if self.selected else "dim")
        return bool(self.selected)

    def act_bulk(self):
        while True:
            ts = self.targets()
            n = len(self.selected)
            opts = [("select tasks matching a filter...", "select")]
            if ts:
                opts += [("set project...", "project"), ("add tags...", "tag+"), ("remove tags...", "tag-"),
                         ("set due date...", "due"), ("clear due date", "nodue"),
                         ("priority: none", "p0"), ("priority: low", "p1"), ("priority: medium", "p2"), ("priority: high", "p3"),
                         ("snooze...", "snooze"), ("mark done", "done"), ("reopen", "open"), ("delete", "delete")]
            title = "bulk edit: %s" % ("%d selected" % n if n else ("1 task" if ts else "no tasks"))
            i = self.menu(title, [o[0] for o in opts])
            if i is None:
                return
            op = opts[i][1]
            if op == "select":
                if not self.select_matching():
                    return
                continue
            break
        ids = [t["id"] for t in ts]
        td = today()
        if op == "snooze":
            self.act_snooze()
            return
        if op == "delete":
            self.act_delete()
            return
        if op in ("done", "open"):
            if op == "done" and not self.blocked_gate(ts):
                return
            with self.edit():
                for t in ts:
                    self.complete(t, op == "done")
            self.say("%d updated" % len(ts), "ok")
            return
        value = None
        if op == "project":
            value = self.prompt("project for %d tasks  (empty clears)" % len(ts))
            if value is None:
                return
            value = value.strip().lstrip("@").replace(" ", "-")
        elif op in ("tag+", "tag-"):
            value = self.prompt("tags to %s" % ("add" if op == "tag+" else "remove"))
            if not value or not value.strip():
                return
            value = [w.lower().lstrip("#") for w in value.split() if w.strip("#")]
        elif op == "due":
            text = self.prompt("due date for %d tasks  (fri, +3d, 12-25, none)" % len(ts))
            if not text or not text.strip():
                return
            try:
                d = parse_date(text.strip(), td)
            except ValueError:
                self.say("could not read that date", "err")
                return
            value = d.isoformat() if d else None
        with self.edit():
            for t in ts:
                if op == "project":
                    t["project"] = value
                elif op == "tag+":
                    t["tags"] += [g for g in value if g not in t["tags"]]
                elif op == "tag-":
                    t["tags"] = [g for g in t["tags"] if g not in value]
                elif op == "due":
                    t["due"] = value
                elif op == "nodue":
                    t["due"] = None
                elif op.startswith("p") and op[1:].isdigit():
                    t["prio"] = int(op[1:])
        self.say("%d updated" % len(ids), "ok")

    # ----- calendar events from .ics files -----

    def ics_cache_path(self, src):
        import hashlib
        return os.path.join(os.path.dirname(self.store.path), "ics-%s.ics" % hashlib.sha1(src.encode()).hexdigest()[:8])

    @staticmethod
    def ics_url(src):
        src = src.strip()
        if src.startswith("webcal://"):
            src = "https://" + src[len("webcal://"):]
        return src

    def ics_read(self, path):
        try:
            with open(os.path.expanduser(path), "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    def ics_fetch(self, src):
        """Text of one calendar source. Web calendars are downloaded and cached in the data folder."""
        src = self.ics_url(src)
        if not re.match(r"^https?://", src):
            return self.ics_read(src)
        cache = self.ics_cache_path(src)
        try:
            import urllib.request
            req = urllib.request.Request(src, headers={"User-Agent": "synth"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read().decode("utf-8", "replace")
            if "BEGIN:VCALENDAR" in data:
                with contextlib.suppress(OSError):
                    with open(cache, "w", encoding="utf-8") as fh:
                        fh.write(data)
                return data
        except Exception:
            pass
        return self.ics_read(cache)

    def ics_cached(self, src):
        src = self.ics_url(src)
        return self.ics_read(self.ics_cache_path(src) if re.match(r"^https?://", src) else src)

    def ics_rebuild(self, events):
        td = today()
        self.ics_raw = events
        self.ics_occ = expand_events(events, td - dt.timedelta(days=2), td + dt.timedelta(days=150))
        self.ics_day = td.isoformat()

    def ics_poll(self):
        srcs = [x for x in (self.opts.get("ics_sources") or []) if isinstance(x, str) and x.strip()]
        if not srcs:
            if self.ics_occ:
                self.ics_occ, self.ics_raw = [], []
            return
        if self.ics_loaded is not None:
            events, self.ics_loaded = self.ics_loaded, None
            self.ics_rebuild(events)
            return
        if self.ics_day != today().isoformat() and self.ics_raw:
            self.ics_rebuild(self.ics_raw)
        if not self.ics_started:
            self.ics_started = True
            events = []
            for sx in srcs:
                events += parse_ics(self.ics_cached(sx))
            self.ics_rebuild(events)
        mins = max(1, int(self.opts.get("ics_refresh", 30) or 30))
        if time.time() >= self.ics_next and (self.ics_thread is None or not self.ics_thread.is_alive()):
            self.ics_next = time.time() + mins * 60

            def work():
                evs = []
                for sx in srcs:
                    evs += parse_ics(self.ics_fetch(sx))
                self.ics_loaded = evs
            self.ics_thread = threading.Thread(target=work, daemon=True)
            self.ics_thread.start()

    def events_on(self, date):
        out = []
        for o in self.ics_occ:
            last = (o["end"] - dt.timedelta(seconds=1)).date() if o["end"] > o["start"] else o["start"].date()
            if o["start"].date() <= date <= last:
                out.append(o)
        return out

    def event_label(self, o, date=None):
        if o["all_day"]:
            return "all day"
        s0, e0 = o["start"], o["end"]
        a = s0.strftime("%H:%M") if not date or s0.date() == date else "00:00"
        b = e0.strftime("%H:%M") if not date or e0.date() == date else "24:00"
        return a if e0 <= s0 else "%s-%s" % (a, b)

    def free_minutes(self):
        """Minutes until the next timed event today, 0 during one, or None without any."""
        now = dt.datetime.now()
        ongoing, nxt = next_event(self.ics_occ, now)
        if ongoing:
            return 0
        if nxt and nxt["start"].date() == now.date():
            return int((nxt["start"] - now).total_seconds() // 60)
        return None

    def pick_event_task(self, day):
        evs = self.events_on(day)
        if not evs:
            self.say("no calendar events that day", "dim")
            return
        j = self.menu("add event as task", ["%s  %s" % (pad(self.event_label(o, day), 11), clip(o["summary"], 40)) for o in evs])
        if j is not None:
            self.event_to_task(evs[j], day)

    def event_to_task(self, o, date):
        key = "ics|%s|%s" % (o["uid"], o["start"].isoformat())
        for t in self.store.tasks:
            if (t.get("src") or {}).get("key") == key:
                self.say("already a task", "dim")
                return None
        with self.edit():
            t = self.store.add(o["summary"])
            t["due"] = date.isoformat()
            t["tags"] = ["event"]
            if not o["all_day"]:
                mins = int((o["end"] - o["start"]).total_seconds() // 60)
                if 0 < mins <= 480:
                    t["est"] = mins * 60
            t["notes"] = (self.event_label(o, date) + ((" at " + o["location"]) if o["location"] else "")).strip()
            t["src"] = {"key": key, "file": "calendar", "line": o["start"].strftime("%H:%M")}
        self.say("added as a task for " + date.isoformat(), "ok")
        return t

    # ----- what now -----

    def act_whatnow(self):
        free = self.free_minutes()
        S = {"min": free if free else 60, "energy": 1, "i": 0, "from_cal": bool(free)}
        med = calibration(est_samples(self.store))
        median = med["median"] if med["n"] >= 3 else 1.0

        def ranked():
            a = self.store.active
            cur = self.store.get(a["id"]) if a else None
            return whatnow_rank(self.store, today(), S["min"], ENERGY_LEVELS[S["energy"]], median,
                                cur["project"] if cur else "")

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            res = ranked()
            self.screen_bar(W, "what now", "%d candidates " % len(res))
            until = ""
            if S["from_cal"]:
                _, nxt = next_event(self.ics_occ, dt.datetime.now())
                if nxt:
                    until = "  (until %s at %s)" % (clip(nxt["summary"], 24), nxt["start"].strftime("%H:%M"))
            self.put(2, 2, "I have", self.attr("dim"))
            x = self.put(2, 9, fmt_duration(S["min"] * 60) if S["min"] else "0m", self.attr("accent", bold=True))
            x = self.put(2, x + 1, "and", self.attr("dim"))
            x = self.put(2, x + 1, ENERGY_LEVELS[S["energy"]], self.attr("accent2", bold=True))
            x = self.put(2, x + 1, "energy" + until, self.attr("dim"))
            if median and abs(median - 1.0) > 0.1:
                self.put(3, 2, "estimates scaled by x%.2f from your history" % median, self.attr("dim"))
            room = max(1, (H - 7) // 2)
            S["i"] = max(0, min(S["i"], len(res) - 1))
            top = max(0, min(S["i"] - room + 1, max(0, len(res) - room))) if S["i"] >= room else 0
            if not res:
                self.put(5, 4, "nothing fits. try more time or press m to change it.", self.attr("dim"))
            for r in range(room):
                k = top + r
                if k >= len(res):
                    break
                sc, t, why = res[k]
                on = k == S["i"]
                bg = "sel_bg" if on else "bg"
                y = 5 + r * 2
                self.fill(y, 0, W, self.attr("fg", bg))
                self.fill(y + 1, 0, W, self.attr("fg", bg))
                x = self.put(y, 2, "%d." % (k + 1), self.attr("accent" if k == 0 else "dim", bg, bold=True))
                self.put(y, x + 1, t["title"] + (("  @" + t["project"]) if t["project"] else ""), self.attr("fg", bg, bold=on), W - x - 4)
                self.put(y + 1, 6, ", ".join(why[:4]) if why else "no particular reason", self.attr("dim", bg), W - 8)
            self.screen_foot(H, W, "j/k  enter track  f focus  x done  z snooze  m time  e energy  o show in list  q close")

        def handle(name, ch):
            if name in ("q", "esc", "ctrl-c"):
                return True
            if name in ("j", "down"):
                S["i"] += 1
            elif name in ("k", "up"):
                S["i"] -= 1
            elif name == "e":
                S["energy"] = (S["energy"] + 1) % 3
                S["i"] = 0
            elif name == "m":
                text = self.prompt("minutes available  (30, 45m, 1h30, empty for unlimited)", str(S["min"] or ""))
                if text is None:
                    return False
                text = text.strip()
                if not text:
                    S["min"], S["from_cal"] = None, False
                else:
                    try:
                        secs = parse_duration(text if re.search(r"[a-zA-Z]", text) else text + "m")
                    except ValueError:
                        self.say("could not read that time", "err")
                        return False
                    S["min"], S["from_cal"] = max(1, secs // 60), False
                S["i"] = 0
            else:
                res = ranked()
                if not res:
                    return False
                t = res[max(0, min(S["i"], len(res) - 1))][1]
                if name == "enter":
                    a = self.store.active
                    if a:
                        self.stop_tracking(False)
                    self.store.active = {"id": t["id"], "start": now_iso()}
                    self.store.save()
                    self.say("tracking: " + clip(t["title"], 40), "ok")
                    return True
                if name == "f":
                    self.jump_to(t["id"])
                    self.backdrop = self.draw
                    self.act_focus()
                    return True
                if name == "o":
                    self.jump_to(t["id"])
                    return True
                if name == "x":
                    with self.edit():
                        self.complete(t, True)
                elif name == "z":
                    with self.edit():
                        t["snooze"] = (today() + dt.timedelta(days=1)).isoformat()
            return False

        self.screen_loop(render, handle)

    # ----- dependency graph -----

    def act_graph(self):
        S = {"show_done": False, "g": None, "sel": None, "vx": 0, "vy": 0, "cache": None}
        GUT = 6

        def build():
            g = dep_graph(self.store, S["show_done"])
            S["g"] = g
            S["pos"] = {k: n for c in g["comps"] for k, n in c["nodes"].items() if not n["dummy"]}
            if S["sel"] not in S["pos"]:
                S["sel"] = g["bott"] if g["bott"] in S["pos"] else (min(S["pos"], key=lambda k: (S["pos"][k]["layer"], S["pos"][k]["y"])) if S["pos"] else None)
            S["cache"] = None

        def geometry(W):
            layers = max(1, S["g"]["layers"])
            cw = max(18, min(32, (W - 4 - GUT * (layers - 1)) // layers))
            return cw

        def canvas(cw):
            """Edge cells for the whole graph, in virtual coordinates."""
            cells = {}
            for c in S["g"]["comps"]:
                nodes = c["nodes"]
                counter = collections.Counter()
                for a, b, orig in c["edges"]:
                    na, nb = nodes[a], nodes[b]
                    crit = orig in S["g"]["crit_edges"]
                    x0 = na["layer"] * (cw + GUT) + cw
                    x1 = nb["layer"] * (cw + GUT) - (1 if nb["dummy"] else 2)
                    k = counter[na["layer"]]
                    counter[na["layer"]] += 1
                    xm = x0 + 1 + (k % 3)
                    graph_route(cells, x0, na["y"], x1, nb["y"], min(xm, x1), crit)
                for k, n in nodes.items():
                    if n["dummy"]:
                        for x in range(cw):
                            cx = n["layer"] * (cw + GUT) + x
                            m, cr = cells.get((cx, n["y"]), (0, False))
                            orig_crit = any(o in S["g"]["crit_edges"] for _a, _b, o in c["edges"] if _a == k or _b == k)
                            cells[(cx, n["y"])] = (m | 3, cr or orig_crit)
            return cells

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            if S["g"] is None:
                build()
            g = S["g"]
            self.screen_bar(W, "dependency graph", "d %s done  " % ("hide" if S["show_done"] else "show"))
            if not S["pos"]:
                self.put(3, 3, "no dependencies yet. press B on a task to add some.", self.attr("dim"))
                self.screen_foot(H, W, "d show done tasks   q close")
                return
            cw = geometry(W)
            if S["cache"] is None or S["cache"][0] != cw:
                S["cache"] = (cw, canvas(cw))
            cells = S["cache"][1]
            tasks_open = [t for t in self.store.tasks if t["id"] in S["pos"] and not t["done"]]
            bott = self.store.get(g["bott"]) if g["bott"] else None
            summary = "critical path %d task%s, about %s" % (len(g["crit"]), "" if len(g["crit"]) == 1 else "s", fmt_duration(g["crit_secs"]))
            if bott:
                summary += "     bottleneck: %s (unblocks %d)" % (clip(bott["title"], 30), g["dependents"][bott["id"]])
            self.put(1, 2, summary, self.attr("accent2", bold=True), W - 4)
            top, bottom = 3, H - 5
            vh = bottom - top
            vw = W - 3
            sel = S["pos"].get(S["sel"])
            if sel:
                sx, sy = sel["layer"] * (cw + GUT), sel["y"]
                if sx < S["vx"]:
                    S["vx"] = max(0, sx - 2)
                if sx + cw > S["vx"] + vw:
                    S["vx"] = sx + cw - vw + 2
                if sy < S["vy"]:
                    S["vy"] = max(0, sy - 1)
                if sy >= S["vy"] + vh:
                    S["vy"] = sy - vh + 2
            ascii_ = self.opts["ascii"]
            table = GRAPH_ASCII if ascii_ else GRAPH_CHARS
            for (cx, cy), (mask, crit) in cells.items():
                sx_, sy_ = cx - S["vx"] + 1, cy - S["vy"] + top
                if top <= sy_ < bottom and 1 <= sx_ < W - 1:
                    self.put(sy_, sx_, table.get(mask, "+"), self.attr("accent" if crit else "border"))
            arrow = ">" if ascii_ else "▸"
            for c in g["comps"]:
                for a, b, orig in c["edges"]:
                    nb = c["nodes"][b]
                    if nb["dummy"]:
                        continue
                    ax, ay = nb["layer"] * (cw + GUT) - 1 - S["vx"] + 1, nb["y"] - S["vy"] + top
                    if top <= ay < bottom and 1 <= ax < W - 1:
                        self.put(ay, ax, arrow, self.attr("accent" if orig in g["crit_edges"] else "dim"))
                for k, n in c["nodes"].items():
                    if n["dummy"]:
                        continue
                    t = self.store.get(k)
                    nx, ny = n["layer"] * (cw + GUT) - S["vx"] + 1, n["y"] - S["vy"] + top
                    if not (top <= ny < bottom) or nx + cw < 1 or nx >= W - 1:
                        continue
                    on = k == S["sel"]
                    bg = "sel_bg" if on else "bg"
                    blocked = bool(blockers(self.store, t))
                    if t["done"]:
                        mark, mrole = self.sym["check_on"], "done"
                    elif blocked:
                        mark, mrole = self.sym["blocked"], "p3"
                    else:
                        mark, mrole = self.sym["check_off"], "ok"
                    trole = "done" if t["done"] else ("accent" if k in g["crit"] else "fg")
                    cnt = g["dependents"].get(k, 0)
                    tail = (" +%d" % cnt) if cnt else ""
                    self.fill(ny, nx, cw, self.attr("fg", bg))
                    x = self.put(ny, nx, mark + " ", self.attr(mrole, bg, bold=True), cw)
                    self.put(ny, x, clip(t["title"], cw - cell_len(mark) - 1 - cell_len(tail)), self.attr(trole, bg, bold=(on or k in g["crit"])), cw - (x - nx))
                    if tail:
                        self.put(ny, nx + cw - cell_len(tail), tail, self.attr("accent2", bg, bold=True))
            t = self.store.get(S["sel"])
            if t:
                need = [x for x in blockers(self.store, t)]
                unb = waiting_on(self.store, t)
                line = "%s  needs %d open%s  unblocks %d direct, %d in all%s" % (
                    clip(t["title"], 40), len(need), (": " + ", ".join(clip(x["title"], 18) for x in need[:3])) if need else "",
                    len(unb), g["dependents"].get(t["id"], 0), "  on the critical path" if t["id"] in g["crit"] else "")
                self.put(H - 3, 2, line, self.attr("fg"), W - 4)
                if g["bott"] == t["id"]:
                    self.put(H - 2, 2, "finishing this one unblocks the most work", self.attr("ok", bold=True), W - 4)
            self.screen_foot(H, W, "j/k same column  h/l prerequisite or next  enter show in list  d done tasks  q close")
            del tasks_open

        def move(dkey):
            pos = S["pos"]
            cur = pos.get(S["sel"])
            if not cur:
                return
            if dkey in ("j", "k"):
                col = sorted((n["y"], k) for k, n in pos.items() if n["layer"] == cur["layer"])
                ids = [k for _y, k in col]
                i = ids.index(S["sel"]) + (1 if dkey == "j" else -1)
                if 0 <= i < len(ids):
                    S["sel"] = ids[i]
                return
            t = self.store.get(S["sel"])
            if dkey == "h":
                cand = [d for d in t.get("deps", []) if d in pos]
            else:
                cand = [o["id"] for o in waiting_on(self.store, t) if o["id"] in pos]
            if cand:
                S["sel"] = min(cand, key=lambda k: abs(pos[k]["y"] - cur["y"]))

        def handle(name, ch):
            if name in ("q", "esc", "ctrl-c") or self.keymap.get(name) == "graph":
                return True
            if name in ("j", "k", "h", "l", "down", "up", "left", "right"):
                move({"down": "j", "up": "k", "left": "h", "right": "l"}.get(name, name))
            elif name == "d":
                S["show_done"] = not S["show_done"]
                build()
            elif name == "enter" and S["sel"]:
                self.jump_to(S["sel"])
                return True
            return False

        self.screen_loop(render, handle)

    # ----- time travel through the data repository -----

    def act_travel(self):
        if not self.sync.enabled():
            if self.confirm("data is not tracked in git yet. start tracking it now?"):
                self.act_sync_setup()
                self.say("make some changes, then open time travel again", "dim", 5)
            return
        fname = os.path.basename(self.store.path)
        self.sync.finish(3.0)
        versions = data_versions(self.sync.dir, fname)
        if not versions:
            self.say("no history in git yet", "dim")
            return
        S = {"v": 0, "tab": 0, "i": 0, "focus": "versions", "cache": {}}
        tabs = ["deleted", "changed", "added"]

        def version():
            return versions[max(0, min(S["v"], len(versions) - 1))]

        def old_data():
            v = version()
            if v["sha"] not in S["cache"]:
                S["cache"][v["sha"]] = data_at(self.sync.dir, v["sha"], fname)
            return S["cache"][v["sha"]]

        def diff():
            d = old_data()
            if d is None:
                return None
            return version_diff(filled_tasks(d), self.store)

        def items(df):
            if df is None:
                return []
            return df[tabs[S["tab"]]]

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            self.screen_bar(W, "time travel", "%d versions " % len(versions))
            lw = min(44, max(26, W // 3))
            room = max(1, H - 4)
            S["v"] = max(0, min(S["v"], len(versions) - 1))
            top = max(0, min(S["v"] - room // 2, max(0, len(versions) - room)))
            for r in range(room):
                k = top + r
                if k >= len(versions):
                    break
                v = versions[k]
                on = k == S["v"]
                bg = "sel_bg" if on else "bg"
                self.fill(1 + r, 0, lw, self.attr("fg", bg))
                stamp = v["when"][5:16].replace("T", " ")
                x = self.put(1 + r, 1, stamp, self.attr("accent" if on and S["focus"] == "versions" else "dim", bg, bold=on))
                self.put(1 + r, x + 1, v["subject"].replace("synth: ", ""), self.attr("fg", bg, bold=on), lw - x - 1)
            for r in range(H - 2):
                self.put(1 + r, lw, self.sym["vline"], self.attr("border"))
            df = diff()
            rx = lw + 2
            x = rx
            for n, nm in enumerate(tabs):
                cnt = len(df[nm]) if df else 0
                on = n == S["tab"]
                label = " %s %d " % (nm, cnt)
                x = self.put(1, x, label, self.attr("accent" if on else "dim", "sel_bg" if on else "bg", bold=on)) + 1
            self.put(2, rx, {"deleted": "in that version, gone now. enter restores one, a restores all",
                              "changed": "different now. enter puts back how it was",
                              "added": "created after that version (read only)"}[tabs[S["tab"]]], self.attr("dim"), W - rx - 1)
            lst = items(df)
            S["i"] = max(0, min(S["i"], len(lst) - 1))
            room2 = max(1, H - 6)
            top2 = max(0, min(S["i"] - room2 + 1, max(0, len(lst) - room2))) if S["i"] >= room2 else 0
            if df is None:
                self.put(4, rx, "could not read that version", self.attr("err"))
            elif not lst:
                self.put(4, rx, "nothing here", self.attr("dim"))
            for r in range(room2):
                k = top2 + r
                if k >= len(lst):
                    break
                it = lst[k]
                on = k == S["i"] and S["focus"] == "items"
                bg = "sel_bg" if on else "bg"
                self.fill(4 + r, rx - 1, W - rx, self.attr("fg", bg))
                if tabs[S["tab"]] == "changed":
                    old, now_, d = it
                    x2 = self.put(4 + r, rx, clip(now_["title"], 30), self.attr("fg", bg, bold=on))
                    self.put(4 + r, x2 + 2, "; ".join("%s %s" % (HIST_LABEL.get(a, a), b) for a, b in d if a not in ("title",)) or "renamed",
                             self.attr("dim", bg), W - x2 - 4)
                else:
                    t = it
                    x2 = self.put(4 + r, rx, ("%s " % (self.sym["check_on"] if t["done"] else self.sym["check_off"])), self.attr("done" if t["done"] else "accent2", bg))
                    self.put(4 + r, x2, t["title"] + (("  @" + t["project"]) if t["project"] else ""), self.attr("fg", bg, bold=on), W - x2 - 2)
            hint = "j/k  tab switch list  h/l focus  R restore this whole version  q close" if S["focus"] == "versions" else "j/k  enter restore  a restore all  tab next list  h back  q close"
            self.screen_foot(H, W, hint)

        def restore_deleted(tasks):
            have = {t["id"] for t in self.store.tasks}
            with self.edit():
                for t in tasks:
                    if t["id"] in have:
                        continue
                    nt = copy.deepcopy(t)
                    if nt["parent"] not in have:
                        nt["parent"] = None
                    nt["deps"] = [d for d in nt.get("deps", []) if d in have]
                    self.store.tasks.append(nt)
                    have.add(nt["id"])
                    self.store.next_id = max(self.store.next_id, nt["id"] + 1)
            self.say("restored %d task%s" % (len(tasks), "" if len(tasks) == 1 else "s"), "ok")

        def handle(name, ch):
            if name in ("q", "esc", "ctrl-c") or self.keymap.get(name) == "travel":
                return True
            df = diff()
            lst = items(df)
            if name == "tab":
                S["tab"] = (S["tab"] + 1) % 3
                S["i"] = 0
                S["focus"] = "items"
            elif name in ("shift-tab",):
                S["tab"] = (S["tab"] - 1) % 3
                S["i"] = 0
                S["focus"] = "items"
            elif name in ("l", "right") and S["focus"] == "versions":
                S["focus"] = "items"
            elif name in ("h", "left"):
                S["focus"] = "versions"
            elif name in ("j", "down"):
                if S["focus"] == "versions":
                    S["v"] += 1
                    S["i"] = 0
                else:
                    S["i"] += 1
            elif name in ("k", "up"):
                if S["focus"] == "versions":
                    S["v"] -= 1
                    S["i"] = 0
                else:
                    S["i"] -= 1
            elif name == "R":
                d = old_data()
                if d and self.confirm("replace your whole list with the version from %s?" % version()["when"][:16].replace("T", " ")):
                    with self.edit():
                        self.store.tasks = filled_tasks(d)
                        self.store.next_id = max([self.store.next_id, d.get("next_id", 1)] + [t["id"] + 1 for t in self.store.tasks])
                        self.store.done_log = d.get("done_log", [])
                        self.store.habits = d.get("habits", [])
                        self.store.projects = d.get("projects", {})
                        self.store.journal = d.get("journal", {})
                        self.store.goals = d.get("goals", [])
                    self.say("restored that version (undo with u)", "ok", 5)
                    return True
            elif S["focus"] == "items" and lst:
                kind = tabs[S["tab"]]
                it = lst[max(0, min(S["i"], len(lst) - 1))]
                if name == "enter" and kind == "deleted":
                    restore_deleted([it])
                elif name == "a" and kind == "deleted":
                    restore_deleted(list(lst))
                elif name == "enter" and kind == "changed":
                    old, now_, d = it
                    with self.edit():
                        for f in RESTORE_FIELDS:
                            now_[f] = copy.deepcopy(old.get(f))
                    self.say("put back how it was", "ok")
            return False

        self.screen_loop(render, handle)

    def momentum(self):
        key = (len(self.store.done_log), today().isoformat())
        if getattr(self, "_mom_key", None) != key:
            self._mom_key = key
            self._mom = momentum_info([e["t"][:10] for e in self.store.done_log], today())
        return self._mom

    def draw_momentum(self, H, W, grow):
        m = momentum_info([e["t"][:10] for e in self.store.done_log], today(), 12)
        s = self.sym
        word = {1: "picking up", -1: "slowing down", 0: "steady"}[m["trend"]]
        self.tiles(2, [
            (str(m["streak"]), "day streak", "ok" if m["streak"] else "dim"),
            (str(m["best"]), "best streak", "accent2"),
            (str(m["last7"]), "done, last 7 days", "fg"),
            ("%s %s" % ({1: s["up"], -1: s["down"], 0: s["flat"]}[m["trend"]], word), "vs previous 7 (%d)" % m["prev7"],
             "ok" if m["trend"] >= 0 else "today"),
        ])
        self.put(6, 2, "weekly completions, oldest to newest", self.attr("accent", bold=True))
        wk = m["weeks"]
        mx = max(wk + [1])
        rows = []
        n = len(wk)
        for i, v in enumerate(wk):
            ago = n - 1 - i
            rows.append(("this week" if ago == 0 else "%d wk ago" % ago, v, str(v)))
        room = max(0, H - 9)
        self.hbars(7, 2, min(W - 6, 70), rows[-room:] if room < len(rows) else rows, "accent2", grow)
        if wk and wk[-1] and wk[-1] >= mx:
            self.put(min(H - 3, 8 + len(rows)), 2, "this week is your best in %d weeks." % n, self.attr("ok"))

    def act_changes(self):
        ranges = [1, 7, 14, 30]
        S = {"ri": 1, "scroll": 0}

        def build(W):
            cut = (today() - dt.timedelta(days=ranges[S["ri"]] - 1)).isoformat()
            evs = [e for e in self.store.history if e["t"][:10] >= cut]
            evs.sort(key=lambda e: e["t"], reverse=True)
            lines = []
            last = ""
            for e in evs:
                day = e["t"][:10]
                if day != last:
                    if lines:
                        lines.append(("", "fg", False))
                    lines.append((day, "accent2", True))
                    last = day
                t = self.store.get(e["id"])
                title = t["title"] if t else "(deleted)"
                label = HIST_LABEL.get(e["k"], e["k"])
                det = "" if e["k"] in ("created", "done", "reopen") else "  " + e["d"]
                txt = "%s %-10s %s%s" % (e["t"][11:16], label, title, det)
                lines.append((clip(txt, W - 6), "ok" if e["k"] == "done" else "fg", False))
            return lines, len(evs)

        def render():
            H, W = self.scr.getmaxyx()
            self.scr.erase()
            lines, n = build(W)
            self.screen_bar(W, "changes", "last %s  %d events " % ("day" if ranges[S["ri"]] == 1 else "%d days" % ranges[S["ri"]], n))
            room = max(1, H - 3)
            S["scroll"] = max(0, min(S["scroll"], max(0, len(lines) - room)))
            if not lines:
                self.put(2, 2, "nothing changed in this range.", self.attr("dim"))
            for i, (txt, role, bold) in enumerate(lines[S["scroll"]:S["scroll"] + room]):
                self.put(1 + i, 2, txt, self.attr(role, bold=bold), W - 4)
            self.screen_foot(H, W, "j/k scroll   r range   q close")

        def handle(name, ch):
            if name in ("q", "esc", "ctrl-c") or self.keymap.get(name) == "changes":
                return True
            if name in ("j", "down"):
                S["scroll"] += 1
            elif name in ("k", "up"):
                S["scroll"] -= 1
            elif name in ("ctrl-d", "pagedown"):
                S["scroll"] += 10
            elif name in ("ctrl-u", "pageup"):
                S["scroll"] -= 10
            elif name in ("g", "home"):
                S["scroll"] = 0
            elif name == "r":
                S["ri"] = (S["ri"] + 1) % len(ranges)
                S["scroll"] = 0
            return False

        self.screen_loop(render, handle)

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
            self.present()
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

    def sv_action_git_setup(self):
        self.act_sync_setup()

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
                self.present()
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
        if self.irc_hits and self.irc_mouse(ev=(mx, my, bstate)):
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
            for ry, cn, k in self.irc_side:
                if ry == my:
                    self.irc_select(to=(cn, k))
                    self.irc_show_pane()
                    return
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

    def dispatch(self, name, ch=None):
        if name == "mouse":
            self.handle_mouse()
            return
        if name in ("tick", "resize"):
            return
        if self.focus == "chat":
            r = self.irc_input_key(name, ch, False)
            if r == "leave":
                self.focus = "list"
            elif r == "full":
                self.irc_screen()
            elif r == "layout":
                nxt = {"right": "bottom", "bottom": "off", "off": "right"}[self.irc_layout()]
                self.irc_set_layout(nxt, focus=nxt != "off")
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
            "irc": self.act_irc,
            "stats": self.act_stats,
            "changes": self.act_changes,
            "git": self.act_git,
            "review": self.act_review,
            "bulk": self.act_bulk,
            "dump": self.act_dump,
            "whatnow": self.act_whatnow,
            "graph": self.act_graph,
            "travel": self.act_travel,
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
        if self.opts.get("git_sync"):
            self.startup_sync()
        self.irc_autostart()
        if self.opts.get("review_nudge", True) and self.store.tasks:
            last = self.state.get("last_review") or ""
            if not last or (today() - dt.date.fromisoformat(last)).days >= 7:
                self.say("weekly review is due, press %s" % self.first_key("review"), "today", 8)
        start = self.opts.get("start_screen", "list")
        starters = {"journal": self.act_journal, "habits": self.act_habits, "projects": self.act_projects,
                    "stats": self.act_stats, "calendar": self.act_calendar,
                    "agenda": lambda: self.act_calendar("agenda")}
        if start in starters:
            starters[start]()
        while self.running:
            self.wake_check()
            self.git_apply()
            self.ics_poll()
            self.draw()
            name, ch = self.read_key()
            self.dispatch(name, ch)
            # a held key queues many events: apply them first and draw once
            burst = 0
            while self.running and burst < 16 and self.input_pending():
                name, ch = self.read_key()
                if name == "tick":
                    break
                self.dispatch(name, ch)
                burst += 1


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "add":
        return cli_add(raw[1:])
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
        try:
            app.run()
        finally:
            app.irc_shutdown()
            app.sync.finish()

    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())