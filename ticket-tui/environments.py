"""Read-only Heroku review-app metadata. Tokens stay in memory."""

import json
import os
import re
import urllib.error
import urllib.request

from core import now


def review_status(review, app=None, dynos=None):
    phase = review.get("status") or "unknown"
    if phase != "created":
        return {"pending": "Pending", "creating": "Creating", "building": "Building",
                "errored": "Failed", "error": "Failed", "deleting": "Deleting"}.get(phase, phase.capitalize())
    if app and app.get("maintenance"):
        return "Maintenance"
    if dynos is None:
        return "Provisioned"
    web = [d.get("state") for d in dynos if d.get("type") == "web"]
    if "crashed" in web:
        return "Web crashed"
    if "up" in web:
        return "Web up"
    if web:
        return "Web " + ", ".join(sorted(set(s or "unknown" for s in web)))
    return "No web dyno"


def fetch_environments(numbers, run, pipeline=None):
    """Use the CLI login to read the pipeline and review apps; never write APIs."""
    if not pipeline:
        raise RuntimeError("Heroku is disabled; configure heroku.pipeline before requesting credentials")
    token = os.environ.get("SIDEQUEST_HEROKU_TOKEN") or run(["heroku", "auth:token"], timeout=15).strip()
    if not token:
        raise RuntimeError("Heroku login unavailable; run heroku auth:whoami in your terminal")

    def get(path):
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.heroku+json; version=3",
        }
        result, seen = None, set()
        try:
            while True:
                request = urllib.request.Request("https://api.heroku.com" + path, headers=headers)
                with urllib.request.urlopen(request, timeout=12) as response:
                    data = json.load(response)
                    next_range = response.headers.get("Next-Range") if getattr(response, "status", 200) == 206 else None
                if result is None:
                    result = data
                elif isinstance(result, list) and isinstance(data, list):
                    result.extend(data)
                else:
                    raise ValueError("Invalid Heroku pagination")
                if not next_range:
                    return result
                if next_range in seen:
                    raise ValueError("Repeated Heroku page")
                seen.add(next_range)
                headers["Range"] = next_range
        except urllib.error.HTTPError as exc:
            reason = {401: "login expired or invalid", 403: "account lacks permission", 404: "pipeline or app not found",
                      429: "rate limited"}.get(exc.code, "service request failed")
            raise RuntimeError(f"Heroku: {reason} (HTTP {exc.code}); keeping cached status") from None
        except (urllib.error.URLError, OSError) as exc:
            detail = str(exc).lower()
            reason = ("TLS certificate verification failed" if "certificate" in detail or "ssl" in detail else
                      "DNS lookup failed for api.heroku.com" if any(s in detail for s in ("enotfound", "getaddrinfo", "nodename", "name or service")) else
                      "network request failed")
            raise RuntimeError(f"Heroku: {reason}; keeping cached status") from None
        except ValueError:
            raise RuntimeError("Heroku: invalid API response; keeping cached status") from None

    reviews = get(f"/pipelines/{pipeline}/review-apps")
    if not isinstance(reviews, list):
        raise RuntimeError("Invalid Heroku response; keeping cached status")
    entries = {}
    for number in numbers:
        review = next((r for r in reviews if str(r.get("pr_number")) == str(number)), None)
        if not review:
            entries[str(number)] = {"status": "Not provisioned", "checked_at": now().isoformat()}
            continue
        app_id = (review.get("app") or {}).get("id")
        app, dynos, warning = {}, None, ""
        if app_id:
            try:
                app = get(f"/apps/{app_id}")
                dynos = get(f"/apps/{app_id}/dynos")
                if not isinstance(app, dict) or not isinstance(dynos, list):
                    raise RuntimeError("Invalid Heroku runtime response")
            except RuntimeError:
                warning = "Runtime status unavailable; provisioning status only"
                app, dynos = {}, None
        entries[str(number)] = {"status": review_status(review, app, dynos),
                                "phase": review.get("status", "unknown"),
                                "app": app.get("name", ""), "url": app.get("web_url", ""),
                                "checked_at": now().isoformat(), "warning": warning}
    return {"generated_at": now().isoformat(), "entries": entries}
