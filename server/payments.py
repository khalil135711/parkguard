import os, requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
MOCK = os.getenv("PAYMENT_MOCK", "1") == "1"      # 1 = Testmodus ohne echtes Geld
PAYPAL_API = "https://api-m.paypal.com" if os.getenv("PAYPAL_ENV") == "live" else "https://api-m.sandbox.paypal.com"

def create(method, ref, amount_cents, plate, currency="EUR"):
    if MOCK:
        return {"url": f"{BASE_URL}/mock/pay/{ref}", "provider_id": "mock"}
    if method == "card":
        import stripe
        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        s = stripe.checkout.Session.create(
            mode="payment", payment_method_types=["card"],
            line_items=[{"quantity": 1, "price_data": {
                "currency": currency.lower(), "unit_amount": amount_cents,
                "product_data": {"name": f"Parken {plate}"}}}],
            success_url=f"{BASE_URL}/kiosk?paid={ref}", cancel_url=f"{BASE_URL}/kiosk",
            metadata={"ref": ref})
        return {"url": s.url, "provider_id": s.id}
    if method == "paypal":
        tok = requests.post(f"{PAYPAL_API}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                            auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_SECRET"])).json()["access_token"]
        o = requests.post(f"{PAYPAL_API}/v2/checkout/orders",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"intent": "CAPTURE",
                                "purchase_units": [{"reference_id": ref, "amount": {
                                    "currency_code": currency, "value": f"{amount_cents/100:.2f}"}}],
                                "application_context": {
                                    "return_url": f"{BASE_URL}/paypal/return?ref={ref}",
                                    "cancel_url": f"{BASE_URL}/kiosk"}}).json()
        link = next(l["href"] for l in o["links"] if l["rel"] in ("approve", "payer-action"))
        return {"url": link, "provider_id": o["id"]}
    raise ValueError("unknown method")

def paypal_capture(order_id):
    tok = requests.post(f"{PAYPAL_API}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                        auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_SECRET"])).json()["access_token"]
    r = requests.post(f"{PAYPAL_API}/v2/checkout/orders/{order_id}/capture",
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return r.json().get("status") == "COMPLETED"
