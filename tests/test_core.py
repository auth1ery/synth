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


if __name__ == "__main__":
    unittest.main()
