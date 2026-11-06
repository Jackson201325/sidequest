#!/usr/bin/env python3
"""sidequest-data qa-shot — capture QA screenshots of the local app in Microsoft Edge.

  sidequest-data qa-shot [DEMO-###]              capture every shot in tickets/DEMO-###/qa/shots.json
  sidequest-data qa-shot --only NAME            capture one shot again (repeatable)
  sidequest-data qa-shot --headed               show the Edge window while it works
  sidequest-data qa-shot --pr-markdown          no browser: print the PR Screenshots section and --attach flags
  sidequest-data qa-shot --review-app [--pr N]  run the same shots on the PR's Heroku review app instead

The ticket key defaults to the current branch. shots.json:
  {"base_url": "http://localhost:3010", "viewport": [1440, 900],
   "shots": [{"name": "01-bulk-request-form", "path": "/bulk_requests/new",
              "caption": "Admin > Bulk requests > New", "criterion": "AC1: ...",
              "steps": [{"fill": "#q", "value": "gift"}, {"click": "#search"}, {"click_text": "Add"},
                        {"select": "#state", "value": "open"}, {"wait_for": ".results"},
                        {"expect_text": "1 result"}, {"wait": 500}],
              "full_page": false, "selector": null}]}
Steps run in order; `wait_for` and `expect_text` retry until `timeout` seconds (default 10).
A sign-in form is filled with the local test account (SIDEQUEST_QA_EMAIL / SIDEQUEST_QA_PASSWORD override it),
only for local URLs (localhost, 127.0.0.1, *.localhost such as admin.localhost). Screenshots go next to shots.json; a failed shot saves its screen to
failures/ instead, and manifest.json records the commit, captions and status of every shot.

--review-app: asks Heroku for the open PR's review app (it must be "Web up"), uses its URL as the
base, and writes to tickets/DEMO-###/qa-review/ (shots from qa-review/shots.json if present, else
qa/shots.json). Sign-in requires SIDEQUEST_REVIEW_EMAIL / SIDEQUEST_REVIEW_PASSWORD, and only on that review app's host.
Uses Edge's DevTools protocol directly (standard library only) with its own profile, so it never
touches your normal Edge windows. SIDEQUEST_QA_BROWSER points it at another Chromium-based binary.

Exit codes: 0 all shots ok, 1 a check failed, 2 spec/browser/usage error.
"""
import argparse, base64, json, os, re, shutil, socket, struct, subprocess, sys, tempfile, time
import urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import config, gitutil, qa as qa_evidence, review_apps
from sidequest.ticket_keys import branch_ticket, is_key

EDGE = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chromium", "chromium-browser", "google-chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "microsoft-edge", "microsoft-edge-stable", "msedge")
STEPS = {"click": (), "click_text": (), "fill": ("value",), "select": ("value",), "wait_for": (),
         "expect_text": (), "wait": ()}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}  # plus any *.localhost (admin.localhost): always loopback


def is_local(host):
    host = (host or "").lower().rstrip(".")
    return host in LOCAL_HOSTS or host.endswith(".localhost")
DEFAULT_ACCOUNT = ("", "")  # supplied by each user through environment variables


class Fail(Exception):
    """A QA check failed (exit 1)."""


class Usage(Exception):
    """Spec, browser or usage problem (exit 2)."""


# ---------------------------------------------------------------- websocket (RFC 6455, client side)
def encode_frame(payload, opcode=1, mask=None):
    mask = mask or os.urandom(4)
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 65536:
        head += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", n)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def _parse_header(read):
    b0, b1 = read(2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", read(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", read(8))[0]
    mask = read(4) if b1 & 0x80 else None
    data = read(n)
    if mask:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return b0 & 0x80, b0 & 0x0F, data


def decode_frame(frame):
    buf = memoryview(frame)
    pos = [0]

    def read(k):
        chunk = bytes(buf[pos[0]:pos[0] + k]); pos[0] += k
        return chunk
    _, opcode, data = _parse_header(read)
    return opcode, data


class DevTools:
    def __init__(self, ws_url, timeout=30):
        u = urllib.parse.urlparse(ws_url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
                           % (u.path, u.hostname, u.port, key)).encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise Usage("browser closed the DevTools connection")
            response += chunk
        head, self.pending = response.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise Usage("browser refused the DevTools connection")
        self.next_id = 0

    def _read(self, k):
        while len(self.pending) < k:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise Usage("browser closed the DevTools connection")
            self.pending += chunk
        out, self.pending = self.pending[:k], self.pending[k:]
        return out

    def _message(self):
        parts = b""
        while True:
            fin, opcode, data = _parse_header(self._read)
            if opcode == 8:
                raise Usage("browser closed the DevTools connection")
            if opcode == 9:
                self.sock.sendall(encode_frame(data, opcode=10)); continue
            if opcode in (0, 1, 2):
                parts += data
                if fin:
                    return json.loads(parts.decode())

    def call(self, method, **params):
        self.next_id += 1
        self.sock.sendall(encode_frame(json.dumps({"id": self.next_id, "method": method, "params": params}).encode()))
        while True:
            msg = self._message()
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise Usage("%s failed: %s" % (method, msg["error"].get("message")))
                return msg.get("result", {})

    def js(self, expression):
        if expression.startswith(HELPERS):
            expression = "{" + expression + "\n}"  # block scope: helper consts don't leak between calls
        r = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise Fail("page script error: %s" % r["exceptionDetails"].get("exception", {}).get("description", "?")[:200])
        return r.get("result", {}).get("value")


# ---------------------------------------------------------------- spec
def load_spec(path):
    try:
        spec = json.loads(path.read_text())
    except FileNotFoundError:
        raise Usage("no shots file at %s: write it first (see `sidequest-data qa-shot --help`)" % path)
    except ValueError as exc:
        raise Usage("%s is not valid JSON: %s" % (path, exc))
    shots = spec.get("shots") if isinstance(spec, dict) else None
    if not shots or not isinstance(shots, list):
        raise Usage("%s has no shots" % path)
    seen = set()
    for shot in shots:
        name = shot.get("name") if isinstance(shot, dict) else None
        if not isinstance(name, str) or not NAME.match(name):
            raise Usage("shot name %r must be letters, digits, - or _ (it becomes the file name)" % (name,))
        if name in seen:
            raise Usage("duplicate name %r" % name)
        seen.add(name)
        if not isinstance(shot.get("path"), str) or not shot["path"].startswith(("/", "http://", "https://")):
            raise Usage("shot %s needs a path like /orders" % name)
        for step in shot.get("steps") or []:
            kinds = [k for k in step if k in STEPS] if isinstance(step, dict) else []
            if len(kinds) != 1:
                raise Usage("shot %s has an unknown step %r (use one of %s)" % (name, step, ", ".join(STEPS)))
            missing = [k for k in STEPS[kinds[0]] if k not in step]
            if missing:
                raise Usage("shot %s: %s step needs %s" % (name, kinds[0], ", ".join(missing)))
    return spec


# ---------------------------------------------------------------- browser
def find_browser(explicit):
    for candidate in ([explicit] if explicit else EDGE):
        path = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if path and os.path.exists(path):
            return path
    raise Usage("Microsoft Edge not found%s" % (" at " + explicit if explicit else ""))


def launch(binary, profile, viewport, headed):
    profile.mkdir(parents=True, exist_ok=True)
    port_file = profile / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)
    args = [binary, "--user-data-dir=" + str(profile), "--remote-debugging-port=0", "--no-first-run",
            "--no-default-browser-check", "--disable-sync", "--hide-scrollbars",
            "--window-size=%d,%d" % tuple(viewport)]
    if not headed:
        args.append("--headless=new")
    if sys.platform.startswith("linux") and os.geteuid() == 0:
        args.append("--no-sandbox")
    proc = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while time.time() < deadline:
        if port_file.exists() and port_file.read_text().strip():
            port = int(port_file.read_text().split()[0])
            for _ in range(50):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=2) as r:
                        pages = [t for t in json.load(r) if t.get("type") == "page"]
                    if pages:
                        return proc, pages[0]["webSocketDebuggerUrl"]
                except OSError:
                    pass
                time.sleep(0.1)
        if proc.poll() is not None:
            raise Usage("Edge exited at start: is another `sidequest-data qa-shot` using %s?" % profile)
        time.sleep(0.1)
    proc.kill()
    raise Usage("Edge did not open its DevTools port within 20s")


HELPERS = r"""
const __q = (s) => { const e = document.querySelector(s); if (!e) throw new Error('no element ' + s); return e; };
const __set = (e, v) => {
  const proto = e.tagName === 'SELECT' ? HTMLSelectElement.prototype : e.tagName === 'TEXTAREA'
    ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, v);
  e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
};
"""


def poll(dev, expression, timeout, what):
    deadline = time.time() + timeout
    while True:
        try:
            if dev.js(expression):
                return
        except Fail:
            pass
        if time.time() > deadline:
            raise Fail("timed out after %ss waiting for %s" % (timeout, what))
        time.sleep(0.25)


def wait_loaded(dev, timeout=20):
    time.sleep(0.3)
    poll(dev, "document.readyState === 'complete' && location.href !== 'about:blank'", timeout, "the page to load")


def navigate(dev, url):
    r = dev.call("Page.navigate", url=url)
    if r.get("errorText"):
        raise Fail("could not open %s: %s (is the app running? `your project app command`)" % (url, r["errorText"]))
    wait_loaded(dev)


def sign_in_if_asked(dev, url, account, hosts=None):
    """Fill the sign-in form, but only on the local app (hosts=None) or the given review-app hosts."""
    if not dev.js("!!document.querySelector('input[type=password]')"):
        return False
    actual = dev.js("window.location.href")
    if not isinstance(actual, str):
        raise Fail("cannot verify the current login host")
    host = urllib.parse.urlparse(actual).hostname
    allowed = is_local(host) if hosts is None else host in hosts
    if not allowed:
        where = "the local app (localhost, *.localhost)" if hosts is None else ", ".join(sorted(hosts))
        raise Fail("sign-in page on %s: automatic sign-in only runs on %s" % (url, where))
    email, password = account
    if not email or not password:
        raise Fail("set SIDEQUEST_QA_EMAIL and SIDEQUEST_QA_PASSWORD for local sign-in")
    dev.js(HELPERS + """(() => {
      const pw = __q('input[type=password]');
      const form = pw.form || document;
      const user = form.querySelector('input[type=email], input[name*=email i], input[name*=login i], input[type=text]');
      if (!user) throw new Error('no email field');
      __set(user, %s); __set(pw, %s);
      const submit = form.querySelector('[type=submit]');
      if (submit) submit.click(); else if (pw.form) pw.form.requestSubmit();
    })()""" % (json.dumps(email), json.dumps(password)))
    try:
        poll(dev, "document.readyState === 'complete' && !document.querySelector('input[type=password]')", 15, "sign-in")
    except Fail:
        raise Fail("sign-in failed for %s: check the %s" % (
            email, "local test login (SIDEQUEST_QA_EMAIL / SIDEQUEST_QA_PASSWORD)" if hosts is None else "review-app QA login (environment variables)"))
    return True


def run_step(dev, step):
    timeout = float(step.get("timeout", 10))
    if "click" in step:
        dev.js(HELPERS + "(() => { const e = __q(%s); e.scrollIntoView({block: 'center'}); e.click(); })()" % json.dumps(step["click"]))
        time.sleep(0.3)
    elif "click_text" in step:
        text = json.dumps(step["click_text"])
        dev.js(HELPERS + """(() => {
          const want = %s.trim().toLowerCase();
          const all = [...document.querySelectorAll('a, button, [role=button], input[type=submit], input[type=button], summary, label')];
          const label = (e) => (e.innerText || e.value || '').trim().toLowerCase();
          const e = all.find((x) => label(x) === want) || all.find((x) => label(x).includes(want));
          if (!e) throw new Error('nothing clickable says ' + %s);
          e.scrollIntoView({block: 'center'}); e.click();
        })()""" % (text, text))
        time.sleep(0.3)
    elif "fill" in step or "select" in step:
        sel = step.get("fill") or step.get("select")
        dev.js(HELPERS + "__set(__q(%s), %s)" % (json.dumps(sel), json.dumps(str(step["value"]))))
    elif "wait_for" in step:
        sel = json.dumps(step["wait_for"])
        poll(dev, "(() => { const e = document.querySelector(%s); return !!e && !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); })()" % sel,
             timeout, step["wait_for"])
    elif "expect_text" in step:
        poll(dev, "document.body && document.body.innerText.includes(%s)" % json.dumps(step["expect_text"]),
             timeout, "the text %r" % step["expect_text"])
    elif "wait" in step:
        time.sleep(float(step["wait"]) / 1000)


def capture(dev, shot, out):
    params = {"format": "png"}
    if shot.get("selector"):
        rect = dev.js(HELPERS + """(() => { const e = __q(%s); e.scrollIntoView({block: 'start'});
          const r = e.getBoundingClientRect(); return [r.left + scrollX, r.top + scrollY, r.width, r.height]; })()"""
                      % json.dumps(shot["selector"]))
        x, y, w, h = rect
        pad = 8
        params.update(captureBeyondViewport=True, clip={"x": max(0, x - pad), "y": max(0, y - pad),
                                                         "width": w + 2 * pad, "height": min(h + 2 * pad, 8000), "scale": 1})
    elif shot.get("full_page"):
        w, h = dev.js("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]")
        params.update(captureBeyondViewport=True, clip={"x": 0, "y": 0, "width": w, "height": min(h, 8000), "scale": 1})
    data = base64.b64decode(dev.call("Page.captureScreenshot", **params)["data"])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(out)


# ---------------------------------------------------------------- git / manifest
def git(*args):
    return gitutil.git(*args, check=False).strip()


def oldest(commits):
    """The commit every other one descends from (so freshness checks cover every shot)."""
    pick = None
    for c in commits:
        if pick is None or subprocess.run(["git", "merge-base", "--is-ancestor", c, pick]).returncode == 0:
            pick = c
    return pick


def read_manifest(folder):
    try:
        data = json.loads((folder / "manifest.json").read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_manifest(folder, key, spec, results, previous, environment=None):
    by_name = {s["name"]: s for s in (previous or {}).get("shots", [])}
    by_name.update({r["name"]: r for r in results})
    order = [s["name"] for s in spec["shots"]]
    shots = [by_name[n] for n in order if n in by_name]
    ok_commits = [s["commit"] for s in shots if s.get("status") == "ok" and s.get("commit")]
    manifest = {"ticket": key, "commit": oldest(ok_commits) if ok_commits else git("rev-parse", "HEAD"),
                "dirty": any(s.get("dirty") for s in shots if s.get("status") == "ok"),
                "branch": git("branch", "--show-current"), "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "shots": shots}
    if environment:
        manifest.update(environment)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def pr_markdown(key, folder):
    manifest = read_manifest(folder)
    shots = [s for s in (manifest or {}).get("shots", []) if s.get("status") == "ok" and (folder / s["file"]).is_file()]
    if not shots:
        raise Usage("no passing screenshots in %s: run the QA first" % folder)
    lines = ["## Screenshots", ""]
    if manifest.get("review_app_url"):
        lines += ["Taken on the review app %s." % manifest["review_app_url"], ""]
    for s in shots:
        where = s.get("caption") or s["name"]
        lines.append("**%s**%s" % (where, (" (" + s["url_path"] + ")") if s.get("url_path") else ""))
        if s.get("criterion"):
            lines.append("_%s_" % s["criterion"])
        lines += ["", "![%s](%s)" % (where.replace("]", ")"), folder / s["file"]), ""]
    print("\n".join(lines).rstrip())
    print()
    print("ATTACH: " + " ".join("--attach %s" % json.dumps(str(folder / s["file"])) for s in shots))


def main():
    ap = argparse.ArgumentParser(prog="sidequest-data qa-shot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key", nargs="?")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--pr-markdown", action="store_true")
    ap.add_argument("--review-app", action="store_true", help="run on the PR's Heroku review app")
    ap.add_argument("--pr", type=int, help="PR number for --review-app (default: the ticket's open PR)")
    ap.add_argument("--browser", default=os.environ.get("SIDEQUEST_QA_BROWSER"))
    ap.add_argument("--profile", type=Path, default=Path.home() / ".cache/sidequest/qa-browser-profile")
    a = ap.parse_args()

    key = (a.key or "").upper()
    if not key:
        key = branch_ticket(git("branch", "--show-current"), config.get("jira", "projects", [])) or ""
        if not key:
            raise Usage("give the ticket key (sidequest-data qa-shot DEMO-###) or run inside its worktree")
    if not is_key(key):
        raise Usage("ticket key must look like APP-123")
    folder = qa_evidence.review_qa_dir(key) if a.review_app else qa_evidence.qa_dir(key)
    if a.pr_markdown:
        pr_markdown(key, folder)
        return 0

    environment, hosts = None, None
    if a.review_app:
        spec_file = folder / "shots.json"
        if not spec_file.is_file():
            spec_file = qa_evidence.qa_dir(key) / "shots.json"
        spec = load_spec(spec_file)
        try:
            pr = review_apps.find_pr(None if a.pr else key, a.pr)
            app = review_apps.review_app(pr["number"])
        except review_apps.ReviewAppError as exc:
            raise Usage(str(exc))
        if app.get("status") != "Web up":
            print("review app for PR #%d is %s%s: wait for it (sidequest-data review-app %s) and retry" % (
                pr["number"], app.get("status"), (" (" + app["warning"] + ")") if app.get("warning") else "", key))
            return 1
        host = review_apps.review_host(app.get("url"))
        if not host:
            raise Usage("Heroku gave no https *.herokuapp.com URL for PR #%d's review app (%r)" % (pr["number"], app.get("url")))
        for shot in spec["shots"]:
            if shot["path"].startswith("http") and urllib.parse.urlparse(shot["path"]).hostname != host:
                raise Usage("shot %s points at %s; --review-app shots must use paths like /orders" % (shot["name"], shot["path"]))
        try:
            account = review_apps.login()
        except review_apps.ReviewAppError as exc:
            raise Usage(str(exc))
        base, hosts = "https://" + host, {host}
        folder.mkdir(parents=True, exist_ok=True)
        head = git("rev-parse", "HEAD")
        remote = git("rev-parse", "--verify", "--quiet", "origin/" + pr["head"]) if pr.get("head") else ""
        environment = {"environment": "review-app", "pr": pr["number"], "review_app": app.get("app", ""),
                       "review_app_url": base, "pushed": bool(remote) and remote == head}
        if not environment["pushed"]:
            print("note: local HEAD %s is not origin/%s; the review app runs what was pushed" % (head[:9], pr.get("head")))
        print("review app %s (PR #%d)" % (base, pr["number"]))
    else:
        spec = load_spec(folder / "shots.json")
    shots = [s for s in spec["shots"] if not a.only or s["name"] in a.only]
    unknown = set(a.only) - {s["name"] for s in spec["shots"]}
    if unknown:
        raise Usage("no shot named " + ", ".join(sorted(unknown)))
    viewport = spec.get("viewport") or [1440, 900]
    if not a.review_app:
        base = spec.get("base_url", "http://localhost:3010").rstrip("/")
        account = (os.environ.get("SIDEQUEST_QA_EMAIL") or DEFAULT_ACCOUNT[0], os.environ.get("SIDEQUEST_QA_PASSWORD") or DEFAULT_ACCOUNT[1])
    commit, dirty = git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))

    proc, ws = launch(find_browser(a.browser), a.profile.expanduser(), viewport, a.headed)
    results = []
    try:
        dev = DevTools(ws)
        dev.call("Page.enable")
        dev.call("Emulation.setDeviceMetricsOverride", width=viewport[0], height=viewport[1],
                 deviceScaleFactor=float(spec.get("scale", 1)), mobile=False)
        for shot in shots:
            url = shot["path"] if shot["path"].startswith("http") else base + shot["path"]
            out = folder / (shot["name"] + ".png")
            entry = {"name": shot["name"], "file": out.name, "caption": shot.get("caption", ""),
                     "criterion": shot.get("criterion", ""), "url_path": urllib.parse.urlparse(url).path,
                     "commit": commit, "dirty": dirty}
            try:
                navigate(dev, url)
                if sign_in_if_asked(dev, url, account, hosts):
                    navigate(dev, url)
                    if dev.js("!!document.querySelector('input[type=password]')"):
                        raise Fail("still on a sign-in page after signing in")
                for step in shot.get("steps") or []:
                    run_step(dev, step)
                time.sleep(float(spec.get("settle_ms", 400)) / 1000)
                capture(dev, shot, out)
                entry["status"] = "ok"
                print("ok      %-28s %s" % (out.name, entry["caption"]))
            except Fail as exc:
                out.unlink(missing_ok=True)
                entry.update(status="failed", error=str(exc), file="failures/" + out.name)
                try:
                    capture(dev, {}, folder / "failures" / out.name)
                except (Fail, Usage, OSError):
                    pass
                print("FAILED  %-28s %s" % (out.name, exc))
            results.append(entry)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    manifest = write_manifest(folder, key, spec, results, read_manifest(folder), environment)
    failed = [r for r in results if r["status"] != "ok"]
    print("%d ok, %d failed; manifest: %s (commit %s%s)" % (len(results) - len(failed), len(failed),
          folder / "manifest.json", manifest["commit"][:9], ", uncommitted changes" if manifest["dirty"] else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Usage as exc:
        print("qa-shot: " + str(exc), file=sys.stderr)
        sys.exit(2)
