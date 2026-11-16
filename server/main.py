import os, re, json, math, time, uuid, asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, PlainTextResponse
from pydantic import BaseModel
import db, anpr, pdfgen, payments

DEVICE_KEY = os.getenv("DEVICE_KEY", "change-me")      # für ESP32-Kameras
ADMIN_KEY = os.getenv("ADMIN_KEY", "change-me-too")    # für Admin-API
DATA = os.getenv("DATA_DIR", "data")
os.makedirs(f"{DATA}/evidence", exist_ok=True)
os.makedirs(f"{DATA}/fines", exist_ok=True)

def norm(p): return re.sub(r"[^A-Z0-9]", "", (p or "").upper())
def admin(key):
    if key != ADMIN_KEY: raise HTTPException(401, "bad admin key")

# ---------- Kernlogik ----------
def deadline(sess, s):
    base = sess["entry_ts"] + int(s["free_minutes"]) * 60
    return base + sess["paid_hours"] * 3600

def issue_fine(c, sess, s):
    if s["fine_mode"] == "off" or sess["fine_waived"]: return
    if c.execute("SELECT 1 FROM whitelist WHERE plate=?", (sess["plate"],)).fetchone(): return
    if c.execute("SELECT 1 FROM fines WHERE session_id=? AND voided=0", (sess["id"],)).fetchone(): return
    now = int(time.time())
    cur = c.execute("INSERT INTO fines(session_id,plate,amount_cents,created_ts) VALUES(?,?,?,?)",
                    (sess["id"], sess["plate"], int(s["fine_cents"]), now))
    fid = cur.lastrowid
    fine = c.execute("SELECT * FROM fines WHERE id=?", (fid,)).fetchone()
    path = pdfgen.make_fine_pdf(f"{DATA}/fines/fine_{fid}.pdf", fine, sess, s,
                                payments.BASE_URL, int(s["free_minutes"]))
    c.execute("UPDATE fines SET pdf_path=? WHERE id=?", (path, fid))
    print(f"[FINE] {sess['plate']} -> {path}")

def check_overstays():
    s = db.settings()
    if s["fine_mode"] != "on_overstay": return
    now = int(time.time())
    with db.conn() as c:
        for sess in c.execute("SELECT * FROM sessions WHERE status='open'").fetchall():
            if now > deadline(sess, s):
                issue_fine(c, sess, s)

async def loop():
    while True:
        try: check_overstays()
        except Exception as e: print("overstay check:", e)
        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app):
    db.init()
    t = asyncio.create_task(loop())
    yield
    t.cancel()

app = FastAPI(title="ParkGuard", lifespan=lifespan)

# ---------- Kamera ----------
@app.post("/api/camera/{direction}")
async def camera(direction: str, image: UploadFile = File(...),
                 x_device_key: str = Header(""), x_plate: str = Header("")):
    if x_device_key != DEVICE_KEY: raise HTTPException(401)
    if direction not in ("entry", "exit"): raise HTTPException(404)
    data = await image.read()
    now = int(time.time())
    img = f"{DATA}/evidence/{direction}_{now}.jpg"
    open(img, "wb").write(data)
    plate = norm(x_plate) or anpr.read_plate(data)   # X-Plate nur zum Testen
    if not plate: return {"ok": False, "reason": "no plate"}
    s = db.settings()
    with db.conn() as c:
        sess = c.execute("SELECT * FROM sessions WHERE plate=? AND status='open'", (plate,)).fetchone()
        if direction == "entry":
            if sess: return {"ok": True, "plate": plate, "note": "already open"}
            c.execute("INSERT INTO sessions(plate,entry_ts,entry_image) VALUES(?,?,?)", (plate, now, img))
            return {"ok": True, "plate": plate, "event": "entry"}
        if not sess: return {"ok": True, "plate": plate, "note": "no open session"}
        c.execute("UPDATE sessions SET exit_ts=?, status='closed' WHERE id=?", (now, sess["id"]))
        sess = c.execute("SELECT * FROM sessions WHERE id=?", (sess["id"],)).fetchone()
        if s["fine_mode"] in ("on_overstay", "on_exit") and now > deadline(sess, s):
            issue_fine(c, sess, s)
        return {"ok": True, "plate": plate, "event": "exit"}

# ---------- Automat / Kiosk ----------
def compute_due(c, plate, s):
    sess = c.execute("SELECT * FROM sessions WHERE plate=? ORDER BY id DESC LIMIT 1", (plate,)).fetchone()
    fines = c.execute("""SELECT f.* FROM fines f WHERE f.plate=? AND f.paid_ts IS NULL AND f.voided=0""",
                      (plate,)).fetchall()
    fee_hours, fee_cents = 0, 0
    if sess:
        elapsed = (sess["exit_ts"] or int(time.time())) - sess["entry_ts"]
        over = max(0, elapsed - int(s["free_minutes"]) * 60)
        fee_hours = max(0, math.ceil(over / 3600) - sess["paid_hours"])
        fee_cents = fee_hours * int(s["rate_cents_per_hour"])
    fine_cents = sum(f["amount_cents"] for f in fines)
    return sess, fines, fee_hours, fee_cents, fine_cents

@app.get("/api/kiosk/lookup")
def lookup(plate: str):
    plate = norm(plate); s = db.settings()
    with db.conn() as c:
        sess, fines, hours, fee, fine = compute_due(c, plate, s)
    if not sess: raise HTTPException(404, "Kennzeichen nicht gefunden")
    return {"plate": plate, "entry_ts": sess["entry_ts"], "exit_ts": sess["exit_ts"],
            "fee_cents": fee, "fine_cents": fine, "total_cents": fee + fine, "currency": s["currency"]}

class PayReq(BaseModel):
    plate: str
    method: str   # card | paypal

@app.post("/api/kiosk/pay")
def pay(req: PayReq):
    plate = norm(req.plate); s = db.settings()
    if req.method not in ("card", "paypal"): raise HTTPException(400, "method")
    with db.conn() as c:
        sess, fines, hours, fee, fine = compute_due(c, plate, s)
        total = fee + fine
        if not sess or total <= 0: raise HTTPException(400, "Nichts zu bezahlen")
        ref = uuid.uuid4().hex
        p = payments.create(req.method, ref, total, plate, s["currency"])
        c.execute("INSERT INTO payments(ref,plate,session_id,hours,fine_ids,amount_cents,method,provider_id) VALUES(?,?,?,?,?,?,?,?)",
                  (ref, plate, sess["id"], hours, json.dumps([f["id"] for f in fines]), total, req.method, p["provider_id"]))
    return {"ref": ref, "url": p["url"], "amount_cents": total}

@app.get("/api/kiosk/status/{ref}")
def status(ref: str):
    with db.conn() as c:
        r = c.execute("SELECT status FROM payments WHERE ref=?", (ref,)).fetchone()
    if not r: raise HTTPException(404)
    return {"status": r["status"]}

def mark_paid(ref):
    with db.conn() as c:
        p = c.execute("SELECT * FROM payments WHERE ref=?", (ref,)).fetchone()
        if not p or p["status"] == "paid": return
        c.execute("UPDATE payments SET status='paid' WHERE ref=?", (ref,))
        c.execute("UPDATE sessions SET paid_hours=paid_hours+? WHERE id=?", (p["hours"], p["session_id"]))
        for fid in json.loads(p["fine_ids"]):
            c.execute("UPDATE fines SET paid_ts=? WHERE id=?", (int(time.time()), fid))

@app.get("/mock/pay/{ref}")
def mock_pay(ref: str):
    if not payments.MOCK: raise HTTPException(404)
    mark_paid(ref)
    return RedirectResponse(f"/kiosk?paid={ref}")

@app.get("/paypal/return")
def paypal_return(ref: str, token: str):
    if payments.paypal_capture(token): mark_paid(ref)
    return RedirectResponse(f"/kiosk?paid={ref}")

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    import stripe
    ev = stripe.Webhook.construct_event(await request.body(), request.headers.get("stripe-signature", ""),
                                        os.environ["STRIPE_WEBHOOK_SECRET"])
    if ev["type"] == "checkout.session.completed":
        mark_paid(ev["data"]["object"]["metadata"]["ref"])
    return {"ok": True}

@app.get("/kiosk")
def kiosk(): return FileResponse("static/kiosk.html")

# ---------- Admin ----------
@app.get("/api/admin/settings")
def get_settings(x_admin_key: str = Header("")):
    admin(x_admin_key); return db.settings()

@app.put("/api/admin/settings")
def put_settings(body: dict, x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c:
        for k, v in body.items():
            if k in db.DEFAULTS: c.execute("REPLACE INTO settings VALUES(?,?)", (k, str(v)))
    return db.settings()

@app.get("/api/admin/sessions")
def sessions(x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 200")]

@app.get("/api/admin/fines")
def fines(x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM fines ORDER BY id DESC LIMIT 200")]

@app.get("/api/admin/fines/{fid}/pdf")
def fine_pdf(fid: int, x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c:
        f = c.execute("SELECT * FROM fines WHERE id=?", (fid,)).fetchone()
    if not f: raise HTTPException(404)
    return FileResponse(f["pdf_path"], media_type="application/pdf")

@app.post("/api/admin/fines/{fid}/void")
def void_fine(fid: int, x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c: c.execute("UPDATE fines SET voided=1 WHERE id=?", (fid,))
    return {"ok": True}

@app.post("/api/admin/sessions/{sid}/waive")      # dieses Auto NICHT bestrafen
def waive(sid: int, x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c: c.execute("UPDATE sessions SET fine_waived=1 WHERE id=?", (sid,))
    return {"ok": True}

class WL(BaseModel):
    plate: str
    note: str = ""

@app.post("/api/admin/whitelist")                 # Dauerhaft ausnehmen (Mitarbeiter, Anwohner ...)
def wl_add(w: WL, x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c: c.execute("REPLACE INTO whitelist VALUES(?,?)", (norm(w.plate), w.note))
    return {"ok": True}

@app.delete("/api/admin/whitelist/{plate}")
def wl_del(plate: str, x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c: c.execute("DELETE FROM whitelist WHERE plate=?", (norm(plate),))
    return {"ok": True}

# ---------- Admin-UI & Zusatz-Endpunkte ----------
@app.get("/admin")
def admin_page(): return FileResponse("static/admin.html")

@app.get("/api/admin/whitelist")
def wl_list(x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM whitelist ORDER BY plate")]

@app.get("/api/admin/sessions/{sid}/image")
def session_image(sid: int, x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c:
        r = c.execute("SELECT entry_image FROM sessions WHERE id=?", (sid,)).fetchone()
    if not r or not r["entry_image"] or not os.path.exists(r["entry_image"]): raise HTTPException(404)
    return FileResponse(r["entry_image"], media_type="image/jpeg")

@app.post("/api/admin/fines/{fid}/paid")          # z. B. Barzahlung vor Ort
def fine_mark_paid(fid: int, x_admin_key: str = Header("")):
    admin(x_admin_key)
    with db.conn() as c: c.execute("UPDATE fines SET paid_ts=? WHERE id=?", (int(time.time()), fid))
    return {"ok": True}
