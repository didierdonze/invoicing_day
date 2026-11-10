"""Read-only Jira Cloud REST client (GET only).

Configuration: ~/.config/invoicing_day/jira.env (KEY=VALUE, chmod 600, outside the repo), or the
file named by INVOICING_JIRA_CONFIG; environment variables win.
  JIRA_URL=https://camptocamp.atlassian.net
  JIRA_EMAIL=<your Atlassian login>
  JIRA_API_TOKEN=<token from id.atlassian.com › Security › API tokens>
Without a configuration, `load()` returns None and the Jira controls are reported as skipped.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .odoo import load_env_file

CONFIG_PATH = Path(os.environ.get("INVOICING_JIRA_CONFIG", "~/.config/invoicing_day/jira.env")).expanduser()
KEYS = ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")
RETRY_DELAYS = (2, 5, 10, 20)


class JiraError(RuntimeError):
    pass


def load(path=None):
    cfg = load_env_file(path or CONFIG_PATH)
    for k in KEYS:
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    if any(not cfg.get(k) for k in KEYS):
        return None
    return Jira(cfg)


class Jira:
    def __init__(self, cfg, timeout=60):
        self.url = cfg["JIRA_URL"].rstrip("/")
        tok = base64.b64encode(f"{cfg['JIRA_EMAIL']}:{cfg['JIRA_API_TOKEN']}".encode()).decode()
        self._headers = {"Authorization": f"Basic {tok}", "Accept": "application/json"}
        self.timeout = timeout

    def get(self, path, params=None):
        q = ("?" + urllib.parse.urlencode(params, doseq=True)) if params else ""
        req = urllib.request.Request(f"{self.url}{path}{q}", headers=self._headers, method="GET")
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code in (429, 502, 503, 504) and attempt < len(RETRY_DELAYS):
                    ra = e.headers.get("Retry-After")
                    time.sleep(float(ra) if ra and ra.isdigit() else RETRY_DELAYS[attempt])
                    continue
                body = e.read().decode(errors="replace")[:300]
                raise JiraError(f"Jira GET {path} → HTTP {e.code}: {body}") from e
            except (OSError, urllib.error.URLError) as e:
                raise JiraError(f"Jira unreachable ({self.url}): {e}") from e

    def search(self, jql, fields=("summary",), limit=2000):
        """Issues matching `jql` (enhanced search endpoint, token pagination)."""
        out, token = [], None
        while len(out) < limit:
            params = {"jql": jql, "fields": ",".join(fields), "maxResults": 100}
            if token:
                params["nextPageToken"] = token
            data = self.get("/rest/api/3/search/jql", params)
            out += data.get("issues") or []
            token = data.get("nextPageToken")
            if not token or data.get("isLast"):
                break
        return out[:limit]

    def worklog_seconds(self, key, started_after_ms, started_before_ms):
        """Σ timeSpentSeconds of the issue's worklogs started in [after, before)."""
        total, start = 0, 0
        while True:
            data = self.get(f"/rest/api/3/issue/{urllib.parse.quote(key)}/worklog",
                            {"startedAfter": started_after_ms, "startedBefore": started_before_ms,
                             "startAt": start, "maxResults": 1000})
            wls = data.get("worklogs") or []
            total += sum(w.get("timeSpentSeconds") or 0 for w in wls)
            start += len(wls)
            if not wls or start >= (data.get("total") or 0):
                return total

    def browse(self, key):
        return f"{self.url}/browse/{key}"
