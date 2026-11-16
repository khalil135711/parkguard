import os, time
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

def _fmt(ts): return time.strftime("%d.%m.%Y %H:%M", time.localtime(ts))

def make_fine_pdf(path, fine, sess, s, base_url, free_minutes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    y = h - 60
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, "Zahlungsaufforderung / Parkverstoss"); y -= 25
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"{s['operator_name']} - {s['operator_address']}"); y -= 35

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, f"Vorgangsnummer: PG-{fine['id']:06d}"); y -= 20
    c.setFont("Helvetica", 11)
    now = int(time.time())
    parked_min = ((sess["exit_ts"] or now) - sess["entry_ts"]) // 60
    lines = [
        f"Kennzeichen: {fine['plate']}",
        f"Einfahrt: {_fmt(sess['entry_ts'])}",
        f"Ausgestellt: {_fmt(fine['created_ts'])}",
        f"Parkdauer bisher: {parked_min} Minuten (erlaubt: {free_minutes} Minuten)",
        f"Betrag: {fine['amount_cents']/100:.2f} {s['currency']}",
    ]
    for l in lines:
        c.drawString(50, y, l); y -= 16
    y -= 10
    c.drawString(50, y, "Bezahlung am Automaten (Kennzeichen eingeben, Karte oder PayPal)"); y -= 16
    c.drawString(50, y, f"oder online: {base_url}/kiosk?plate={fine['plate']}"); y -= 30

    if sess["entry_image"] and os.path.exists(sess["entry_image"]):
        try:
            c.drawString(50, y, "Beweisfoto (Einfahrt):"); y -= 5
            c.drawImage(ImageReader(sess["entry_image"]), 50, y - 240, width=320, height=240,
                        preserveAspectRatio=True)
        except Exception:
            pass
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(50, 40, "Automatisch erstellt. Rechtsgrundlage und Betragshoehe vor Einsatz rechtlich pruefen.")
    c.save()
    return path
