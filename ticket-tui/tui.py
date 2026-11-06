#!/usr/bin/env python3
"""Sidequest: a keyboard-driven attention queue for Jira and GitHub."""

import argparse
import curses
import json
import os
import queue
import re
import subprocess
import sys
import threading
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.access import access_error
from sidequest import config
from sidequest import qa
from sidequest import terminal
from sidequest.application import build_workflow

from core import Store, now, parse_time, rank, tickets_from
from sidequest.environments import fetch_environments
from sidequest.ticket_keys import branch_keys, is_key
from sidequest.worktrees import parse_worktrees
from worklog import collect_worklog, daily_summary
from workflow import next_owner, ownership, stage_context, workflow_path, workflow_strip
from sorting import DATE_SORTS, SORT_MODES, activity_date, last_commit, ordered
from activity import ticket_activity
from launcher import (agent_command, find_tw_window, jump_to_window, new_window_command,  # noqa: F401
                      open_in_edge, start_agent, switch_client)
from layout import (DAY_RULE, EVENT_INDENT, HEAVY, LIGHT, TONE, border, card, columns, lane_tab, pr_glyph_offset,
                    relative, scroll_label, table_header, table_row, timeline, panel_rects)
import standup
from queue_evidence import EVERY, QueueEvidence
from plan_document import document_views

WORKFLOW = Path(__file__).resolve().parents[1]
ROOT = Path(config.get('workspace', 'repository') or WORKFLOW).expanduser().resolve()
VIEWS = ["All", "Needs me", "Waiting", "Clarify"]
# Right-pane views: key, tab label, internal name.
TABS = [("a", "Activity", "Activity"), ("p", "Plan", "Plan"), ("d", "Updates", "Updates"), ("v", "Overview", "Overview"),
        ("s", "Work log", "Work log"), ("f", "Flow", "Workflow"), ("u", "Standup", "Standup")]
TAB_KEYS = {key: name for key, _, name in TABS}
# Optional per-ticket plans stay outside this source tree.
PLANS = qa.tickets_dir()
# Bottom bar. On narrow terminals descriptions shorten first, then MOVE is dropped, then DO.
# (key, description, short description used when the terminal is narrow)
FOOTER = [("MOVE", [("j/k", "tickets", ""), ("h/l", "pane", ""), ("1-4", "lane", ""), ("/", "search", "search")]),
          ("DO", [("Space", "open menu", "menu"), ("w", "go to worktree", "work"), ("r", "refresh", "refresh"),
                  ("o", "sort", "sort"), ("+/-", "resize sections", "size")]),
          ("", [("?", "help", "help"), ("q", "quit", "quit")])]
SPACE_MENU = [("Open", [("j", "Jira"), ("o", "PR"), ("w", "worktree"), ("s", "agent")]),
              ("Work", [("n", "create/open local worktree")])]
DETAIL_WORKERS = 4
PLAN_HEADING = "\x00"          # marks a markdown heading in the Plan tab; stripped before drawing


def readable_date(value):
    stamp = parse_time(value)
    if not stamp:
        return "Not recorded"
    local = stamp.astimezone(now().tzinfo)
    days = (now().date() - local.date()).days
    day = "Today" if days == 0 else "Yesterday" if days == 1 else local.strftime("%d %b %Y")
    return f"{day}, {local:%H:%M}"


def source_age(value):
    stamp = parse_time(value)
    if not stamp:
        return "not loaded"
    minutes = max(0, int((now() - stamp).total_seconds() // 60))
    return "just now" if minutes < 1 else f"{minutes}m ago" if minutes < 60 else f"{minutes // 60}h ago" if minutes < 1440 else f"{minutes // 1440}d ago"


# Space s: run the configured agent in the ticket's worktree, using bundled prompts.
# (label, phrase, optional metadata); no company skills are loaded.
AGENT_TASKS = [
    ("Review PR feedback", "Review the PR feedback for {key} and explain the changes needed", 'sidequest-feedback'),
    ("Review this branch", "Review the branch for {key} and report correctness issues", None),
    ("Plan or start ticket", "Start {key}", 'sidequest-start'),
    ("QA locally", "QA {key} locally", 'sidequest-qa-local'),
    ("QA review app", "QA {key} on its review app", 'sidequest-qa-review-app'),
    ("Ship ticket", "Prepare {key} for shipping", 'sidequest-ship'),
    ("Triage an error", "Investigate the error reported for {key}", 'sidequest-triage'),
    ("Custom prompt...", None, None),
]


def agent_prompt(key, phrase, skill):
    prompt = phrase.format(key=key)
    if skill:
        from sidequest.skills import render
        prompt += '\n\n' + render(WORKFLOW / 'agents/skills' / skill / 'SKILL.md')
    return prompt


def run(args, timeout=45):
    executable = [sys.executable, '-B', str(WORKFLOW / 'bin' / 'sidequest-data.py'), *args[1:]] if args[0] == 'sidequest-data' else args
    result = subprocess.run(executable, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    if result.returncode == 1 and args[:2] == ["sidequest-data", "collect"]:
        # A completed partial collection is a versioned snapshot, not a process failure.
        # The queue applies each healthy source and reports the failed ones separately.
        try:
            partial = json.loads(result.stdout)
        except (ValueError, TypeError):
            partial = None
        if (isinstance(partial, dict) and partial.get("version") == 1
                and isinstance(partial.get("sources"), dict)
                and isinstance(partial.get("failures"), dict) and partial["failures"]):
            return result.stdout
    if result.returncode:
        service = ("Jira" if args[:2] in (["sidequest-data", "ticket"], ["sidequest-data", "my-tickets"]) else
                   "GitHub" if args[:2] == ["sidequest-data", "pr-feedback"] else args[0])
        raise RuntimeError(access_error(service, result.stderr))
    diagnostics = result.stderr.strip()
    if args[:2] == ["sidequest-data", "pr-feedback"]:
        # Compatibility for diagnostics emitted by older read-only helpers.
        diagnostics = "\n".join(line for line in diagnostics.splitlines()
                                if not line.startswith("sidequest-data: no Jira token in the Keychain"))
    if args[0] == "sidequest-data" and diagnostics:
        # The existing helpers sometimes return valid empty JSON after an API error.
        raise RuntimeError(f"sidequest-data {args[1]} reported diagnostics; keeping the previous snapshot. Check the helper in your terminal")
    return result.stdout


def unexpected(label, exc):
    return f"{label} failed unexpectedly ({type(exc).__name__}: {exc}); please report this"


def worktrees():
    result = {}
    if not config.get('workspace', 'repository'):
        return result
    try:
        # Same parsing and key rule as sidequest.worktrees.lookup, so w and Space n agree.
        for path, branch in parse_worktrees(run(["git", "worktree", "list", "--porcelain"])):
            for key in branch_keys(branch or ""):
                result[key] = path
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        pass
    return result


def demo_sources():
    clock = now()
    jira = {"generated_at": clock.isoformat(), "jira_available": True, "tickets": [
        {"key": "DEMO-901", "summary": "Validate bulk request quantities", "status": "In Progress", "priority": "High", "assignee": "Example Developer", "assignee_ok": True},
        {"key": "DEMO-902", "summary": "Keep inventory totals consistent", "status": "Code Review", "priority": "Medium", "assignee": "Reviewer", "assignee_ok": False},
        {"key": "DEMO-903", "summary": "Check tracking status display", "status": "QA", "priority": "Medium", "assignee": "QA team", "assignee_ok": False},
        {"key": "DEMO-904", "summary": "Clarify export acceptance criteria", "status": "Blocked", "priority": "Low", "assignee": "Unknown"},
    ]}
    prs = {"generated_at": clock.isoformat(), "open_prs": [
        {"ticket": "DEMO-901", "number": 901, "title": "Validate bulk request quantities", "review_decision": "CHANGES_REQUESTED", "ci": "green", "unresolved_count": 2},
        {"ticket": "DEMO-902", "number": 902, "title": "Keep inventory totals consistent", "ci": "green", "requested_reviewers": ["reviewer"]},
    ]}
    environments = {"entries": {"901": {"status": "Building", "checked_at": clock.isoformat()},
                                "902": {"status": "Web up", "checked_at": clock.isoformat()}}}
    return jira, prs, environments


EVIDENCE_EVENTS = ("jira", "prs", "worklog", "worktrees", "heroku", "heroku_error")


class App:
    def __init__(self, store, snapshots, demo=False, stale_days=2, escalate_days=5, standup_time=standup.DEFAULT_TIME,
                 workflow_factory=None):
        self.store, self.snapshots, self.demo = store, snapshots, demo
        self.workflow_factory = workflow_factory or (lambda: build_workflow(config.SETTINGS, os.environ, run))
        self.standup_time = standup_time
        self.stale_days, self.escalate_days = stale_days, escalate_days
        self.view, self.query, self.index, self.offset = "All", "", 0, 0
        self.preview_scroll = 0
        self.list_fraction = 0.3
        self.page_size = self.preview_page_size = 1
        self.focus_pane = "list"
        self.detail_tab = "Activity"     # Jira + GitHub events only, newest first
        self.message = "+/- resize sections   = reset   Space: menu   ?: help"
        # A message you caused stays up briefly; background results wait their turn.
        self.user_message_at = 0.0
        self.deferred_message = None
        self.events = queue.Queue()
        self.refreshing = False
        self.refresh_status = ""
        self.refresh_started = 0
        self.jobs = {}
        self.foreground_target = None
        self.dirty = True
        self.styles = {}
        self.plan_cache = {}
        settings = store.get("@app")
        fraction = settings.get("list_fraction", 0.3)
        if isinstance(fraction, (int, float)) and 0 < fraction < 1:
            self.list_fraction = fraction
        self.sort_mode = {"Last work date": "Last commit"}.get(settings.get("sort_mode"), settings.get("sort_mode", "Attention"))
        if self.sort_mode not in SORT_MODES:
            self.sort_mode = "Attention"
        self.sort_descending = settings.get("sort_descending", True)
        self.evidence = QueueEvidence(store, snapshots, demo_sources() if demo else None)
        self.rebuild()
        if demo:
            for key in ("DEMO-902", "DEMO-903"):
                self.store.save(key, {"observed_since": (now() - timedelta(days=8)).isoformat()})
            self.rebuild()

    def rebuild(self):
        previous = self.selected() if hasattr(self, "tickets") else None
        self.tickets = [rank(t, self.store, stale_days=self.stale_days, escalate_days=self.escalate_days)
                        for t in tickets_from(self.evidence.jira, self.evidence.prs, self.evidence.fallback, self.evidence.windows,
                                              config.get('jira', 'projects', []))]
        self.tickets = ordered(self.tickets, self.sort_mode, self.sort_descending, self.evidence.worklog)
        if previous:
            self.index = next((i for i, t in enumerate(self.visible()) if t.key == previous.key), self.index)
        self.dirty = True

    def set_sort(self, mode, descending=None):
        self.sort_mode = mode
        self.sort_descending = (mode != "Ticket") if descending is None else descending
        self.tickets = ordered(self.tickets, mode, self.sort_descending, self.evidence.worklog)
        self.index, self.offset, self.preview_scroll = 0, 0, 0
        self.focus_pane = "list"
        self.store.save("@app", {"sort_mode": mode, "sort_descending": self.sort_descending})
        self.message = "Sorted by " + mode + (" (descending)" if self.sort_descending else " (ascending)")
        self.dirty = True

    def resize_sections(self, change):
        if change == 0:
            self.list_fraction = 0.3
        else:
            height, width = self.screen.getmaxyx()
            ticket_rect, detail_rect = panel_rects(height, width, self.focus_pane, self.list_fraction)
            if not ticket_rect or not detail_rect:
                self.message = "Use at least 18 terminal rows to resize sections"
                return
            available = ticket_rect[2] + detail_rect[2]
            rows = max(5, min(available - 8, ticket_rect[2] + change))
            self.list_fraction = rows / available
        self.store.save("@app", {"list_fraction": self.list_fraction})
        percentage = round(self.list_fraction * 100)
        self.message = f"Tickets {percentage}% / details {100 - percentage}%   +/- resize   = reset"
        self.dirty = True

    def choose_sort(self):
        selected = SORT_MODES.index(self.sort_mode)
        while True:
            self.drain()
            self.screen.erase()
            self.put(1, 2, "SORT TICKETS", curses.A_BOLD)
            self.put(2, 2, "j/k choose · Enter apply · Esc cancel · O reverse current sort")
            for i, mode in enumerate(SORT_MODES):
                self.put(4 + i, 2, ("> " if i == selected else "  ") + mode,
                         curses.A_REVERSE if i == selected else 0)
            self.put(13, 2, "Dates: newest first by default. Missing dates always go last.")
            self.put(14, 2, "Last commit: your git commits on the ticket plus its PR's commits.")
            self.screen.refresh()
            try:
                key = self.screen.get_wch()
            except curses.error:
                continue
            if key in ("j", curses.KEY_DOWN):
                selected = (selected + 1) % len(SORT_MODES)
            elif key in ("k", curses.KEY_UP):
                selected = (selected - 1) % len(SORT_MODES)
            elif key in ("\n", "\r"):
                self.set_sort(SORT_MODES[selected])
                break
            elif key == "O":
                self.set_sort(self.sort_mode, not self.sort_descending)
                break
            elif key in ("\x1b", "q"):
                break
        self.screen.clear()
        self.dirty = True

    def choose(self, title, options, hint="j/k choose · Enter apply · Esc cancel"):
        """Full-screen picker; returns the chosen index or None."""
        selected = 0
        try:
            while True:
                self.screen.erase()
                self.put(1, 2, title, curses.A_BOLD)
                self.put(2, 2, hint)
                for i, option in enumerate(options):
                    self.put(4 + i, 2, ("> " if i == selected else "  ") + option,
                             curses.A_REVERSE if i == selected else 0)
                self.screen.refresh()
                try:
                    key = self.screen.get_wch()
                except curses.error:
                    continue
                if key in ("j", curses.KEY_DOWN):
                    selected = (selected + 1) % len(options)
                elif key in ("k", curses.KEY_UP):
                    selected = (selected - 1) % len(options)
                elif isinstance(key, str) and key.isdigit() and 1 <= int(key) <= len(options):
                    return int(key) - 1
                elif key in ("\n", "\r"):
                    return selected
                elif key in ("\x1b", "q"):
                    return None
        finally:
            self.screen.clear()
            self.dirty = True

    def launch_agent(self, ticket):
        if self.demo:
            self.message = "Demo: agent launch disabled"
            return
        choice = self.choose(f"AGENT WORKFLOW FOR {ticket.key}",
                             [f"{i + 1}  {label}" for i, (label, *_) in enumerate(AGENT_TASKS)],
                             "Runs in the ticket's worktree; exit returns here · j/k · Enter · Esc cancel")
        if choice is None:
            self.message = "Agent launch cancelled"
            return
        _, template, skill = AGENT_TASKS[choice]
        if template is None:
            text = self.prompt(f"Agent prompt ({ticket.key})")
            if not text or not text.strip():
                self.message = "Agent launch cancelled"
                return
            text = text.strip()
            prompt = text if ticket.key.casefold() in text.casefold() else f"{ticket.key}: {text}"
        else:
            prompt = agent_prompt(ticket.key, template, skill)
        path = ticket.worktree
        if not path:
            self.message = f"{ticket.key} has no worktree yet; configure workspace.repository and create or select a local worktree"
            return
        workflow = self.workflow_factory()
        self.background('agent', 'Starting agent for ' + ticket.key,
                        lambda: workflow.agent(ticket.key, path, prompt), 'launch')

    def start_work(self, ticket):
        if self.demo:
            self.message = 'Demo: creating worktrees is disabled'
            return
        if not config.get('workspace', 'repository'):
            self.message = 'Configure workspace.repository first; Jira stays read-only'
            return
        if ticket.key.startswith('PR-') and not any(row.get('key') == ticket.key for row in self.evidence.jira.get('tickets', [])):
            self.message = 'Use the PR branch checkout; creating a ticket worktree needs a Jira key'
            return
        workflow = self.workflow_factory()
        self.background('workspace', 'Opening local worktree for ' + ticket.key,
                        lambda: workflow.start(ticket.key, ticket.title), 'launch')

    def run_foreground(self, action):
        """Temporarily hand this terminal to a shell/agent and restore curses."""
        curses.def_prog_mode()
        curses.endwin()
        try:
            status = terminal.run_request(action)
            self.message = action['label'] + (' closed; back in Sidequest' if status == 0 else ' exited with status ' + str(status))
        except (OSError, RuntimeError) as exc:
            self.message = 'Could not start ' + Path(action['argv'][0]).name + '; check the command and worktree'
        finally:
            curses.reset_prog_mode()
            self.screen.clear()
            self.dirty = True
        self.load_worktrees()

    def background(self, name, label, task, event="message"):
        if name in self.jobs:
            self.message = label + " already in progress"
            return
        self.jobs[name] = (label, time.monotonic())
        self.dirty = True

        def worker():
            try:
                self.events.put((event, task()))
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                self.events.put(("heroku_error" if name == "heroku" else "message", str(exc)))
            except Exception as exc:  # noqa: BLE001 - a worker bug must reach the status line, not draw a traceback over curses
                self.events.put(("heroku_error" if name == "heroku" else "message", unexpected(label, exc)))
            finally:
                self.events.put(("job_done", name))

        threading.Thread(target=worker, daemon=True).start()

    def load_worktrees(self):
        if not self.demo:
            self.background("worktrees", "Loading worktrees", worktrees, "worktrees")

    def refresh_environments(self, quiet=False):
        """quiet: automatic checks (startup, after refresh) don't replace the status message."""
        if self.demo:
            if not quiet:
                self.message = "Demo: sample Heroku status; external actions disabled"
            return
        if not config.get('heroku', 'pipeline'):
            if not quiet:
                self.message = 'Heroku is disabled; configure heroku.pipeline to enable it'
            return
        numbers = sorted({p["number"] for t in self.tickets for p in t.prs})
        if numbers:
            self.background("heroku", "Loading Heroku environments", lambda: fetch_environments(
                numbers, run, config.get('heroku', 'pipeline')), "heroku")
        elif not quiet:
            self.message = "No linked PRs to check for Heroku environments"

    def refresh_worklog(self):
        if not self.demo and config.get('workspace', 'repository'):
            tickets = [{"key": t.key, "worktree": self.evidence.windows.get(t.key, "")} for t in self.tickets]
            self.background("worklog", "Loading dated work history", lambda: collect_worklog(tickets, ROOT, run), "worklog")

    def environment(self, ticket):
        entries = self.evidence.environments.get("entries", {})
        statuses = [entries[str(p["number"])].get("status", "Unknown")
                    for p in ticket.prs if str(p["number"]) in entries]
        if statuses:
            stale = self.evidence.environment_error or any(
                not parse_time(entries[str(p["number"])].get("checked_at")) or
                (now() - parse_time(entries[str(p["number"])].get("checked_at"))).total_seconds() > 300
                for p in ticket.prs if str(p["number"]) in entries)
            suffix = " (refreshing)" if "heroku" in self.jobs else " (cached)" if stale else ""
            return " / ".join(dict.fromkeys(statuses)) + suffix
        return "Loading" if "heroku" in self.jobs else "Unavailable" if self.evidence.environment_error else "Not checked" if ticket.prs else "No linked PR"

    def pr_label(self, ticket):
        return " / ".join(f"#{p['number']}" for p in ticket.prs) if ticket.prs else "none linked"

    def visible(self):
        return [t for t in self.tickets if t.lane != "Done"
                and (self.view == "All" or t.lane == self.view)
                and self.query.casefold() in f"{t.key} {t.title} {t.status} {t.action}".casefold()]

    def selected(self):
        rows = self.visible()
        self.index = max(0, min(self.index, len(rows) - 1))
        return rows[self.index] if rows else None

    def refresh(self):
        if self.demo:
            self.message = "Demo: isolated sample data; live refresh disabled"
            return
        if self.refreshing:
            return
        self.refreshing = True
        self.refresh_started = time.monotonic()
        self.refresh_status = "Loading Jira + GitHub"
        self.dirty = True

        def worker():
            result = ({}, [], {EVERY})
            try:
                result = self.evidence.collect(run)
            except Exception as exc:  # noqa: BLE001 - see background(); refresh must still finish
                result = ({}, [unexpected("Refresh", exc)], {EVERY})
            finally:
                # Always finish, or self.refreshing stays True and r silently does nothing.
                self.events.put(("refreshed", result))

        threading.Thread(target=worker, daemon=True).start()

    def drain(self):
        changed = False
        while True:
            try:
                name, data = self.events.get_nowait()
            except queue.Empty:
                break
            self.dirty = True
            if name in EVIDENCE_EVENTS:
                changed = self.evidence.apply(name, data) or changed
                if name == "worktrees":
                    self.refresh_worklog()
                elif name == "heroku_error":
                    self.notify(data)
            elif name == "message":
                self.notify(data)
            elif name == "job_done":
                self.jobs.pop(data, None)
            elif name == 'launch':
                if data.foreground is not None:
                    self.foreground_target = data.foreground
                    if data.key:
                        self.evidence.windows[data.key] = data.foreground['cwd']
                        changed = True
                if data.message:
                    self.notify(data.message)
            elif name == "refreshed":
                changed = self.evidence.finish_refresh(data) or changed
                self.refreshing = False
                self.refresh_status = ""
                messages = data[1]
                self.notify(("Refresh incomplete: " + " | ".join(messages)) if messages else "Refreshed through sidequest-data (read only)")
                self.load_worktrees()
                self.refresh_environments(quiet=True)
        if changed:
            self.rebuild()

    def notify(self, text):
        """Show a background result without overwriting what you just did."""
        if self.user_message_at and time.monotonic() - self.user_message_at < 4:
            self.deferred_message = text
        else:
            self.message = text

    def put_parts(self, y, x, parts, limit):
        """Draw (text, attr) pieces left to right, stopping at column `limit`."""
        for text, attr in parts:
            if x >= limit:
                break
            self.put(y, x, text, attr, limit - x)
            x += len(text)
        return x

    def key_parts(self, groups, width):
        """Grouped key hints: GROUP key desc  key desc │ GROUP ... ; drops trailing groups that don't fit."""
        bold, dim, accent = curses.A_BOLD, curses.A_DIM, self.style("accent")

        def render(chosen, compact):
            parts = []
            for i, (label, keys) in enumerate(chosen):
                if i:
                    parts.append((" │ " if compact else "  │  ", dim))
                if label:
                    parts.append((label + " ", accent | bold))
                for j, item in enumerate(keys):
                    key, desc = item[0], item[2] if compact and len(item) > 2 else item[1]
                    parts += [("  " if j else "", 0), (key, bold), ((" " + desc) if desc else "", 0)]
            return parts

        def fits(parts):
            return sum(len(t) for t, _ in parts) <= width

        chosen = list(groups)
        for compact in (False, True):
            if fits(render(chosen, compact)):
                return render(chosen, compact)
        while len(chosen) > 1 and not fits(render(chosen, True)):
            chosen.pop(0)           # movement keys are the most familiar; actions and help/quit stay
        return render(chosen, True)

    def put(self, y, x, text, attr=0, width=None):
        height, columns = self.screen.getmaxyx()
        if y < 0 or y >= height or x < 0 or x >= columns:
            return
        clean = "".join(c if c.isprintable() else " " for c in str(text))
        try:
            self.screen.addnstr(y, x, clean, max(0, min(columns - x - 1, width or columns)), attr)
        except curses.error:
            pass

    def standup_data(self):
        data = standup.preview(self.tickets, self.evidence.worklog, now(), self.standup_time, self.escalate_days, self.stale_days)
        if not self.demo:
            # Optional saved standup: the saved report's section, when it covers this meeting.
            data["written"] = standup.written(self.snapshots.parent / "reports", data["meeting"])
        return data

    def copy_standup(self):
        text = standup.as_text(self.standup_data())
        try:
            subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=5)
            self.message = "Standup copied to the clipboard"
        except (OSError, subprocess.SubprocessError):
            self.message = "Couldn't copy (pbcopy unavailable); use sidequest --standup in a terminal"

    def details(self, ticket):
        errors = ["REFRESH ERROR (cached data)", *self.evidence.refresh_errors, ""] if self.evidence.refresh_errors else []
        return errors + self.ticket_details(ticket)

    def ticket_details(self, ticket):
        if self.detail_tab == "Standup":
            jira_time = (self.evidence.jira or self.evidence.fallback).get("generated_at")
            return standup.view_lines(self.standup_data(),
                                      f"Jira {source_age(jira_time)} · GitHub {source_age(self.evidence.prs.get('generated_at'))} · "
                                      f"git {source_age(self.evidence.worklog.get('generated_at'))}")
        if not ticket:
            return ["No tickets in this view.", "Press r to refresh, / to search, or 1 for All."]
        if self.detail_tab in ("Plan", "Updates"):
            return self.plan_lines(ticket, self.detail_tab)
        if self.detail_tab == "Activity":
            events = ticket_activity(ticket)
            comments = ("Jira comments not loaded yet (r)" if ticket.jira_comment_total is None else
                        f"Jira comments {len(ticket.jira_comments)} of {ticket.jira_comment_total}, "
                        f"checked {source_age(ticket.jira_comments_checked_at)}")
            return [f"{len(events)} events, newest first · {comments}", ""] + (
                timeline(events, now()) if events else ["No dated activity loaded."])
        if self.detail_tab == "Workflow":
            stage = stage_context(ticket)
            return [ticket.key + " · WORKFLOW", ticket.title, "",
                    *workflow_strip(ticket), "Turn: " + next_owner(ticket) + " (" + ownership(ticket)[1] + ")",
                    "Your next action: " + ticket.action, "",
                    "WORKFLOW", *workflow_path(ticket), "",
                    "To move forward: " + stage["next"],
                    f"Jira status: {ticket.status}",
                    "", "Clock source: " + ticket.wait_source,
                    "Since: " + readable_date(ticket.wait_since),
                    "First assigned to you: " + readable_date(ticket.first_assigned_at),
                    "Jira status since: " + readable_date(ticket.status_since),
                    "Configure thresholds with --stale-days N and --escalate-days N.",
                    "Earlier/later indicate position, not verified completion. Review or QA can return work to implementation."]
        if self.detail_tab == "Work log":
            return [ticket.key + " · DATED WORK SUMMARY", ticket.title, "",
                    "Your commits (git + PR), grouped by local date.",
                    "Commit timestamps are evidence, not hours worked or ticket completion.",
                    "Git coverage: latest 2,000 authored commits from the past 90 days.", ""] + daily_summary(
                        ticket, self.evidence.worklog.get("entries", {}).get(ticket.key, [])) + [
                        "", "Source checked: " + readable_date(self.evidence.worklog.get("generated_at")),
                        *self.evidence.worklog.get("errors", []), "a: activity · v: overview"]
        stage = stage_context(ticket)
        lines = [ticket.key, ticket.title, "", "STATUS", *workflow_strip(ticket),
                 "Turn: " + next_owner(ticket) + " (" + ownership(ticket)[1] + ")",
                 "To move forward: " + stage["next"],
                 f"Priority: {ticket.priority or 'unknown'} · Jira status: {ticket.status}", "",
                 "DATES",
                 f"Last commit: {readable_date(last_commit(ticket, self.evidence.worklog))}",
                 f"Last Jira update: {readable_date(ticket.updated)}",
                 f"First assigned to you: {readable_date(ticket.first_assigned_at)}",
                 f"Jira status since: {readable_date(ticket.status_since)}",
                 f"Clock source: {ticket.wait_source}",
                 f"Since: {readable_date(ticket.wait_since)} · {ticket.wait_label} business time"
                 f" (follow up after {self.stale_days} business days)",
                 "", "HEROKU ENVIRONMENT", self.environment(ticket)]
        for pr in ticket.prs:
            env = self.evidence.environments.get("entries", {}).get(str(pr["number"]), {})
            if env:
                lines += [f"PR #{pr['number']}: {env.get('status', 'Unknown')} · {source_age(env.get('checked_at'))}",
                          env.get("app", ""), env.get("url", "")]
                if env.get("warning"):
                    lines += [env["warning"]]
        if self.evidence.environment_error:
            lines += ["Last refresh failed; cached results may be stale.", self.evidence.environment_error]
        lines += ["Web up means a web dyno is up; HTTP readiness is not checked.", ""]
        for pr in ticket.prs:
            decision = (pr.get("review_decision") or "Awaiting review").replace("_", " ").lower()
            lines += ["GITHUB PR", f"PR #{pr['number']}: {pr.get('title') or ticket.title}",
                      f"{decision} · CI: {pr.get('ci', 'unknown')}",
                      "Reviewers: " + (", ".join(pr.get("requested_reviewers", [])) or "none requested") +
                      f" · {pr.get('unresolved_count', 0)} unresolved threads",
                      pr.get("url") or "No PR URL in this snapshot",
                      f"Branch: {pr.get('branch') or 'unknown'}" + (" · Draft" if pr.get("wip") else ""),
                      f"Source activity: {readable_date(pr.get('updated_at'))}"]
        lines += ["", "WORKSPACE", "Worktree: " + (ticket.worktree or "not found"),
                  "w / gw: open the existing tmux ticket window"]
        return lines

    def plan_lines(self, ticket, view="Plan"):
        """Read the selected document view; cache both views until the file changes."""
        path = PLANS / ticket.key / "plan.md"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            if view == "Updates":
                return [f"No updates recorded yet for {ticket.key}.", "", str(path)]
            return [f"No plan yet for {ticket.key}.", "",
                    f'Space s → Custom: "start {ticket.key} and write the plan" asks your agent to write it to',
                    str(path)]
        cached = self.plan_cache.get(ticket.key)
        if not cached or cached[0] != mtime:
            try:
                text = path.read_text(errors="replace")
            except OSError as exc:
                return [f"Couldn't read {path}: {exc.strerror}"]
            cached = (mtime, document_views(text, PLAN_HEADING))
            self.plan_cache[ticket.key] = cached
        stamp = datetime.fromtimestamp(cached[0], tz=now().tzinfo).isoformat()
        age = relative(stamp, now())
        edited = "edited just now" if age == "now" else f"edited {age} ago"
        lines = cached[1][view] or [f"No {view.lower()} recorded yet for {ticket.key}."]
        return [f"{path.parent.parent.name}/{path.parent.name}/{path.name} · {edited}", ""] + lines

    def style(self, name):
        return self.styles.get(name, 0)

    def setup_colors(self):
        # NO_COLOR (https://no-color.org) wins; glyph shapes and heavy borders still carry meaning.
        if os.environ.get("NO_COLOR") or not curses.has_colors():
            return
        curses.start_color()
        try:
            curses.use_default_colors()
            background = -1
        except curses.error:
            background = curses.COLOR_BLACK
        for i, (name, color) in enumerate((("accent", curses.COLOR_CYAN),
                ("Needs me", curses.COLOR_RED),
                ("Waiting", curses.COLOR_GREEN), ("Clarify", curses.COLOR_MAGENTA),
                ("good", curses.COLOR_GREEN), ("bad", curses.COLOR_RED)), 1):
            curses.init_pair(i, color, background)
            self.styles[name] = curses.color_pair(i)

    def loading_line(self):
        loading = []
        if self.refreshing:
            loading.append((self.refresh_status, self.refresh_started))
        loading += list(self.jobs.values())
        if not loading:
            return ""
        label, started = loading[0]
        spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(time.monotonic() * 10) % 10]
        extra = f" +{len(loading) - 1}" if len(loading) > 1 else ""
        return f"{spinner} {label} · {int(time.monotonic() - started)}s{extra}"

    def source_failed(self, name):
        return self.evidence.failed({"Jira": "jira", "GitHub": "prs"}[name])

    def header_status(self):
        """Right side of the header: what's loading, else the sort and how fresh the data is."""
        loading = self.loading_line()
        if loading:
            return loading, self.style("accent"), False
        sources = (("Jira", self.evidence.jira or self.evidence.fallback), ("GitHub", self.evidence.prs))
        # A source that is not configured is "off", not stale; one whose last refresh failed says so
        # next to the age of the data still shown, instead of reading as freshly refreshed.
        active = [(name, data) for name, data in sources if data.get("enabled") is not False]
        stale = any(not parse_time(data.get("generated_at")) or
                    (now() - parse_time(data.get("generated_at"))).total_seconds() > 3600 for _, data in active)

        def label(name, data):
            if data.get("enabled") is False and not self.source_failed(name):
                return name + " off"
            age = relative(data.get("generated_at"), now()) or "not loaded"
            return f"{name} {'failed, data ' + age if self.source_failed(name) else age}"
        arrow = "↓" if self.sort_descending else "↑"
        text = (f"Sort: {self.sort_mode} {arrow}  ·  Refreshed " + " · ".join(label(n, d) for n, d in sources)
                + ("  STALE" if stale else ""))
        if self.evidence.refresh_errors:
            text = "ERROR · " + text
        return text, curses.A_BOLD if self.evidence.refresh_errors else curses.A_DIM, stale or bool(self.evidence.refresh_errors)

    def tone(self, glyph):
        return self.style(TONE.get(glyph, ""))

    def draw_box(self, y, x, h, w, title, focused, label=""):
        attr = (curses.A_BOLD | self.style("accent")) if focused else curses.A_DIM
        self.put(y, x, border(w, title, focused), attr, w + 1)
        self.put(y + h - 1, x, border(w, title, focused, top=False, label=label), attr, w + 1)
        side = (HEAVY if focused else LIGHT)[3]
        for row in range(y + 1, y + h - 1):
            self.put(row, x, side, attr)
            self.put(row, x + w - 1, side, attr)

    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 12 or width < 64:
            self.put(0, 0, "Resize terminal to at least 64 columns x 12 rows. q: quit")
            self.screen.refresh()
            return
        bold, accent = curses.A_BOLD, self.style("accent")
        clock = now()

        # Row 0: title, lane tabs with counts, then sort/freshness (or what's loading) on the right.
        parts = [(" Sidequest" + (" · DEMO" if self.demo else "") + "  ", bold | accent)]
        compact = width < 130
        for i, view in enumerate(VIEWS):
            count = sum(t.lane != "Done" and (view == "All" or t.lane == view) for t in self.tickets)
            label = lane_tab(i + 1, view, count, self.view == view, compact)
            parts.append((label, (curses.A_REVERSE | bold) if self.view == view else self.style(view) or 0))
        x = self.put_parts(0, 0, parts, width - 1)
        status, status_attr, stale = self.header_status()
        if stale and not self.loading_line():
            status_attr = self.style("Needs me") or bold
        room = width - x - 3
        if len(status) > room and not self.loading_line():
            status = status.replace("Sort: ", "").replace("  ·  ", " · ").replace("GitHub", "GH")
        if room > 12:
            status = status if len(status) <= room else status[:room - 1] + "…"
            self.put(0, width - len(status) - 2, status, status_attr)

        # Panels: the one your keys control has a heavy, coloured border.
        rows = self.visible()
        ticket = self.selected()
        list_active = self.focus_pane == "list"
        list_rect, preview_rect = panel_rects(height, width, self.focus_pane, self.list_fraction)
        if list_rect:
            top, _, panel_h, list_w = list_rect
            title = f"Tickets {len(rows)}" + (f"  /{self.query}" if self.query else "")
            inner_w = list_w - 2
            with_when = self.sort_mode in DATE_SORTS
            cols = columns(inner_w, with_when)
            self.put(top + 1, 1, table_header(cols), curses.A_DIM, inner_w)
            capacity = max(1, panel_h - 3)
            self.page_size = capacity
            self.offset = min(self.offset, self.index)
            if self.index >= self.offset + capacity:
                self.offset = self.index - capacity + 1
            self.draw_box(top, 0, panel_h, list_w, title, list_active, scroll_label(self.offset, capacity, len(rows)))
            ci_x = 1 + cols["glyph"] + pr_glyph_offset(cols)
            for i, item in enumerate(rows[self.offset:self.offset + capacity], self.offset):
                y = top + 2 + (i - self.offset)
                selected = i == self.index
                when = relative(activity_date(item, self.sort_mode, self.evidence.worklog), clock) if with_when else ""
                glyph, rest = table_row(item, cols, when)
                # Selection is solid while the list has the keys, underlined while the preview does.
                sel = (curses.A_REVERSE if list_active else curses.A_UNDERLINE) if selected else 0
                self.put(y, 1, glyph, (sel or self.style(item.lane)) | bold, inner_w)
                self.put(y, 1 + len(glyph), rest, sel | (bold if selected else 0), inner_w - len(glyph))
                pr_cell = rest[pr_glyph_offset(cols) - 0:pr_glyph_offset(cols) + cols["pr"]].split(" ")
                if len(pr_cell) > 1 and pr_cell[1] in TONE:
                    self.put(y, ci_x + len(pr_cell[0]) + 1, pr_cell[1],
                             sel | bold | self.tone(pr_cell[1]), 1)
            if not rows:
                self.put(top + 3, 2, "No matching tickets. r: refresh  /: search  Esc: clear", curses.A_DIM)
        if preview_rect:
            top, px, panel_h, pw = preview_rect
            title = f"{ticket.key} · {ticket.title}" if ticket else "No ticket"
            x, detail_width = px + 2, pw - 4
            def tab_strip(short):
                parts = []
                for key, label, name in TABS:
                    label = label.split()[0] if short else label
                    parts += [(f" {key} {label} ", (curses.A_REVERSE | bold) if self.detail_tab == name else accent)]
                return parts
            tabs = tab_strip(False)
            if sum(len(t) for t, _ in tabs) > detail_width:
                tabs = tab_strip(True)
            self.put_parts(top + 1, x - 1, tabs, x + detail_width)
            y0 = top + 3
            if ticket and self.detail_tab != "Standup":
                summary = card(ticket, clock, last_commit(ticket, self.evidence.worklog), self.environment(ticket), self.stale_days)
                if panel_h < 16:
                    summary = summary[:2]
                for i, line in enumerate(summary):
                    attr = (bold | self.style(ticket.lane)) if i == 0 else curses.A_BOLD if line.startswith("→") else 0
                    self.put(y0 + i, x, line, attr, detail_width)
                    if line.startswith("PR #"):
                        pieces = line.split(" ")
                        if len(pieces) > 2 and pieces[2] in TONE:
                            self.put(y0 + i, x + len(pieces[0]) + len(pieces[1]) + 2, pieces[2],
                                     bold | self.tone(pieces[2]), 1)
                self.put(y0 + len(summary), x, "─" * detail_width, curses.A_DIM, detail_width)
                y0 += len(summary) + 1
            lines = []
            details = self.details(ticket)
            if ticket and len(details) > 1 and details[0].startswith(ticket.key) and details[1] == ticket.title:
                details = details[2:]                    # key and title are already in the panel border
            while details and not details[0].strip():
                details = details[1:]
            for line in details:
                indent = " " * (len(line) - len(line.lstrip(" ")))
                if self.detail_tab == "Activity" and re.match(r"\d\d:\d\d ", line):
                    indent = " " * EVENT_INDENT
                lines += textwrap.wrap(line, max(10, detail_width), subsequent_indent=indent) or [""]
            body_height = max(1, top + panel_h - 1 - y0)
            self.preview_page_size = body_height
            self.preview_scroll = min(self.preview_scroll, max(0, len(lines) - body_height))
            self.draw_box(top, px, panel_h, pw, title, not list_active,
                          scroll_label(self.preview_scroll, body_height, len(lines)))
            for y, line in enumerate(lines[self.preview_scroll:self.preview_scroll + body_height], y0):
                if line.startswith(DAY_RULE) or line.startswith(PLAN_HEADING):
                    line = line[len(PLAN_HEADING):] if line.startswith(PLAN_HEADING) else line
                    self.put(y, x, line, bold | accent, detail_width)
                    continue
                if self.detail_tab == "Activity" and line.startswith(" "):
                    self.put(y, x, line, curses.A_DIM, detail_width)
                    continue
                if self.detail_tab == "Activity" and re.match(r"\d\d:\d\d ", line):
                    self.put(y, x, line, 0, detail_width)
                    mark = line[EVENT_INDENT - 2:EVENT_INDENT - 1]
                    self.put(y, x + EVENT_INDENT - 2, mark, bold | (self.tone(mark) or accent), 1)
                    continue
                heading = line in ("STATUS", "DATES", "WORKFLOW", "HEROKU ENVIRONMENT", "GITHUB PR", "WORKSPACE", "STANDUP PREVIEW") \
                    or (self.detail_tab == "Standup" and line.endswith(":") and not line.startswith("-"))
                current = "YOU ARE HERE" in line
                self.put(y, x, line, (bold | curses.A_REVERSE) if current else bold | accent if heading else 0, detail_width)

        # Bottom: the keys that work right now, then the message line.
        footer = [(label, [(k, ("scroll" if self.focus_pane == "preview" else d) if k == "j/k" else d, *rest)
                           for k, d, *rest in keys]) for label, keys in FOOTER]
        self.put_parts(height - 2, 1, self.key_parts(footer, width - 3), width - 1)
        self.put(height - 1, 1, self.message)
        self.screen.refresh()

    def prompt(self, label, initial=""):
        value, cursor = initial, len(initial)
        curses.curs_set(1)
        try:
            while True:
                height, width = self.screen.getmaxyx()
                self.screen.move(height - 1, 0)
                self.screen.clrtoeol()
                prefix = label + ": "
                available = max(1, width - len(prefix) - 2)
                start = max(0, cursor - available + 1)
                self.put(height - 1, 0, prefix + value[start:start + available])
                self.screen.move(height - 1, min(width - 2, len(prefix) + cursor - start))
                self.screen.refresh()
                key = self.screen.get_wch()
                if key in ("\n", "\r"):
                    return value
                if key == "\x1b":
                    return None
                if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    if cursor:
                        value, cursor = value[:cursor - 1] + value[cursor:], cursor - 1
                elif key == curses.KEY_LEFT:
                    cursor = max(0, cursor - 1)
                elif key == curses.KEY_RIGHT:
                    cursor = min(len(value), cursor + 1)
                elif key in (curses.KEY_HOME, "\x01"):
                    cursor = 0
                elif key in (curses.KEY_END, "\x05"):
                    cursor = len(value)
                elif key == "\x15":
                    value, cursor = value[cursor:], 0
                elif isinstance(key, str) and key.isprintable():
                    value = value[:cursor] + key + value[cursor:]
                    cursor += 1
        finally:
            curses.curs_set(0)

    def open_url(self, ticket, pr=False):
        known_jira = any(issue.get('key') == ticket.key for issue in self.evidence.jira.get('tickets', []))
        url = (ticket.prs[0].get("url") if pr and ticket.prs else
               config.get('jira', 'site').rstrip('/') + f"/browse/{ticket.key}" if not pr and known_jira and is_key(ticket.key) and config.get('jira', 'site') else None)
        from urllib.parse import urlsplit
        allowed = {'github.com', urlsplit(config.get('jira', 'site')).hostname}
        if self.demo or not url or urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in allowed:
            self.message = "No supported link available" if not self.demo else "Demo: external actions disabled"
            return
        self.background("browser", "Opening browser", lambda: open_in_edge(run, url))

    def jump(self, ticket):
        if self.demo:
            self.message = "Demo: workspace jumps disabled"
            return
        workflow = self.workflow_factory()
        self.background('workspace', 'Finding ' + ticket.key + ' workspace',
                        lambda: workflow.open(ticket.key, ticket.worktree), 'launch')

    def action(self, key):
        ticket = self.selected()
        if not ticket:
            return
        if key == "j":
            self.open_url(ticket)
        elif key == "o":
            self.open_url(ticket, pr=True)
        elif key == "w":
            self.jump(ticket)
        elif key == "s":
            self.launch_agent(ticket)
        elif key == "n":
            self.start_work(ticket)

    def help(self):
        self.screen.erase()
        lines = ["Sidequest attention queue / keys", "",
                 "MOVE",
                 "  j/k, arrows   Next / previous ticket (or scroll the preview)   gg / G  First / last",
                 "  Ctrl-f/b      Page the ticket list          Ctrl-d/u  Scroll the preview",
                 "  h / l, Enter  List / preview pane           gl / gL   Next / previous ticket needing you",
                 "  + / -         Grow / shrink ticket section   =       Reset 30/70 split (size is remembered)",
                 "  1..4          All / Needs me / Waiting / Clarify",
                 "  /             Filter tickets (Enter applies)  Esc     Clear filter, back to list",
                 "",
                 "WAIT starts at the later of Jira status entry or first assignment to you.",
                 "  Comments, commits and PR reviews do not reset WAIT.",
                 "  Mon–Fri 09–17 in your configured timezone; 8h = 1d. Missing history uses labeled observed wait.",
                 "VIEWS (details pane)",
                 "  a Activity (Jira + GitHub events only; opens first)   p Plan (tickets/DEMO-###/plan.md)",
                 "  d Updates (progress and recorded results)   v Overview",
                 "  s Work log   f Flow   u Standup (y copies it)",
                 "  The card on top: lane · stage · whose turn · waiting; PR + CI; dates; → your next step.",
                 "  Activity marks: ✓ approved ✗ changes requested ✎ comment • commit ↻ updated (a bare",
                 "  'updated' stamp doesn't say what changed).",
                 "",
                 "OPEN  (press Space, then)",
                 "  j Jira   o PR   w worktree shell   s agent workflows / custom prompt",
                 "  n create/reuse a local ticket worktree and open a shell; exit returns here",
                 "",
                 "DATA",
                 "  r refresh Jira + GitHub via sidequest-data   e recheck Heroku   o / O choose / reverse sort",
                 "  w / gw  open the worktree through shell, tmux or Herdr",
                 "  ? help   q / Ctrl-q quit",
                 "",
                 "Text fields: Enter saves, Esc cancels, Ctrl-a/e move, Ctrl-u clears to start.",
                 f"Waiting stays one lane; reminders after {self.stale_days} business days, escalation after {self.escalate_days}.",
                 "Limits: assigned Jira inventory is paginated; 100 open PRs is an explicit limit. No Jira/GitHub writes from this tool;",
                 "Agent command: workspace.agent_command (default claude; configure your preferred CLI).",
                 "Terminal: workspace.terminal or SIDEQUEST_TERMINAL (auto, shell, tmux, herdr).",
                 "", "Press any key to return."]
        height, _ = self.screen.getmaxyx()
        for y, line in enumerate(lines[:height - 1]):
            heading = line and not line.startswith(" ") and line.isupper() or line.startswith(("VIEWS", "OPEN"))
            self.put(y, 1, line, (curses.A_BOLD | self.style("accent")) if heading or y == 0 else 0)
        self.screen.refresh()
        self.screen.timeout(-1)
        self.screen.get_wch()
        self.screen.timeout(50)

    def loop(self, screen):
        self.screen = screen
        curses.curs_set(0)
        curses.set_escdelay(25)
        self.setup_colors()
        screen.keypad(True)
        screen.timeout(50)
        self.load_worktrees()
        self.refresh_environments(quiet=True)
        pending = ""
        space_hint = space_before = ""
        last_ranked = time.monotonic()
        last_spinner = -1
        while True:
            self.drain()
            if time.monotonic() - last_ranked >= 60:
                self.rebuild()
                last_ranked = time.monotonic()
            frame = int(time.monotonic() * 8)
            if self.dirty or ((self.refreshing or self.jobs) and frame != last_spinner):
                self.draw()
                self.dirty = False
                last_spinner = frame
            if self.foreground_target:
                action, self.foreground_target = self.foreground_target, None
                self.run_foreground(action)
                continue
            if self.deferred_message and time.monotonic() - self.user_message_at >= 4:
                self.message, self.deferred_message = self.deferred_message, None
                self.dirty = True
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            self.dirty = True
            before = self.message
            try:
                if pending:
                    prefix, pending = pending, ""
                    if prefix == " ":
                        # The menu hint only lives while Space is waiting; Esc or any key puts the
                        # bar back to what it said before (an action may then set its own message).
                        if self.message == space_hint:
                            self.message = before = space_before
                        screen.timeout(-1)
                        try:
                            self.action(key)
                        finally:
                            screen.timeout(50)
                    elif key == "g":
                        self.index, self.preview_scroll = 0, 0
                    elif key == "w":
                        ticket = self.selected()
                        if ticket:
                            self.jump(ticket)
                    elif key in ("l", "L"):
                        rows = self.visible()
                        direction = 1 if key == "l" else -1
                        for step in range(1, len(rows) + 1):
                            i = (self.index + direction * step) % len(rows)
                            if rows[i].lane in ("Needs me", "Clarify") or rows[i].age >= self.stale_days:
                                self.index, self.preview_scroll = i, 0
                                break
                elif key in ("q", "\x11"):
                    return
                elif key in (" ", "g"):
                    pending = key
                    if key == " ":
                        space_before = self.message
                        space_hint = self.message = "Space → " + "  │  ".join(
                            label + ": " + "  ".join(f"{k} {d}" for k, d in keys) for label, keys in SPACE_MENU)
                elif key in ("j", curses.KEY_DOWN, "k", curses.KEY_UP):
                    delta = 1 if key in ("j", curses.KEY_DOWN) else -1
                    if self.focus_pane == "preview":
                        self.preview_scroll = max(0, self.preview_scroll + delta)
                    else:
                        self.index += delta
                        self.preview_scroll = 0
                elif key in ("\x06", "\x02", "G"):
                    self.index = len(self.visible()) - 1 if key == "G" else self.index + (1 if key == "\x06" else -1) * self.page_size
                    self.preview_scroll = 0
                elif key in ("\x04", "\x15"):
                    self.preview_scroll = max(0, self.preview_scroll + (1 if key == "\x04" else -1) * max(1, self.preview_page_size // 2))
                elif key in ("+", "-", "="):
                    self.resize_sections({"+": 1, "-": -1, "=": 0}[key])
                elif key in ("h", "l", "\n", "\r"):
                    self.focus_pane = "list" if key == "h" else "preview"
                elif isinstance(key, str) and key in "1234":
                    self.view, self.index, self.preview_scroll = VIEWS[int(key) - 1], 0, 0
                elif key == "/":
                    screen.timeout(-1)
                    try:
                        query = self.prompt("Search", self.query)
                    finally:
                        screen.timeout(50)
                    if query is not None:
                        self.query, self.index = query, 0
                elif key == "\x1b":
                    self.query, self.focus_pane, self.preview_scroll = "", "list", 0
                elif key == "r":
                    self.refresh()
                elif key == "e":
                    self.refresh_environments()
                elif key == "o":
                    self.choose_sort()
                elif key == "O":
                    self.set_sort(self.sort_mode, not self.sort_descending)
                elif key == "w":
                    ticket = self.selected()
                    if ticket:
                        self.jump(ticket)
                elif key == "y" and self.detail_tab == "Standup":
                    self.copy_standup()
                elif key in TAB_KEYS:
                    self.detail_tab = TAB_KEYS[key]
                    self.preview_scroll = 0
                    self.focus_pane = "preview"
                elif key == "?":
                    self.help()
                elif key == curses.KEY_RESIZE:
                    screen.clear()
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                self.message = str(exc)
            if self.message != before:
                self.user_message_at = time.monotonic()


def main():
    parser = argparse.ArgumentParser(prog='sidequest', description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Isolated sample data; no external actions")
    parser.add_argument("--refresh", action="store_true", help="Refresh in background on startup")
    parser.add_argument("--list", action="store_true", help="Print the queue without a TUI")
    parser.add_argument("--standup", action="store_true", help="Print a preview of your next standup and exit")
    parser.add_argument("--update-report", action="store_true",
                        help="Rewrite the Standup section of today's report with the draft from your commits "
                             "(used by sidequest --update-report; the old file is kept in the snapshot directory/report-backups)")
    parser.add_argument("--standup-time", default=os.environ.get("SIDEQUEST_STANDUP_TIME", "09:00"),
                        help="When your standup starts, HH:MM (default 09:00, or $SIDEQUEST_STANDUP_TIME)")
    parser.add_argument("--snapshots", type=Path, default=config.STATE_DIR / 'snapshots')
    parser.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
    parser.add_argument("--stale-days", type=int, default=2)
    parser.add_argument("--escalate-days", type=int, default=5)
    args = parser.parse_args()
    if args.stale_days < 1 or args.escalate_days < args.stale_days:
        parser.error("Require 1 <= stale-days <= escalate-days")
    try:
        standup_time = standup.parse_standup_time(args.standup_time)
    except ValueError:
        parser.error("--standup-time must look like 09:00")
    if args.refresh and not args.demo and (args.list or args.standup or args.update_report):
        run(['sidequest-data', 'collect', '--json', '--out', str(args.snapshots)], timeout=300)
    store = Store(":memory:") if args.demo else Store(args.data_dir / "tickets.sqlite3")
    try:
        app = App(store, args.snapshots, args.demo, args.stale_days, args.escalate_days, standup_time)
        if args.update_report and args.demo:
            parser.error("--update-report needs real data, not --demo")
        if (args.standup or args.list or args.update_report) and not args.demo:
            # The git history (which sets the order) normally loads in the background; collect it once here.
            app.evidence.windows = worktrees()
            app.rebuild()
            try:
                app.evidence.worklog = collect_worklog([{"key": t.key, "worktree": t.worktree} for t in app.tickets], ROOT, run)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                pass
            app.rebuild()
        if args.update_report:
            # Today's report is for today's standup: draft that meeting even after it started
            # (the refresh only adds new Today items to a standup that's already written).
            data = dict(standup.preview(app.tickets, app.evidence.worklog, now(), app.standup_time, app.escalate_days,
                                        app.stale_days, today=True), written=None)
            jira_time = (app.evidence.jira or app.evidence.fallback).get("generated_at")
            sources = (f"Jira {source_age(jira_time)} · GitHub {source_age(app.evidence.prs.get('generated_at'))} · "
                       f"git {source_age(app.evidence.worklog.get('generated_at'))}")
            clock = now()
            result = standup.update_report(args.snapshots.parent / "reports", data, clock, sources,
                                           args.snapshots / "report-backups")
            if result:
                print(f"Standup updated in {result['path']} (for {data['meeting']:%a %d %b %H:%M}).")
                print(f"Previous version: {result['backup']}")
            else:
                print(f"No report for {clock:%Y-%m-%d} yet (reports are supplied by you), so nothing was changed. "
                      f"Draft for {data['meeting']:%a %d %b %H:%M}:\n")
                print(standup.as_text(data))
                raise SystemExit(3)
            return
        if args.standup:
            data = app.standup_data()
            print(f"Next standup: {data['meeting']:%a %d %b, %H:%M}\n")
            print(standup.as_text(data))
            return 1 if app.evidence.refresh_errors else 0
        if args.list:
            for ticket in app.visible():
                stamp = last_commit(ticket, app.evidence.worklog)
                when = stamp.astimezone(now().tzinfo).strftime("%d %b %H:%M") if stamp else "no commits"
                print(f"{ticket.key:<12} {when:<12} {ticket.lane:<12} {ticket.wait_label:>6}  {ticket.action} | {ticket.title}")
            if app.evidence.refresh_errors:
                print('Cached results; refresh incomplete: ' + ' | '.join(app.evidence.refresh_errors), file=sys.stderr)
            return 1 if app.evidence.refresh_errors else 0
        if args.refresh:
            app.refresh()
        curses.wrapper(app.loop)
    except KeyboardInterrupt:
        pass
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
