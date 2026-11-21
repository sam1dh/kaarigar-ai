"""Make a printable A4 sheet of machine QR stickers straight from the database (no web screen needed).

Same stickers as W7 Machines → Print stickers: 90 x 64 mm, 8 per A4 page, QR = PUBLIC_APP_URL/m/<qr_token>.
Use it before Phase 4's W7 is connected, or to reprint all stickers for the demo in one go.

    cd backend
    python scripts/print_stickers.py --plant shree                       # every active machine
    python scripts/print_stickers.py --plant shree --codes HP-07,CNC-03  # some machines
    python scripts/print_stickers.py --plant shree --url https://dev.kaarigar-ai.online   # stickers for the dev tunnel

Writes stickers.html. Open it in Chrome → Print → A4, scale 100%, margins none. Read-only: changes nothing.
"""
from __future__ import annotations

import argparse
import html
import os
import sys
from pathlib import Path


def load_dotenv() -> None:
    for p in (Path(".env"), Path("../.env")):
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))
            return


CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "IBM Plex Sans", Arial, sans-serif; color: #1C2626; background: #E9EDE8; }
.sheet { width: 210mm; min-height: 297mm; margin: 8mm auto; padding: 10mm; background: #fff;
         display: grid; grid-template-columns: 90mm 90mm; grid-auto-rows: 64mm; gap: 6mm; justify-content: center; align-content: start; }
.sticker { border: 0.4mm solid #1C2626; border-radius: 3mm; display: flex; overflow: hidden; background: #fff; }
.qr-panel { width: 48mm; padding: 3mm; display: flex; align-items: center; justify-content: center; flex: none; }
.qr { width: 42mm; height: 42mm; }
.qr svg { width: 100%; height: 100%; display: block; shape-rendering: crispEdges; }
.divider { width: 0.3mm; background: #D3D9D3; margin: 3mm 0; flex: none; }
.info { flex: 1; min-width: 0; display: flex; flex-direction: column; padding: 3.5mm; }
.brand-row { display: flex; align-items: center; gap: 1.2mm; }
.brand-dot { width: 1.6mm; height: 1.6mm; border-radius: 9999px; background: #1F4239; flex: none; }
.brand { font-size: 5.5pt; letter-spacing: .16em; text-transform: uppercase; font-weight: 600; color: #1F4239; line-height: 1; }
.code { font-family: "Anek Latin", Arial, sans-serif; font-weight: 700; line-height: 1; letter-spacing: -.01em; margin-top: 2mm; }
.name { font-size: 8.5pt; font-weight: 600; line-height: 1.2; margin-top: 1.5mm; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.meta { font-size: 7pt; margin-top: 1mm; color: #5B6863; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.footer { margin-top: auto; padding-top: 2mm; border-top: 0.3mm solid #D3D9D3; display: flex; align-items: center; gap: 1.2mm; }
.scan { font-size: 7.5pt; font-weight: 600; color: #1F4239; }
.tip { width: 210mm; margin: 8mm auto 0; font-size: 11pt; }
@media print { body { background: #fff; } .sheet { margin: 0; } .sheet:not(:last-child) { break-after: page; } .tip { display: none; } }
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plant", required=True, help="plant slug, e.g. shree")
    ap.add_argument("--codes", help="comma-separated machine codes; default: every active machine")
    ap.add_argument("--url", help="app address printed in the QR; default PUBLIC_APP_URL")
    ap.add_argument("--out", default="stickers.html")
    a = ap.parse_args()
    load_dotenv()
    base = (a.url or os.environ.get("PUBLIC_APP_URL") or "").rstrip("/")
    if not base.startswith("https://"):
        print("Set PUBLIC_APP_URL (or --url) to the https address the phones will open, e.g. https://dev.kaarigar-ai.online")
        return 2

    import psycopg
    import segno

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        t = conn.execute("select id from tenants where slug = %s", (a.plant,)).fetchone()
        if not t:
            print(f"No plant with slug '{a.plant}'.")
            return 2
        has_archive = conn.execute("""select 1 from information_schema.columns
                                      where table_name = 'machines' and column_name = 'archived_at'""").fetchone()
        sql = """select m.code, m.name, m.line, m.qr_token, mm.model from machines m
                 left join machine_models mm on mm.id = m.model_id where m.tenant_id = %s"""
        params: list = [t[0]]
        if has_archive:
            sql += " and m.archived_at is null"
        if a.codes:
            codes = [c.strip().upper() for c in a.codes.split(",") if c.strip()]
            sql += " and upper(m.code) = any(%s)"
            params.append(codes)
        rows = conn.execute(sql + " order by m.code", params).fetchall()
    if not rows:
        print("No machines found.")
        return 2

    cards = []
    for code, name, line, token, model in rows:
        svg = segno.make(f"{base}/m/{token}", error="m").svg_inline(scale=4, border=0, dark="#1C2626", omitsize=True,
                                                                   title=f"QR code for {code}")
        meta = " · ".join(html.escape(x) for x in (line, model) if x)
        code_size = "17pt" if len(code) > 7 else "20pt" if len(code) > 5 else "23pt"
        scan_icon = ('<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#1F4239" '
                     'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
                     '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/>'
                     '<path d="M8 12h8"/></svg>')
        cards.append(f"""<div class="sticker">
<div class="qr-panel"><div class="qr">{svg}</div></div><div class="divider"></div>
<div class="info">
  <div class="brand-row"><span class="brand-dot"></span><span class="brand">Kaarigar AI</span></div>
  <div class="code" style="font-size:{code_size}">{html.escape(code)}</div>
  <div class="name">{html.escape(name or '')}</div>
  <div class="meta">{meta}</div>
  <div class="footer">{scan_icon}<span class="scan">Scan to ask Kaarigar</span></div>
</div></div>""")
    pages = ["".join(cards[i:i + 8]) for i in range(0, len(cards), 8)]
    doc = (f"<!doctype html><html><head><meta charset='utf-8'><title>Kaarigar stickers</title><style>{CSS}</style></head><body>"
           f"<p class='tip'>Print: A4, scale 100% (not \"fit to page\"), margins none. QR codes open {html.escape(base)}/m/…</p>"
           + "".join(f"<div class='sheet'>{p}</div>" for p in pages) + "</body></html>")
    Path(a.out).write_text(doc, encoding="utf-8")
    print(f"{len(rows)} stickers on {len(pages)} page(s) → {a.out}  (QR address: {base}/m/<token>)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
