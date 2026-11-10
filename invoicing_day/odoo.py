"""Read-only Odoo client (XML-RPC), shared by every command of invoicing_day.

Origin: `load_config`, the `Odoo` class and its exit codes come from
~/.claude/skills/checkup-projets/scripts/profitability.py. The `search_read` / `read_group` /
`fields_get` calls are the interface of Compass's `OdooROClient`, which the ported hours fetcher
(invoicing_day/hours/fetch.py) expects.

Structural read-only guard: any method outside READ_ONLY is refused BEFORE the network call.
Do not widen READ_ONLY without an explicit request from Didier.

Configuration: ~/.config/timesheetMagician/odoo.env (KEY=VALUE, chmod 600, outside the repo),
or the file named by INVOICING_ODOO_CONFIG; environment variables win.
  ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_API_KEY
The API key bypasses 2FA and is a full access under Didier's identity: it never goes into the
repo, a report, a page or a conversation.
"""
import os
import time
import xmlrpc.client
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("INVOICING_ODOO_CONFIG",
                                  "~/.config/timesheetMagician/odoo.env")).expanduser()
KEYS = ("ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY")
READ_ONLY = frozenset({"search_read", "read", "read_group", "search", "search_count",
                       "fields_get", "name_search"})
TIMEOUT_S = 90
RETRY_DELAYS = (2, 5, 10, 20, 40)        # seconds, on HTTP 429/502/503/504


class OdooError(RuntimeError):
    """Odoo answered with a fault (bad field, access right…). CLI exit code 4."""
    exit_code = 4


class OdooUnreachable(OdooError):
    """Network / VPN problem, or authentication refused. CLI exit code 3."""
    exit_code = 3


class ConfigError(OdooError):
    """Missing configuration. CLI exit code 5."""
    exit_code = 5


def load_env_file(path):
    cfg = {}
    p = Path(path).expanduser()
    if p.exists():
        for raw in p.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def load_config(path=None):
    cfg = load_env_file(path or CONFIG_PATH)
    for k in KEYS:
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    missing = [k for k in KEYS if not cfg.get(k)]
    if missing:
        raise ConfigError(f"Odoo configuration incomplete ({', '.join(missing)}) — see {path or CONFIG_PATH}")
    return cfg


class _Transport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout, **kw):
        super().__init__(**kw)
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _PlainTransport(xmlrpc.client.Transport):
    def __init__(self, timeout, **kw):
        super().__init__(**kw)
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class Odoo:
    """Read-only XML-RPC client. `Odoo()` reads the config and authenticates immediately."""

    def __init__(self, cfg=None, timeout=TIMEOUT_S):
        cfg = cfg or load_config()
        self.url = cfg["ODOO_URL"].rstrip("/")
        self.db, self._key = cfg["ODOO_DB"], cfg["ODOO_API_KEY"]
        tr = (_Transport if self.url.startswith("https") else _PlainTransport)(timeout)
        try:
            common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True, transport=tr)
            self.uid = common.authenticate(self.db, cfg["ODOO_LOGIN"], self._key, {})
        except (OSError, xmlrpc.client.Error) as e:
            raise OdooUnreachable(f"Odoo unreachable ({self.url}) — VPN down? {e}") from e
        if not self.uid:
            raise OdooUnreachable("Odoo authentication refused (login / API key)")
        tr = (_Transport if self.url.startswith("https") else _PlainTransport)(timeout)
        self._obj = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True, transport=tr)

    # -- the single door to Odoo
    def execute_kw(self, model, method, args, kwargs=None):
        if method not in READ_ONLY:
            raise OdooError(f"method {method} refused: invoicing_day is read-only on Odoo")
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return self._obj.execute_kw(self.db, self.uid, self._key, model, method, args, kwargs or {})
            except xmlrpc.client.Fault as e:
                raise OdooError(f"{model}.{method} refused by Odoo: {e.faultString.strip().splitlines()[-1][:300]}") from e
            except xmlrpc.client.ProtocolError as e:
                # c2c's Odoo rate-limits XML-RPC (429 seen on 2026-11-10): wait and retry.
                if e.errcode in (429, 502, 503, 504) and attempt < len(RETRY_DELAYS):
                    retry_after = (e.headers or {}).get("Retry-After") if hasattr(e, "headers") else None
                    time.sleep(float(retry_after) if retry_after and str(retry_after).isdigit()
                               else RETRY_DELAYS[attempt])
                    continue
                raise OdooUnreachable(f"Odoo unreachable during {model}.{method} — VPN down? {e}") from e
            except OSError as e:
                raise OdooUnreachable(f"Odoo unreachable during {model}.{method} — VPN down? {e}") from e

    # -- Compass OdooROClient interface
    def search_read(self, model, domain, fields=None, **kw):
        return self.execute_kw(model, "search_read", [domain], {"fields": fields or [], **kw})

    def read_group(self, model, domain, fields, groupby, **kw):
        return self.execute_kw(model, "read_group", [domain, fields, groupby], {"lazy": False, **kw})

    def fields_get(self, model, attributes=("type",)):
        return self.execute_kw(model, "fields_get", [], {"attributes": list(attributes)})

    def search_count(self, model, domain, **kw):
        return self.execute_kw(model, "search_count", [domain], kw)

    def read(self, model, ids, fields=None, **kw):
        return self.execute_kw(model, "read", [list(ids)], {"fields": fields or [], **kw})

    # -- links for reports and pages
    def link(self, model, rec_id):
        return f"{self.url}/web#id={rec_id}&model={model}&view_type=form"
