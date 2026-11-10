"""Print a local HTML file to PDF with headless Chrome — the delivery piece for client documents.

Ported unchanged from Compass (~/.openclaw/workspace/compass/pdf.py, commit 506671a), except the
Chrome override variable: INVOICING_CHROME (COMPASS_CHROME still honoured).

Generic on purpose: it knows nothing about hours, Odoo or the charter. The render module builds
a self-contained HTML (data-URI images, inline CSS, offline CSP); this module only prints it.

Why Chrome: it is already on the PM's machine, so the Camptocamp charter costs zero installs
(typst and python-docx are absent), and it implements CSS @page margin boxes — running header,
footer and `page / pages` counters — which is what a client document needs. Proven before the
first line of this file by `verify/chrome_print_probe.py` (A4, counters, Messina Sans embedded,
icon on every page, Creator ≠ HeadlessChrome).

Three things this module refuses to get wrong:
  * a THROWAWAY profile (`--user-data-dir`): without it `google-chrome` hands the job to the
    PM's running browser and exits 0 having written nothing;
  * no half-written file: Chrome prints to a temp name, the result must look like a PDF, and
    only then is it moved into place — the agent attaches whatever sits at the final path;
  * no orphan: Chrome runs in its own process group, killed whole on timeout.
"""
import os
import re
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

CHROMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
TIMEOUT_S = 90


class PdfError(RuntimeError):
    pass


def find_chrome():
    """`INVOICING_CHROME` / `COMPASS_CHROME` (a path or a command name), else the first Chrome/Chromium on PATH."""
    env = (os.environ.get("INVOICING_CHROME") or os.environ.get("COMPASS_CHROME") or "").strip()
    for name in ((env,) if env else CHROMES):
        hit = shutil.which(name)
        if hit:
            return hit
    raise PdfError(f"no Chrome/Chromium found ({env or ', '.join(CHROMES)}) — set INVOICING_CHROME")


def html_to_pdf(html_path, pdf_path, timeout=TIMEOUT_S):
    """Print `html_path` to `pdf_path`. Returns {"path", "bytes", "pages"}; raises PdfError and
    leaves no file at `pdf_path` on any failure (the HTML is always kept)."""
    html_path, pdf_path = Path(html_path).resolve(), Path(pdf_path).resolve()
    tmp_pdf = pdf_path.with_name(pdf_path.name + ".part")
    tmp_pdf.unlink(missing_ok=True)
    chrome = find_chrome()
    with tempfile.TemporaryDirectory(prefix="invoicing-chrome-", ignore_cleanup_errors=True) as prof:
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-first-run",
               "--no-default-browser-check", "--disable-extensions",
               "--disable-background-networking", "--disable-component-update", "--disable-sync",
               "--user-agent=Camptocamp",              # PDF Creator field; never "HeadlessChrome"
               f"--user-data-dir={prof}", "--no-pdf-header-footer",
               f"--print-to-pdf={tmp_pdf}", html_path.as_uri()]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
        except OSError as e:
            raise PdfError(f"cannot start {chrome}: {e} — HTML kept at {html_path}") from e
        try:
            _, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            tmp_pdf.unlink(missing_ok=True)
            raise PdfError(f"Chrome timed out after {timeout} s — HTML kept at {html_path}")
    data = tmp_pdf.read_bytes() if tmp_pdf.exists() else b""
    if len(data) <= 1024 or not data.startswith(b"%PDF-"):
        tmp_pdf.unlink(missing_ok=True)
        tail = (err or b"").decode(errors="replace").strip()[-600:]
        raise PdfError(f"Chrome exited {p.returncode} without a usable PDF — HTML kept at "
                       f"{html_path}" + (f"\n{tail}" if tail else ""))
    os.replace(tmp_pdf, pdf_path)
    return {"path": str(pdf_path), "bytes": len(data),
            "pages": len(re.findall(rb"/Type\s*/Page[^s]", data))}


def brand_font_ok(family="Messina Sans"):
    """True when fontconfig resolves the charter font, False when it falls back, None when
    fontconfig cannot be asked. Messina Sans is a commercial font installed on c2c machines and
    deliberately not shipped in the workspace — on any other machine the PDF silently uses the
    CSS fallback, so the caller warns."""
    if not shutil.which("fc-match"):
        return None
    try:
        out = subprocess.run(["fc-match", "-f", "%{family}", family], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return family.lower() in out.lower()
