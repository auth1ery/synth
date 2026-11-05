import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import synth  # noqa: E402

BASE = dt.date(2026, 10, 7)  # a wednesday


class DateTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(synth.parse_date("today", BASE), BASE)
        self.assertEqual(synth.parse_date("tom", BASE), dt.date(2026, 10, 8))
        self.assertEqual(synth.parse_date("fri", BASE), dt.date(2026, 10, 9))
        self.assertEqual(synth.parse_date("wed", BASE), dt.date(2026, 10, 14))
        self.assertEqual(synth.parse_date("+2w", BASE), dt.date(2026, 10, 21))
        self.assertEqual(synth.parse_date("eom", BASE), dt.date(2026, 10, 31))
        self.assertIsNone(synth.parse_date("none", BASE))

    def test_numeric(self):
        self.assertEqual(synth.parse_date("2027-01-02", BASE), dt.date(2027, 1, 2))
        self.assertEqual(synth.parse_date("12-25", BASE), dt.date(2026, 12, 25))
        self.assertEqual(synth.parse_date("01-05", BASE), dt.date(2027, 1, 5))
        with self.assertRaises(ValueError):
            synth.parse_date("someday", BASE)

    def test_months(self):
        self.assertEqual(synth.add_months(dt.date(2026, 1, 31), 1), dt.date(2026, 2, 28))
        self.assertEqual(synth.add_months(dt.date(2026, 11, 15), 3), dt.date(2027, 2, 15))

    def test_repeat(self):
        self.assertEqual(synth.parse_repeat("weekly"), "1w")
        self.assertEqual(synth.next_due("2026-10-01", "1w", BASE), dt.date(2026, 10, 14))
        self.assertEqual(synth.next_due("2026-10-20", "2d", BASE), dt.date(2026, 10, 22))


class QuickAddTests(unittest.TestCase):
    def test_parse(self):
        p = synth.parse_quick("buy milk #errands #home @shop !2 due:tom every:1w")
        self.assertEqual(p["title"], "buy milk")
        self.assertEqual(p["tags"], ["errands", "home"])
        self.assertEqual(p["project"], "shop")
        self.assertEqual(p["prio"], 2)
        self.assertEqual(p["repeat"], "1w")
        self.assertIsNot(p["due"], synth.UNSET)

    def test_bad_date_stays_in_title(self):
        p = synth.parse_quick("call due:someday")
        self.assertEqual(p["title"], "call due:someday")

    def test_roundtrip(self):
        t = synth.blank_task(1, "write docs")
        t.update(tags=["work"], project="proj", prio=3, due="2026-10-09", repeat="1w")
        p = synth.parse_quick(synth.serialize(t))
        self.assertEqual(p["title"], "write docs")
        self.assertEqual((p["tags"], p["project"], p["prio"], p["due"], p["repeat"]),
                         (["work"], "proj", 3, "2026-10-09", "1w"))


class QueryTests(unittest.TestCase):
    def setUp(self):
        a = synth.blank_task(1, "Ship release")
        a.update(tags=["work"], project="proj", prio=3, due="2026-10-06")
        b = synth.blank_task(2, "Buy milk")
        b.update(prio=1, done=True)
        self.a, self.b = a, b

    def test_terms(self):
        td = BASE
        q = synth.compile_query
        self.assertTrue(q("#wo")(self.a, td))
        self.assertTrue(q("@proj !2+")(self.a, td))
        self.assertFalse(q("!2")(self.a, td))
        self.assertTrue(q("due:overdue is:open")(self.a, td))
        self.assertTrue(q("is:done milk")(self.b, td))
        self.assertTrue(q("-#work")(self.b, td))
        self.assertTrue(q("@none")(self.b, td))
        self.assertFalse(q("-is:done")(self.b, td))


class StoreTests(unittest.TestCase):
    def test_undo_redo_and_persist(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.json")
            s = synth.Store(path)
            s.snap()
            parent = s.add("parent")
            child = s.add("child", parent=parent["id"])
            s.save()
            s2 = synth.Store(path)
            self.assertEqual(len(s2.tasks), 2)
            self.assertEqual(len(s2.descendants(parent["id"])), 1)
            s.snap()
            s.delete([parent["id"]])
            self.assertEqual(s.tasks, [])
            self.assertTrue(s.undo())
            self.assertEqual(len(s.tasks), 2)
            self.assertTrue(s.redo())
            self.assertEqual(s.tasks, [])
            self.assertEqual(child["parent"], parent["id"])


class DurationTests(unittest.TestCase):
    def test_parse_and_format(self):
        self.assertEqual(synth.parse_duration("90"), 5400)
        self.assertEqual(synth.parse_duration("1h30m"), 5400)
        self.assertEqual(synth.parse_duration("45s"), 45)
        with self.assertRaises(ValueError):
            synth.parse_duration("soon")
        self.assertEqual(synth.fmt_duration(5400), "1h30m")
        self.assertEqual(synth.fmt_duration(3600), "1h")
        self.assertEqual(synth.fmt_duration(125, clock=True), "02:05")
        self.assertEqual(synth.fmt_duration(3725, clock=True), "1:02:05")

    def test_quick_add_estimate(self):
        p = synth.parse_quick("ship it est:2h")
        self.assertEqual((p["title"], p["est"]), ("ship it", 7200))
        t = synth.blank_task(1, "ship it")
        t["est"] = 7200
        self.assertIn("est:2h", synth.serialize(t))


class FuzzyTests(unittest.TestCase):
    def test_subsequence(self):
        self.assertIsNone(synth.fuzzy_score("xyz", "write docs"))
        score, pos = synth.fuzzy_score("wdoc", "write docs")
        self.assertEqual(pos[0], 0)
        self.assertEqual(len(pos), 4)

    def test_ranking_prefers_tight_matches(self):
        tight = synth.fuzzy_score("syn", "synth docs")[0]
        loose = synth.fuzzy_score("syn", "buy some yellow nuts")[0]
        self.assertGreater(tight, loose)


class LinkTests(unittest.TestCase):
    def test_links_and_backlinks(self):
        with tempfile.TemporaryDirectory() as d:
            s = synth.Store(os.path.join(d, "t.json"))
            a = s.add("alpha")
            b = s.add("beta")
            b["notes"] = "see [[%d]] and [[alp]] and [[nothing here]] http://x.org/a." % a["id"]
            kinds = [k for k, _, _ in synth.task_links(s, b)]
            self.assertEqual(kinds, ["task", "task", "broken", "url"])
            self.assertEqual(synth.backlinks(s, a), [b])
            self.assertEqual(synth.render_refs(s, "go [[%d]]" % a["id"], ">"), "go > alpha")
            self.assertEqual(synth.task_links(s, b)[3][1], "http://x.org/a")


class StatsTests(unittest.TestCase):
    def test_streaks(self):
        td = dt.date(2026, 10, 7)
        days = ["2026-10-07", "2026-10-06", "2026-10-05", "2026-09-01", "2026-09-02"]
        self.assertEqual(synth.streak_info(days, td), (3, 3))
        self.assertEqual(synth.streak_info(["2026-10-06"], td), (1, 1))
        self.assertEqual(synth.streak_info(["2026-10-01"], td), (0, 1))
        self.assertEqual(synth.streak_info([], td), (0, 0))

    def test_done_log_and_time_persist(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.json")
            s = synth.Store(path)
            s.done_log.append({"t": "2026-10-07T10:00:00", "id": 1, "p": ""})
            s.time_log.append({"t": "2026-10-07T10:00:00", "s": 60, "id": 1, "p": ""})
            s.active = {"id": 1, "start": "2026-10-07T11:00:00"}
            s.save()
            s2 = synth.Store(path)
            self.assertEqual((len(s2.done_log), len(s2.time_log), s2.active["id"]), (1, 1, 1))
            s2.snap()
            s2.done_log.clear()
            s2.undo()
            self.assertEqual(len(s2.done_log), 1)


def make_store():
    tmp = tempfile.mkdtemp()
    return synth.Store(os.path.join(tmp, "todos.json"))


class DependencyTests(unittest.TestCase):
    def test_blockers_and_cycles(self):
        st = make_store()
        a, b, c = st.add("a"), st.add("b"), st.add("c")
        b["deps"] = [a["id"]]
        c["deps"] = [b["id"]]
        self.assertEqual([x["id"] for x in synth.blockers(st, b)], [a["id"]])
        self.assertTrue(synth.would_cycle(st, a["id"], c["id"]))
        self.assertFalse(synth.would_cycle(st, c["id"], a["id"]))
        a["done"] = True
        self.assertEqual(synth.blockers(st, b), [])
        self.assertEqual([x["id"] for x in synth.waiting_on(st, b)], [c["id"]])

    def test_delete_cleans_deps(self):
        st = make_store()
        a, b = st.add("a"), st.add("b")
        b["deps"] = [a["id"]]
        st.delete([a["id"]])
        self.assertEqual(b["deps"], [])

    def test_query_tokens(self):
        st = make_store()
        a, b = st.add("a"), st.add("b")
        b["deps"] = [a["id"]]
        b["snooze"] = "2999-01-01"
        td = dt.date(2026, 10, 7)
        self.assertTrue(synth.compile_query("is:blocked", st)(b, td))
        self.assertFalse(synth.compile_query("is:blocked", st)(a, td))
        self.assertTrue(synth.compile_query("is:ready", st)(a, td))
        self.assertFalse(synth.compile_query("is:ready", st)(b, td))
        self.assertTrue(synth.compile_query("is:snoozed", st)(b, td))
        self.assertTrue(synth.compile_query("has:deps", st)(b, td))


class SnoozeTests(unittest.TestCase):
    def test_is_snoozed(self):
        t = synth.blank_task(1, "x")
        td = dt.date(2026, 10, 7)
        self.assertFalse(synth.is_snoozed(t, td))
        t["snooze"] = "2026-10-08"
        self.assertTrue(synth.is_snoozed(t, td))
        t["snooze"] = "2026-10-07"
        self.assertFalse(synth.is_snoozed(t, td))
        t["snooze"], t["done"] = "2026-10-09", True
        self.assertFalse(synth.is_snoozed(t, td))


class SortRuleTemplateTests(unittest.TestCase):
    def test_custom_sort(self):
        a, b, c = (synth.blank_task(i, n) for i, n in ((1, "b"), (2, "a"), (3, "c")))
        a["prio"], b["prio"], c["prio"] = 1, 1, 3
        ctx = {"time_by": {}, "store": None}
        out = synth.sort_items([a, b, c], "-prio,title", ctx)
        self.assertEqual([t["title"] for t in out], ["c", "a", "b"])

    def test_rules(self):
        st = make_store()
        t = st.add("urgent")
        t["prio"] = 3
        rules = synth.compile_rules([{"when": "!3", "fg": "p3", "prefix": "[!]"}, {"when": "!1", "fg": "p1"}], st)
        got = synth.match_rules(rules, t, dt.date(2026, 10, 7))
        self.assertEqual(got, {"fg": "p3", "prefix": "[!]"})

    def test_templates(self):
        spec = {"title": "Fix {bug} on {date}", "notes": "see {bug}", "subtasks": ["test {bug}"]}
        self.assertEqual(synth.template_vars(spec), ["bug"])
        self.assertEqual(synth.fill_template("a {bug} {date}", {"bug": "x"}), "a x {date}")


class HabitTests(unittest.TestCase):
    def test_parse(self):
        p = synth.parse_habit("read 3/week")
        self.assertEqual((p["name"], p["kind"], p["target"]), ("read", "weekly", 3))
        p = synth.parse_habit("run mon,wed,fri")
        self.assertEqual((p["kind"], p["days"]), ("days", [0, 2, 4]))
        p = synth.parse_habit("water x8")
        self.assertEqual((p["name"], p["kind"], p["target"]), ("water", "daily", 8))
        self.assertEqual(synth.serialize_habit(synth.parse_habit("run mon,wed,fri")), "run mon,wed,fri")

    def test_streak(self):
        td = dt.date(2026, 10, 7)
        h = synth.blank_habit(1, "x")
        h["created"] = "2026-10-01T00:00:00"
        for i in (1, 2, 3):
            h["log"][(td - dt.timedelta(days=i)).isoformat()] = 1
        self.assertEqual(synth.habit_streak(h, td), (3, 3))
        h["log"][td.isoformat()] = 1
        self.assertEqual(synth.habit_streak(h, td), (4, 4))
        h["log"].pop((td - dt.timedelta(days=2)).isoformat())
        self.assertEqual(synth.habit_streak(h, td), (2, 2))

    def test_weekly(self):
        td = dt.date(2026, 10, 7)
        h = synth.blank_habit(1, "x")
        h.update(kind="weekly", target=2, created="2026-09-01T00:00:00")
        h["log"] = {"2026-10-05": 1, "2026-10-06": 1}
        self.assertEqual(synth.habit_today(h, td), (True, True))
        self.assertEqual(synth.habit_week_total(h, td), 2)

    def test_scheduled_days(self):
        h = synth.blank_habit(1, "x")
        h.update(kind="days", days=[0])
        self.assertTrue(synth.habit_scheduled(h, dt.date(2026, 10, 5)))
        self.assertFalse(synth.habit_scheduled(h, dt.date(2026, 10, 6)))


class JournalEstimateTests(unittest.TestCase):
    def test_journal_vars(self):
        st = make_store()
        t = st.add("ship it")
        st.done_log.append({"t": "2026-10-07T10:00:00", "id": t["id"], "p": ""})
        st.time_log.append({"t": "2026-10-07T10:00:00", "s": 600, "id": t["id"], "p": ""})
        v = synth.journal_vars(st, dt.date(2026, 10, 7))
        self.assertEqual(v["weekday"], "Wednesday")
        self.assertIn("ship it", v["done"])
        self.assertEqual(v["done_count"], "1")
        out = synth.fill_template(synth.DEFAULT_JOURNAL_TEMPLATE, v)
        self.assertIn("## Done", out)

    def test_calibration(self):
        st = make_store()
        for i in range(4):
            t = st.add("t%d" % i)
            t["est"] = 600
            st.done_log.append({"t": "2026-10-0%dT10:00:00" % (i + 1), "id": t["id"], "p": "", "est": 600})
            st.time_log.append({"t": "2026-10-0%dT10:00:00" % (i + 1), "s": 1200, "id": t["id"], "p": ""})
        cal = synth.calibration(synth.est_samples(st))
        self.assertEqual(cal["n"], 4)
        self.assertAlmostEqual(cal["median"], 2.0)
        self.assertEqual(cal["within"], 0.0)


class GoalProjectTests(unittest.TestCase):
    def test_goal_kinds(self):
        st = make_store()
        td = dt.date(2026, 10, 7)
        a, b = st.add("a"), st.add("b")
        a["project"] = b["project"] = "p"
        a["done"] = True
        st.done_log.append({"t": "2026-10-06T10:00:00", "id": a["id"], "p": "p"})
        g = {"kind": "count", "target": 4, "query": "@p", "start": "2026-10-01", "due": ""}
        self.assertEqual(synth.goal_progress(st, g, td)["cur"], 1)
        g = {"kind": "tasks", "query": "@p"}
        self.assertAlmostEqual(synth.goal_progress(st, g, td)["frac"], 0.5)
        g = {"kind": "manual", "milestones": [{"t": "x", "done": True}, {"t": "y", "done": False}]}
        self.assertAlmostEqual(synth.goal_progress(st, g, td)["frac"], 0.5)

    def test_pace(self):
        td = dt.date(2026, 10, 15)
        g = {"start": "2026-10-01", "due": "2026-10-29"}
        self.assertEqual(synth.goal_pace(g, 0.1, td)[0], "behind")
        self.assertEqual(synth.goal_pace(g, 0.9, td)[0], "ahead")
        self.assertEqual(synth.goal_pace(g, 1.0, td)[0], "done")

    def test_project_stats(self):
        st = make_store()
        td = dt.date(2026, 10, 7)
        a, b = st.add("a"), st.add("b")
        a["project"] = b["project"] = "p"
        a["done"] = True
        a["done_at"] = "2026-10-06T10:00:00"
        s = synth.project_stats(st, "p", td)
        self.assertEqual((s["total"], s["done"], s["open"]), (2, 1, 1))
        self.assertEqual(s["health"], "on track")
        st.projects["p"] = {"status": "paused"}
        self.assertEqual(synth.project_stats(st, "p", td)["health"], "paused")


class PersistenceTests(unittest.TestCase):
    def test_roundtrip_and_undo(self):
        st = make_store()
        st.add("a")
        st.habits.append(synth.blank_habit(1, "read"))
        st.journal["2026-10-07"] = "hi"
        st.projects["p"] = {"status": "paused"}
        st.goals.append({"id": 1, "name": "g"})
        st.save()
        st2 = synth.Store(st.path)
        self.assertEqual(st2.habits[0]["name"], "read")
        self.assertEqual(st2.journal["2026-10-07"], "hi")
        self.assertEqual(st2.projects["p"]["status"], "paused")
        self.assertEqual(st2.goals[0]["name"], "g")
        st2.snap()
        st2.journal["2026-10-07"] = "changed"
        st2.undo()
        self.assertEqual(st2.journal["2026-10-07"], "hi")



class QuickNoteTests(unittest.TestCase):
    def test_inline_note(self):
        p = synth.parse_quick("call dentist #health // ask about the March invoice")
        self.assertEqual(p["title"], "call dentist")
        self.assertEqual(p["tags"], ["health"])
        self.assertEqual(p["notes"], "ask about the March invoice")


class SettingsPanelTests(unittest.TestCase):
    KINDS = {"bool", "int", "float", "choice", "text", "multiline", "order", "strlist", "color", "keys",
             "records", "action"}

    def walk(self, nodes):
        for n in nodes:
            yield n
            yield from self.walk(n["children"])

    def test_schema(self):
        seen = set()
        for n in self.walk(synth.build_settings_tree()):
            for it in n["items"]:
                self.assertIn(it["kind"], self.KINDS, it["label"])
                self.assertTrue(it["desc"], it["label"])
                if it["kind"] != "action":
                    self.assertIn(it["key"], synth.DEFAULTS, it["label"])
                    self.assertNotIn(it["key"], seen)
                    seen.add(it["key"])
                if it["kind"] in ("int", "float"):
                    self.assertLess(it["min"], it["max"])
                if it["kind"] == "records" and not it.get("dict"):
                    self.assertIn(it["fields"], synth.RECORD_FIELDS)
                if it["kind"] == "order":
                    for r in it.get("required", ()):
                        self.assertIn(r, it["available"])
                if it["kind"] == "action":
                    self.assertTrue(hasattr(synth.App, "sv_action_" + it["run"]))

    def test_defaults_inside_ranges(self):
        for n in self.walk(synth.build_settings_tree()):
            for it in n["items"]:
                if it["kind"] in ("int", "float"):
                    v = synth.DEFAULTS[it["key"]]
                    self.assertTrue(it["min"] <= v <= it["max"], it["key"])

    def test_helpers(self):
        self.assertEqual(synth.parse_key_list("j, down , g g"), ["j", "down", "g g"])
        self.assertEqual(synth.parse_key_list("none"), [])
        self.assertTrue(synth.color_valid("#1a2B3c"))
        self.assertTrue(synth.color_valid("208"))
        self.assertTrue(synth.color_valid("accent"))
        self.assertFalse(synth.color_valid("#12"))
        self.assertFalse(synth.color_valid("300"))
        fields = synth.RECORD_FIELDS["views"]
        rec = {"name": "a", "query": "", "columns": [], "show_done": False, "icon": None}
        self.assertEqual(synth.clean_record(rec, fields), {"name": "a", "show_done": False})

    def test_settings_roundtrip(self):
        path = os.path.join(tempfile.mkdtemp(), "sub", "settings.json")
        self.assertEqual(synth.load_settings(path), {})
        self.assertTrue(synth.save_settings_file(path, {"theme": "nord", "views": [{"name": "x"}]}))
        self.assertEqual(synth.load_settings(path)["views"][0]["name"], "x")

    def test_history_diff_and_record(self):
        st = synth.Store(os.path.join(tempfile.mkdtemp(), "t.json"))
        a = st.add("write docs")
        before = {t["id"]: synth.task_sig(t) for t in st.tasks}
        a["prio"] = 2
        a["done"] = True
        a["tags"] = ["x"]
        a["notes"] = "hello"
        b = st.add("second")
        st.record_changes(before)
        kinds = [(e["id"], e["k"]) for e in st.history]
        self.assertIn((a["id"], "prio"), kinds)
        self.assertIn((a["id"], "done"), kinds)
        self.assertIn((a["id"], "tags"), kinds)
        self.assertIn((a["id"], "notes"), kinds)
        self.assertIn((b["id"], "created"), kinds)
        tl = synth.history_for(st, a["id"])
        self.assertEqual(tl[0]["k"], "created")
        before = {t["id"]: synth.task_sig(t) for t in st.tasks}
        st.delete([b["id"]])
        st.record_changes(before)
        self.assertFalse([e for e in st.history if e["id"] == b["id"]])
        st.save()
        st2 = synth.Store(st.path)
        self.assertEqual(len(st2.history), len(st.history))

    def test_momentum(self):
        td = dt.date(2026, 10, 15)
        days = [(td - dt.timedelta(days=i)).isoformat() for i in range(3)]
        days += [(td - dt.timedelta(days=9)).isoformat()]
        m = synth.momentum_info(days, td)
        self.assertEqual(m["streak"], 3)
        self.assertEqual(m["last7"], 3)
        self.assertEqual(m["prev7"], 1)
        self.assertEqual(m["trend"], 1)
        self.assertEqual(len(m["weeks"]), 8)
        self.assertEqual(synth.momentum_info([], td)["streak"], 0)

    def test_todo_parsing(self):
        self.assertEqual(synth.parse_todo_line("    # TODO: fix this later"), ("TODO", "fix this later"))
        self.assertEqual(synth.parse_todo_line("x = 1  // FIXME(auth) handle nulls */"), ("FIXME", "handle nulls"))
        self.assertIsNone(synth.parse_todo_line("# TODO"))
        self.assertIsNone(synth.parse_todo_line("nothing here"))
        refs = synth.parse_commit_refs("fixes synth:12 and touches synth:7", "")
        self.assertEqual(refs, {12: True, 7: False})

    def test_change_summary(self):
        self.assertEqual(synth.change_summary([]), "synth: update")
        self.assertEqual(synth.change_summary(["done #1 a"]), "synth: done #1 a")
        msg = synth.change_summary(["done #1 a", "created #2 b"])
        self.assertTrue(msg.startswith("synth: 2 changes\n\n- done #1 a"))

    def test_git_scan_link_and_sync(self):
        import shutil
        import subprocess
        if not shutil.which("git"):
            self.skipTest("git not installed")
        d = tempfile.mkdtemp()

        def git(*a):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"] + list(a),
                           cwd=d, check=True, capture_output=True)
        git("init", "-q")
        with open(os.path.join(d, "a.py"), "w") as fh:
            fh.write("x = 1\n# TODO: write docs\n# FIXME handle empty input\n")
        git("add", "-A")
        git("commit", "-q", "-m", "first")
        found = synth.scan_todos(d)
        self.assertEqual(sorted(f["kind"] for f in found), ["FIXME", "TODO"])
        self.assertEqual(found[0]["file"], "a.py")
        # branch probe: untouched, then committed, then merged
        git("switch", "-q", "-c", "feat")
        base = synth.git_rev(d, "refs/heads/feat")
        job = {"id": 1, "repo": d, "branch": "feat", "base": base}
        self.assertEqual(synth.git_probe(job), "active")
        with open(os.path.join(d, "b.txt"), "w") as fh:
            fh.write("b\n")
        git("add", "-A")
        git("commit", "-q", "-m", "work on synth:1")
        self.assertEqual(synth.git_probe(job), "active")
        git("switch", "-q", "main")
        git("merge", "-q", "feat")
        self.assertEqual(synth.git_probe(job), "merged")
        self.assertEqual(synth.git_mentions(d)[0][2], {1: False})
        # data sync commits
        data = tempfile.mkdtemp()
        sy = synth.DataSync(data)
        self.assertTrue(sy.setup())
        with open(os.path.join(data, "todos.json"), "w") as fh:
            fh.write("{}")
        sy.mark(["created #1 hello"], delay=0)
        sy.finish()
        rc, out = synth.git_run(["log", "--format=%s"], data)
        self.assertIn("synth: created #1 hello", out)

    def test_review_data(self):
        st = synth.Store(os.path.join(tempfile.mkdtemp(), "t.json"))
        td = dt.date(2026, 10, 30)
        a = st.add("late")
        a["due"] = "2026-10-20"
        b = st.add("soon")
        b["due"] = "2026-11-02"
        c = st.add("old")
        c["created"] = "2026-08-01T10:00:00"
        e = st.add("finished")
        e["done"] = True
        st.done_log.append({"t": "2026-10-28T10:00:00", "id": e["id"], "p": "x", "n": "finished"})
        d = synth.review_data(st, td)
        self.assertEqual([t["title"] for t in d["slipped"]], ["late"])
        self.assertEqual([t["title"] for t in d["ahead"]], ["soon"])
        self.assertEqual([t["title"] for t in d["stale"]], ["old"])
        self.assertEqual(d["done"], 1)
        self.assertIn("## wins", synth.review_text(d, td))

    def test_natural_due_and_dump(self):
        td = dt.date(2026, 11, 1)
        self.assertEqual(synth.natural_due("call mom tomorrow", td), ("call mom", "2026-11-02"))
        self.assertEqual(synth.natural_due("ship it in 3 days", td), ("ship it", "2026-11-04"))
        self.assertEqual(synth.natural_due("email bob by friday", td), ("email bob", "2026-11-06"))
        self.assertEqual(synth.natural_due("buy tomorrow's milk", td), ("buy tomorrow's milk", None))
        items = synth.parse_dump("# Work\n- plan release !2\n  - write notes\n  - [x] tag build\n- call dentist\n")
        self.assertEqual([(i["title"], i["depth"], i["project"]) for i in items],
                         [("plan release", 0, "Work"), ("write notes", 1, "Work"), ("tag build", 1, "Work"), ("call dentist", 0, "Work")])
        self.assertTrue(items[2]["done"])
        self.assertEqual(items[0]["prio"], 2)
        st = synth.Store(os.path.join(tempfile.mkdtemp(), "t.json"))
        made = synth.create_from_items(st, items, ["inbox"])
        self.assertEqual(made[1]["parent"], made[0]["id"])
        self.assertIsNone(made[3]["parent"])
        self.assertIn("inbox", made[0]["tags"])

    def test_cli_add(self):
        import subprocess
        d = tempfile.mkdtemp()
        env = dict(os.environ, SYNTH_DATA=os.path.join(d, "todos.json"), SYNTH_CONFIG=os.path.join(d, "c.toml"))
        script = os.path.join(os.path.dirname(os.path.abspath(synth.__file__)), "synth.py")
        r = subprocess.run([sys.executable, script, "add", "buy milk !2 #home"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("added #1 buy milk", r.stdout)
        r = subprocess.run([sys.executable, script, "add", "-p", "ops"], env=env, capture_output=True, text=True,
                           input="- a\n  - b\n")
        self.assertEqual(r.returncode, 0)
        st = synth.Store(env["SYNTH_DATA"])
        self.assertEqual([t["title"] for t in st.tasks], ["buy milk", "a", "b"])
        self.assertEqual(st.tasks[2]["parent"], st.tasks[1]["id"])
        self.assertEqual(st.tasks[1]["project"], "ops")
        self.assertTrue(st.history)

    def test_github_parse_and_fake_gh(self):
        items = synth.parse_gh_items('[{"number": 4, "title": "Crash", "url": "u", "state": "OPEN", "labels": [{"name": "bug"}]}]', "issue")
        self.assertEqual(items[0]["labels"], ["bug"])
        self.assertEqual(items[0]["state"], "open")
        self.assertEqual(synth.parse_gh_items("not json", "pr"), [])
        self.assertTrue(synth.gh_done_state("issue", "closed"))
        self.assertFalse(synth.gh_done_state("pr", "closed"))
        self.assertTrue(synth.gh_done_state("pr", "merged"))
        d = tempfile.mkdtemp()
        fake = os.path.join(d, "gh")
        with open(fake, "w") as fh:
            fh.write('#!/bin/sh\necho \'[{"number": 9, "title": "Fix it", "url": "https://x/9", "state": "OPEN", "labels": []}]\'\n')
        os.chmod(fake, 0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = d + os.pathsep + old
        try:
            got, err = synth.gh_list(d, "issue")
        finally:
            os.environ["PATH"] = old
        self.assertEqual(err, "")
        self.assertEqual(got[0]["number"], 9)

    def test_ics(self):
        ics = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a1\nSUMMARY:Standup\\, team\nDTSTART:20261102T160000\nDTEND:20261102T161500\n"
            "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4\nEXDATE:20261104T160000\nLOCATION:Zoom\nEND:VEVENT\n"
            "BEGIN:VEVENT\nUID:b2\nSUMMARY:Holiday\nDTSTART;VALUE=DATE:20261111\nEND:VEVENT\n"
            "BEGIN:VEVENT\nUID:c3\nSUMMARY:Review\nDTSTART:20261103T100000\nDURATION:PT1H\nRRULE:FREQ=MONTHLY;BYDAY=1TU\nEND:VEVENT\n"
            "END:VCALENDAR\n")
        ev = synth.parse_ics(ics)
        self.assertEqual(len(ev), 3)
        self.assertEqual(ev[0]["summary"], "Standup, team")
        occ = synth.expand_events(ev, dt.date(2026, 11, 1), dt.date(2026, 12, 10))
        stand = [o["start"].strftime("%m-%d") for o in occ if o["summary"].startswith("Standup")]
        self.assertEqual(stand, ["11-02", "11-09", "11-11"])
        self.assertEqual([o["start"].strftime("%m-%d") for o in occ if o["summary"] == "Review"], ["11-03", "12-01"])
        hol = [o for o in occ if o["summary"] == "Holiday"][0]
        self.assertTrue(hol["all_day"])
        ongoing, nxt = synth.next_event(occ, dt.datetime(2026, 11, 2, 16, 5))
        self.assertEqual(ongoing["summary"], "Standup, team")
        self.assertEqual(nxt["summary"], "Review")

    def test_whatnow_rank(self):
        st = synth.Store(os.path.join(tempfile.mkdtemp(), "t.json"))
        td = dt.date(2026, 11, 1)
        a = st.add("overdue big")
        a["due"] = "2026-10-28"
        a["est"] = 7200
        b = st.add("quick win")
        b["est"] = 600
        b["prio"] = 1
        c = st.add("blocked")
        c["deps"] = [b["id"]]
        c["prio"] = 3
        d = st.add("later")
        d["snooze"] = "2026-12-01"
        rank = synth.whatnow_rank(st, td, None, "medium")
        self.assertEqual(rank[0][1]["title"], "overdue big")
        self.assertNotIn("blocked", [r[1]["title"] for r in rank])
        self.assertNotIn("later", [r[1]["title"] for r in rank])
        short = synth.whatnow_rank(st, td, 30, "low")
        self.assertEqual([r[1]["title"] for r in short], ["quick win"])

    def test_dep_graph(self):
        st = synth.Store(os.path.join(tempfile.mkdtemp(), "t.json"))
        a, b, c, d = (st.add(n) for n in "abcd")
        b["deps"] = [a["id"]]
        c["deps"] = [b["id"], a["id"]]
        d["deps"] = [c["id"]]
        g = synth.dep_graph(st)
        comp = g["comps"][0]
        self.assertEqual(g["layers"], 4)
        self.assertEqual(comp["nodes"][a["id"]]["layer"], 0)
        self.assertEqual(comp["nodes"][d["id"]]["layer"], 3)
        self.assertTrue(any(n["dummy"] for n in comp["nodes"].values()))
        self.assertEqual(g["bott"], a["id"])
        self.assertEqual(g["dependents"][a["id"]], 3)
        self.assertIn(d["id"], g["crit"])
        self.assertEqual(synth.dep_graph(synth.Store(os.path.join(tempfile.mkdtemp(), "x.json")))["comps"], [])

    def test_time_travel(self):
        import shutil
        if not shutil.which("git"):
            self.skipTest("git not installed")
        data = tempfile.mkdtemp()
        path = os.path.join(data, "todos.json")
        st = synth.Store(path)
        sy = synth.DataSync(data)
        sy.setup()
        st.on_save = lambda lines: sy.mark(lines, delay=0)
        a = st.add("keep me")
        b = st.add("delete me")
        st.save()
        sy.finish()
        st.delete([b["id"]])
        a["prio"] = 3
        st.add("new one")
        st.save()
        sy.finish()
        versions = synth.data_versions(data, "todos.json")
        self.assertGreaterEqual(len(versions), 2)
        old = synth.data_at(data, versions[1]["sha"], "todos.json")
        diff = synth.version_diff(synth.filled_tasks(old), st)
        self.assertEqual([t["title"] for t in diff["deleted"]], ["delete me"])
        self.assertEqual([t["title"] for t in diff["added"]], ["new one"])
        self.assertEqual(diff["changed"][0][2][0][0], "prio")


class IrcParseTests(unittest.TestCase):
    def test_parse(self):
        m = synth.irc_parse("@time=2026-01-02T03:04:05.000Z :nick!user@host PRIVMSG #chan :hello there")
        self.assertEqual((m["nick"], m["user"], m["host"], m["cmd"]), ("nick", "user", "host", "PRIVMSG"))
        self.assertEqual(m["params"], ["#chan", "hello there"])
        self.assertIn("time", m["tags"])
        m = synth.irc_parse("PING :irc.example.net")
        self.assertEqual((m["cmd"], m["params"]), ("PING", ["irc.example.net"]))
        m = synth.irc_parse(":irc.example.net 001 me :Welcome")
        self.assertEqual((m["nick"], m["cmd"], m["params"]), ("irc.example.net", "001", ["me", "Welcome"]))

    def test_sasl_payload(self):
        chunks = synth.irc_sasl_plain("acct", "pw")
        self.assertEqual(chunks, ["AGFjY3QAcHc="])
        long = synth.irc_sasl_plain("a" * 200, "b" * 200)
        self.assertTrue(all(len(c) <= 400 for c in long))
        exact = synth.irc_sasl_plain("a" * 148, "b" * 149)  # 300 raw bytes, 400 base64 chars
        self.assertEqual(exact[-1], "+")

    def test_split_and_clean(self):
        parts = synth.irc_split("word " * 200, 100)
        self.assertTrue(all(len(x.encode()) <= 100 for x in parts))
        self.assertEqual(" ".join(parts), ("word " * 200).strip())
        parts = synth.irc_split("\u00e9" * 300, 100)
        self.assertTrue(all(len(x.encode()) <= 100 for x in parts))
        self.assertNotIn("\n", synth.irc_clean("a\r\nQUIT :x"))

    def test_mentions_and_format(self):
        self.assertTrue(synth.irc_mentioned("hey Bob, look", "bob"))
        self.assertTrue(synth.irc_mentioned("bob: hi", "Bob"))
        self.assertFalse(synth.irc_mentioned("bobby is here", "bob"))
        self.assertEqual(synth.irc_strip_format("\x02bold\x0f \x0304,05red\x03"), "bold red")
        self.assertEqual(synth.irc_env_name("Libera.Chat"), "SYNTH_IRC_PASSWORD_LIBERA_CHAT")


class FakeIrcServer:
    """A tiny server: SASL PLAIN, registration, JOIN, echoes what the client sends."""

    def __init__(self):
        import socket
        import threading
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.got = []
        self.conn = None
        self.t = threading.Thread(target=self.run, daemon=True)
        self.t.start()

    def out(self, line):
        self.conn.sendall((line + "\r\n").encode())

    def run(self):
        import base64
        self.conn, _ = self.srv.accept()
        self.conn.settimeout(5)
        data = b""
        try:
            while True:
                chunk = self.conn.recv(4096)
                if not chunk:
                    return
                data += chunk
                while b"\n" in data:
                    raw, _, data = data.partition(b"\n")
                    line = raw.decode().rstrip("\r")
                    self.got.append(line)
                    if line.startswith("CAP LS"):
                        self.out(":srv CAP * LS :sasl=PLAIN server-time multi-prefix away-notify")
                    elif line.startswith("CAP REQ"):
                        self.out(":srv CAP * ACK :sasl server-time multi-prefix")
                    elif line == "AUTHENTICATE PLAIN":
                        self.out("AUTHENTICATE +")
                    elif line.startswith("AUTHENTICATE ") and line != "AUTHENTICATE PLAIN":
                        self.account = base64.b64decode(line.split()[1]).split(b"\0")
                        self.out(":srv 903 me :SASL authentication successful")
                    elif line == "CAP END":
                        self.out(":srv 001 me :Welcome to FakeNet")
                        self.out(":srv 005 me PREFIX=(ov)@+ CHANTYPES=# :are supported")
                    elif line.startswith("PING"):
                        self.out("PONG :" + line[5:])
                    elif line.startswith("JOIN "):
                        ch = line.split()[1]
                        self.out(":me!u@h JOIN " + ch)
                        self.out(":srv 353 me = %s :@op me alice" % ch)
                        self.out(":srv 366 me %s :End" % ch)
                        self.out("@time=2026-01-02T03:04:05.000Z :alice!a@h PRIVMSG %s :hello me, welcome" % ch)
                    elif line.startswith("PRIVMSG "):
                        self.out(":srv NOTICE me :got it")
        except OSError:
            pass


class IrcClientTests(unittest.TestCase):
    def wait(self, fn, secs=5):
        import time
        end = time.time() + secs
        while time.time() < end:
            if fn():
                return True
            time.sleep(0.02)
        return False

    def test_session(self):
        srv = FakeIrcServer()
        cfg = {"name": "fake", "host": "127.0.0.1", "port": srv.port, "tls": False, "plain_auth": True,
               "nick": "me", "account": "myacct", "auth": "sasl", "channels": ["#synth"], "reconnect": False}
        c = synth.IrcClient(cfg, password="secret")
        c.start()
        try:
            self.assertTrue(self.wait(lambda: c.status == "online"))
            self.assertEqual(srv.account, [b"", b"myacct", b"secret"])
            self.assertTrue(self.wait(lambda: "#synth" in c.buffers and c.buffers["#synth"].lines))
            b = c.buffers["#synth"]
            self.assertTrue(self.wait(lambda: any(l[1] == "msg" for l in b.lines)))
            self.assertEqual(c.nick_list("#synth")[0], ("op", "@"))
            msg = [l for l in b.lines if l[1] == "msg"][0]
            self.assertEqual((msg[2], msg[3]), ("alice", "hello me, welcome"))
            self.assertEqual(b.mentions, 1)
            self.assertEqual(c.alerts[0][2], "alice")
            err, _ = c.command("#synth", "/msg alice hi there")
            self.assertIsNone(err)
            self.assertTrue(self.wait(lambda: "PRIVMSG alice :hi there" in srv.got))
            self.assertIn("alice", c.buffers)
            self.assertTrue(self.wait(lambda: any(l[1] == "notice" or l[1] == "info" for l in c.buffers["*"].lines if "got it" in l[3])))
            c.privmsg("#synth", "a b\r\nQUIT :x")
            self.assertTrue(self.wait(lambda: any(g.startswith("PRIVMSG #synth :a b") for g in srv.got)))
            self.assertFalse(any(g.startswith("QUIT") for g in srv.got))
            c.command("#synth", "/ns identify topsecret")
            self.assertTrue(self.wait(lambda: "PRIVMSG NickServ :identify topsecret" in srv.got))
            for buf in c.buffers.values():
                self.assertFalse(any("topsecret" in l[3] or "secret" == l[3] for l in buf.lines))
        finally:
            c.stop()

    def test_no_password_without_tls(self):
        srv = FakeIrcServer()
        cfg = {"name": "fake", "host": "127.0.0.1", "port": srv.port, "tls": False,
               "nick": "me", "auth": "sasl", "reconnect": False}
        c = synth.IrcClient(cfg, password="secret")
        c.start()
        try:
            self.assertTrue(self.wait(lambda: c.status == "online"))
            self.assertFalse(any("secret" in g or g.startswith("AUTHENTICATE") for g in srv.got))
            self.assertFalse(any("IDENTIFY" in g for g in srv.got))
        finally:
            c.stop()


if __name__ == "__main__":
    unittest.main()