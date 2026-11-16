# ParkGuard

<img width="870" height="1296" alt="Bildschirmfoto 2026-11-16 um 17 42 02" src="https://github.com/user-attachments/assets/7f93f352-8383-4c1f-9700-750d0533c24b" />

Parkzeit-Überwachung mit Kamera, automatischem Strafzettel-PDF und Bezahlung per Automat (Karte / PayPal).

<img width="1756" height="980" alt="Bildschirmfoto 2026-11-16 um 17 45 00" src="https://github.com/user-attachments/assets/a1919eb5-88f9-4a43-ae9e-b3d92f61f1f1" />

## Architektur

```
[ESP32-S3 Kamera Einfahrt] --JPEG--> [Server (FastAPI)] <--JPEG-- [ESP32-S3 Kamera Ausfahrt]
                                        |  Kennzeichen (ANPR), Sessions, SQLite
                                        |  Strafe -> PDF (reportlab)
                                        |  Zahlung -> Stripe (Karte) / PayPal
                                        v
                           [Automat: /kiosk]  Kennzeichen eingeben -> bezahlen
```

Der ESP32-S3 ist zu schwach für ANPR, PDF und Zahlungs-APIs. Er macht Fotos und schickt sie an den Server.

## Ablauf
1. Kamera Einfahrt schickt Foto, der Server erkennt das Kennzeichen und startet die Session.
2. Admin-Einstellung `free_minutes` (Standard 60) legt die erlaubte Parkdauer fest.
3. `fine_mode`:
   - `off`: nie bestrafen (nur Gebühr am Automaten)
   - `on_overstay`: sofort Strafe + PDF, sobald die Zeit überschritten ist (Prüfung alle 30 s)
   - `on_exit`: Strafe erst bei der Ausfahrt
4. Besucher kann vorher oder nachher am Automaten zahlen (`/kiosk`). Bezahlte Stunden verschieben die Frist.
5. Ausnahmen: Whitelist (dauerhaft) oder `waive` (einzelne Session), Strafe stornieren mit `void`.

## Starten (Server)
```bash
cd server
pip install -r requirements.txt
export DEVICE_KEY=geheim1 ADMIN_KEY=geheim2 BASE_URL=http://DEINE-IP:8000
export PAYMENT_MOCK=1          # Testmodus. Für echt: 0 + Stripe/PayPal Keys
uvicorn main:app --host 0.0.0.0 --port 8000
```
Test ohne Kamera:
```bash
curl -X POST localhost:8000/api/camera/entry -H "X-Device-Key: geheim1" -H "X-Plate: BN AB 123" -F image=@foto.jpg
curl -X PUT localhost:8000/api/admin/settings -H "X-Admin-Key: geheim2" -H "Content-Type: application/json" -d '{"free_minutes":1}'
```
Dann `http://localhost:8000/kiosk` öffnen.

## Echte Zahlung
- Karte: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, Webhook auf `/webhook/stripe`
- PayPal: `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, `PAYPAL_ENV=live|sandbox`
- Physische Kartenleser (SumUp, Stripe Terminal) sind besser als Kartennummern selbst zu verarbeiten (PCI-DSS). Eigene Kartenabfrage am ESP32 solltest du nicht bauen.

## ESP32-S3
- `firmware/camera_node/camera_node.ino`: Kamera-Node (Pins für Freenove ESP32-S3 CAM, sonst anpassen).
- Auslöser: Lichtschranke/Induktionsschleife an `TRIGGER_PIN`.
- Kennzeichen brauchen gute Auflösung, Infrarot-Beleuchtung und einen engen Winkel (< 30°).
- Bezahlterminal mit ESP32-S3 + Display: zeigt per `/api/kiosk/pay` einen QR-Code, der Besucher zahlt am Handy. (Nächster Schritt.)

## Rechtliches (Deutschland)
- Kennzeichen sind personenbezogene Daten (DSGVO): Hinweisschilder, Löschfristen, Rechtsgrundlage klären.
- Privates Parken: Meist "Vertragsstrafe/erhöhtes Parkentgelt", nicht "Bußgeld". Höhe und Beschilderung rechtlich prüfen.
- Halteradresse gibt es nur über Halteranfrage (§ 39 StVG, berechtigtes Interesse). Das PDF ist zum Ausdrucken/Anbringen gedacht.
- Vor dem Einsatz Zugangsdaten ändern (DEVICE_KEY / ADMIN_KEY) und HTTPS verwenden.
