"""OpenRAROC Premium API server.

Handles Stripe checkout, API key management, premium bank data,
and the admin dashboard.
"""

import json
import os

import stripe
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .auth import get_storage, require_admin, require_api_key
from .emails import send_welcome, send_renewal_reminder, send_data_update, send_payment_failed
from .storage import JsonStorage

app = FastAPI(title="OpenRAROC API", version="1.0.0")

# CORS — allow the web app origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://openraroc.com",
        "https://www.openraroc.com",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Stripe config
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://openraroc.com")
API_URL = os.environ.get("API_URL", "https://api.openraroc.com")

# Bank data
_banks_data: dict | None = None


def _load_banks() -> dict:
    global _banks_data
    if _banks_data is not None:
        return _banks_data

    # Free banks (same as raroc_engine/banks.py)
    free = {
        "bnp_paribas": {
            "name": "BNP Paribas", "country": "France", "irb_approach": "A-IRB",
            "cost_to_income": 0.618, "effective_tax_rate": 0.262,
            "avg_lgd_unsecured": 0.37, "avg_lgd_secured": 0.20,
            "funding_spread_bp": 0.0015,
            "corporate_ead_bn": 260, "corporate_avg_pd": 0.0221,
            "source": "BNP Paribas URD 2025 Ch.5 CR6; FY25 Results",
            "confidence": "high", "tier": "free",
        },
        "hsbc": {
            "name": "HSBC", "country": "United Kingdom", "irb_approach": "A-IRB",
            "cost_to_income": 0.502, "effective_tax_rate": 0.226,
            "avg_lgd_unsecured": 0.459, "avg_lgd_secured": 0.25,
            "funding_spread_bp": 0.0010,
            "corporate_ead_bn": 25, "corporate_avg_pd": 0.0042,
            "source": "HSBC Pillar 3 31 Dec 2025 CR6; FY25 Annual Report",
            "confidence": "high", "tier": "free",
        },
        "deutsche_bank": {
            "name": "Deutsche Bank", "country": "Germany", "irb_approach": "Mixed",
            "cost_to_income": 0.76, "effective_tax_rate": 0.34,
            "avg_lgd_unsecured": 0.3927, "avg_lgd_secured": 0.1690,
            "funding_spread_bp": 0.0025,
            "corporate_ead_bn": 129, "corporate_avg_pd": 0.0256,
            "source": "Deutsche Bank Pillar 3 FY2025 CR6; FY25 Results",
            "confidence": "high", "tier": "free",
        },
        "jp_morgan": {
            "name": "JP Morgan", "country": "United States", "irb_approach": "A-IRB",
            "cost_to_income": 0.55, "effective_tax_rate": 0.24,
            "avg_lgd_unsecured": 0.2216, "avg_lgd_secured": 0.15,
            "funding_spread_bp": 0.0010,
            "corporate_ead_bn": 2019, "corporate_avg_pd": 0.0132,
            "source": "JPM Pillar 3 Q2 2025 Wholesale Table; Annual Report",
            "confidence": "high", "tier": "free",
        },
    }

    # Load premium banks from JSON
    premium_path = os.environ.get("RAROC_PREMIUM_BANKS", "/app/premium_banks.json")
    fallbacks = [premium_path, "premium_banks.json", os.path.expanduser("~/.raroc/premium_banks.json")]
    premium = {}
    for path in fallbacks:
        if os.path.isfile(path):
            with open(path) as f:
                premium = json.load(f)
            for key in premium:
                premium[key]["tier"] = "premium"
                premium[key].setdefault("confidence", "high")
            break

    _banks_data = {**free, **premium}
    return _banks_data


# ── Public endpoints ─────────────────────────────────────────────

@app.get("/v1/status")
async def status():
    banks = _load_banks()
    return {"status": "ok", "version": "1.0.0", "banks": len(banks)}


@app.get("/v1/checkout")
async def checkout(email: str = ""):
    if not email or "@" not in email:
        raise HTTPException(400, "Valid email required")
    if not stripe.api_key or not STRIPE_PRICE_ID:
        raise HTTPException(503, "Payment system not configured")

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        customer_email=email,
        success_url=f"{API_URL.rstrip('/')}/v1/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=WEBAPP_URL,
    )
    return RedirectResponse(session.url, status_code=303)


@app.get("/v1/checkout/success")
async def checkout_success(session_id: str = "", storage: JsonStorage = Depends(get_storage)):
    if not session_id:
        return RedirectResponse(WEBAPP_URL, status_code=303)

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return RedirectResponse(WEBAPP_URL, status_code=303)

    # Create customer + key (idempotent)
    customer = None
    if session.customer:
        customer = storage.find_customer_by_stripe(str(session.customer))
    if not customer:
        customer = storage.add_customer(
            email=session.customer_email or "",
            stripe_customer_id=str(session.customer or ""),
            stripe_subscription_id=str(session.subscription or ""),
        )

    api_key = storage.add_key(customer.id)
    if customer.email:
        send_welcome(customer.email, api_key.key)
    return RedirectResponse(f"{WEBAPP_URL}/app?key={api_key.key}", status_code=303)


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, storage: JsonStorage = Depends(get_storage)):
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(body, sig, STRIPE_WEBHOOK_SECRET)
        except (stripe.SignatureVerificationError, ValueError):
            raise HTTPException(400, "Invalid webhook signature")
    else:
        event = json.loads(body)

    event_type = event.get("type", "")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email", "")
        stripe_cid = session.get("customer", "")
        stripe_sid = session.get("subscription", "")

        customer = None
        if stripe_cid:
            customer = storage.find_customer_by_stripe(stripe_cid)
        if not customer:
            customer = storage.add_customer(
                email=email,
                stripe_customer_id=stripe_cid,
                stripe_subscription_id=stripe_sid,
            )
        api_key = storage.add_key(customer.id)
        if email:
            send_welcome(email, api_key.key)

    elif event_type == "invoice.payment_failed":
        invoice = event["data"]["object"]
        customer_email = invoice.get("customer_email", "")
        if customer_email:
            send_payment_failed(customer_email)

    return JSONResponse({"received": True})


@app.get("/v1/banks")
async def get_banks(
    _key: str = Depends(require_api_key),
):
    banks = _load_banks()
    result = []
    for key, data in banks.items():
        entry = {"key": key, **data}
        result.append(entry)
    return {"banks": result, "total": len(result)}


# ── Admin endpoints ──────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    email: str
    organization: str = ""
    expires_days: int = 365


@app.get("/admin/api/customers")
async def admin_list_customers(
    _admin: str = Depends(require_admin),
    storage: JsonStorage = Depends(get_storage),
):
    return {"customers": storage.list_customers_with_keys()}


@app.post("/admin/api/keys")
async def admin_create_key(
    req: CreateKeyRequest,
    _admin: str = Depends(require_admin),
    storage: JsonStorage = Depends(get_storage),
):
    customer = storage.find_customer_by_email(req.email)
    if not customer:
        customer = storage.add_customer(email=req.email, organization=req.organization)
    api_key = storage.add_key(customer.id, expires_days=req.expires_days)
    return {"customer": customer.model_dump(), "key": api_key.model_dump()}


@app.delete("/admin/api/keys/{key_str}")
async def admin_revoke_key(
    key_str: str,
    _admin: str = Depends(require_admin),
    storage: JsonStorage = Depends(get_storage),
):
    if not storage.revoke_key(key_str):
        raise HTTPException(404, "Key not found")
    return {"revoked": True}


class DataUpdateRequest(BaseModel):
    message: str = "Bank data has been updated with the latest Pillar 3 filings."


@app.post("/admin/api/send-reminders")
async def admin_send_reminders(
    _admin: str = Depends(require_admin),
    storage: JsonStorage = Depends(get_storage),
):
    """Send renewal reminders to customers with keys expiring in 30 or 7 days."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent = []

    for days in [7, 30]:
        for key, customer in storage.get_expiring_keys(within_days=days):
            # Skip if already reminded today
            if key.last_reminder_sent == today:
                continue
            if send_renewal_reminder(customer.email, days):
                storage.mark_reminder_sent(key.key)
                sent.append({"email": customer.email, "days_left": days})

    return {"sent": len(sent), "reminders": sent}


@app.post("/admin/api/send-data-update")
async def admin_send_data_update(
    req: DataUpdateRequest,
    _admin: str = Depends(require_admin),
    storage: JsonStorage = Depends(get_storage),
):
    """Send data update notification to all active Pro customers."""
    customers = storage.get_active_customers()
    sent = []
    for customer in customers:
        if send_data_update(customer.email, req.message):
            sent.append(customer.email)

    return {"sent": len(sent), "emails": sent}


# ── Admin dashboard ──────────────────────────────────────────────

ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenRAROC Admin</title>
<style>
  :root {
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #f1f5f9; --muted: #94a3b8; --accent: #3b82f6;
    --green: #22c55e; --red: #ef4444; --yellow: #eab308;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
  .header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header .version { color: var(--muted); font-size: 13px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }

  /* Auth overlay */
  #auth-overlay { position: fixed; inset: 0; background: var(--bg); z-index: 100; display: flex; align-items: center; justify-content: center; }
  #auth-overlay .auth-box { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 32px; width: 380px; text-align: center; }
  #auth-overlay h2 { margin-bottom: 16px; font-size: 18px; }
  #auth-overlay input { width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 14px; margin-bottom: 12px; }
  #auth-overlay button { width: 100%; padding: 10px; border-radius: 8px; border: none; background: var(--accent); color: white; font-size: 14px; font-weight: 600; cursor: pointer; }
  #auth-overlay button:hover { opacity: 0.9; }
  #auth-error { color: var(--red); font-size: 13px; margin-top: 8px; min-height: 20px; }

  /* Cards */
  .section { margin-bottom: 32px; }
  .section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .section-header h2 { font-size: 16px; font-weight: 600; }
  .badge { background: var(--accent); color: white; font-size: 12px; padding: 2px 8px; border-radius: 10px; font-weight: 600; }

  /* Table */
  table { width: 100%; border-collapse: collapse; background: var(--surface); border-radius: 8px; overflow: hidden; }
  th { text-align: left; padding: 10px 14px; font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border); }
  td { padding: 10px 14px; font-size: 13px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(59,130,246,0.05); }

  .status-active { color: var(--green); }
  .status-revoked { color: var(--red); }
  .status-expired { color: var(--yellow); }

  .key-text { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; color: var(--muted); }
  .btn { padding: 5px 12px; border-radius: 6px; border: none; font-size: 12px; font-weight: 600; cursor: pointer; }
  .btn-red { background: rgba(239,68,68,0.15); color: var(--red); }
  .btn-red:hover { background: rgba(239,68,68,0.25); }
  .btn-blue { background: var(--accent); color: white; }
  .btn-blue:hover { opacity: 0.9; }

  /* Create form */
  .create-form { background: var(--surface); border-radius: 8px; padding: 16px; display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
  .create-form .field { display: flex; flex-direction: column; gap: 4px; }
  .create-form label { font-size: 12px; color: var(--muted); font-weight: 600; }
  .create-form input { padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 13px; }
  .create-form input:focus { outline: none; border-color: var(--accent); }

  .empty { text-align: center; padding: 32px; color: var(--muted); font-size: 14px; }
  .stats { display: flex; gap: 16px; margin-bottom: 24px; }
  .stat { background: var(--surface); border-radius: 8px; padding: 16px 20px; flex: 1; }
  .stat .label { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
  .stat .value { font-size: 24px; font-weight: 700; }

  /* Email section */
  .email-actions { background: var(--surface); border-radius: 8px; padding: 16px; display: flex; gap: 16px; align-items: stretch; flex-wrap: wrap; }
  .email-card { flex: 1; min-width: 240px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
  .email-card h3 { font-size: 14px; font-weight: 600; color: var(--text); }
  .email-card p { font-size: 12px; color: var(--muted); margin: 0; flex: 1; }
  .email-card textarea { padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); font-size: 12px; font-family: inherit; resize: vertical; min-height: 48px; }
  .email-card textarea:focus { outline: none; border-color: var(--accent); }
  .btn-green { background: rgba(34,197,94,0.15); color: var(--green); }
  .btn-green:hover { background: rgba(34,197,94,0.25); }

  /* Toast */
  .toast { position: fixed; bottom: 24px; right: 24px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 20px; font-size: 13px; color: var(--text); box-shadow: 0 4px 12px rgba(0,0,0,0.3); transform: translateY(80px); opacity: 0; transition: all 0.3s ease; z-index: 200; max-width: 400px; }
  .toast.show { transform: translateY(0); opacity: 1; }
  .toast.success { border-color: var(--green); }
  .toast.error { border-color: var(--red); }
</style>
</head>
<body>

<div id="auth-overlay">
  <div class="auth-box">
    <h2>Admin Login</h2>
    <p style="color:var(--muted);font-size:13px;margin-bottom:16px;">Enter your admin key to continue</p>
    <input type="password" id="admin-key-input" placeholder="Admin key" onkeydown="if(event.key==='Enter')authenticate()">
    <button onclick="authenticate()">Sign In</button>
    <div id="auth-error"></div>
  </div>
</div>

<div class="header">
  <div><h1>OpenRAROC Admin</h1></div>
  <div class="version">v1.0.0</div>
</div>

<div class="container">
  <div class="stats" id="stats">
    <div class="stat"><div class="label">Customers</div><div class="value" id="stat-customers">-</div></div>
    <div class="stat"><div class="label">Active Keys</div><div class="value" id="stat-keys">-</div></div>
    <div class="stat"><div class="label">Calculations</div><div class="value" id="stat-calcs">-</div></div>
    <div class="stat"><div class="label">Portfolios</div><div class="value" id="stat-portfolios">-</div></div>
    <div class="stat"><div class="label">Comparisons</div><div class="value" id="stat-compares">-</div></div>
  </div>

  <div class="section">
    <div class="section-header">
      <h2>Usage (last 14 days)</h2>
    </div>
    <div id="analytics-chart" style="background:var(--surface);border-radius:8px;padding:16px;min-height:120px;display:flex;align-items:end;gap:4px;"></div>
  </div>

  <div class="section">
    <div class="section-header">
      <h2>Create API Key</h2>
    </div>
    <div class="create-form">
      <div class="field" style="flex:2"><label>Email</label><input type="email" id="new-email" placeholder="cfo@company.com"></div>
      <div class="field" style="flex:2"><label>Organization</label><input type="text" id="new-org" placeholder="Acme Corp"></div>
      <div class="field" style="flex:1"><label>Expires (days)</label><input type="number" id="new-expires" value="365" min="1"></div>
      <button class="btn btn-blue" onclick="createKey()" style="padding:8px 20px;height:35px;">Create</button>
    </div>
  </div>

  <div class="section">
    <div class="section-header">
      <h2>Customers</h2>
      <span class="badge" id="customer-count">0</span>
    </div>
    <table id="customer-table">
      <thead><tr><th>Email</th><th>Organization</th><th>Status</th><th>Created</th><th>Keys</th></tr></thead>
      <tbody id="customer-tbody"></tbody>
    </table>
  </div>

  <div class="section">
    <div class="section-header">
      <h2>API Keys</h2>
      <span class="badge" id="key-count">0</span>
    </div>
    <table id="key-table">
      <thead><tr><th>Key</th><th>Customer</th><th>Status</th><th>Created</th><th>Expires</th><th>Last Used</th><th></th></tr></thead>
      <tbody id="key-tbody"></tbody>
    </table>
  </div>

  <div class="section">
    <div class="section-header">
      <h2>Emails</h2>
    </div>
    <div class="email-actions">
      <div class="email-card">
        <h3>Renewal Reminders</h3>
        <p>Send reminders to customers with keys expiring in 7 or 30 days. Safe to run multiple times — only sends once per day per customer.</p>
        <button class="btn btn-green" onclick="sendReminders()" id="btn-reminders" style="padding:8px 16px;">Send Reminders</button>
      </div>
      <div class="email-card">
        <h3>Data Update Notification</h3>
        <p>Notify all active Pro customers about a bank data update.</p>
        <textarea id="update-message" placeholder="e.g. Updated 19 banks to FY2025 data from latest Pillar 3 filings."></textarea>
        <button class="btn btn-green" onclick="sendDataUpdate()" id="btn-update" style="padding:8px 16px;">Send to All Customers</button>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let adminKey = sessionStorage.getItem('raroc_admin_key') || '';
let data = null;

function apiBase() { return window.location.origin; }

function headers() {
  return { 'Authorization': 'Bearer ' + adminKey, 'Content-Type': 'application/json' };
}

async function authenticate() {
  const input = document.getElementById('admin-key-input');
  const key = input.value.trim();
  if (!key) return;
  try {
    const r = await fetch(apiBase() + '/admin/api/customers', { headers: { 'Authorization': 'Bearer ' + key } });
    if (r.ok) {
      adminKey = key;
      sessionStorage.setItem('raroc_admin_key', key);
      document.getElementById('auth-overlay').style.display = 'none';
      loadData();
    } else {
      document.getElementById('auth-error').textContent = 'Invalid admin key';
    }
  } catch (e) {
    document.getElementById('auth-error').textContent = 'Connection error';
  }
}

const WEBAPP = 'https://openraroc.com';

async function loadData() {
  try {
    const r = await fetch(apiBase() + '/admin/api/customers', { headers: headers() });
    if (!r.ok) { sessionStorage.removeItem('raroc_admin_key'); location.reload(); return; }
    const json = await r.json();
    data = json.customers || [];
    render();
    loadAnalytics();
  } catch (e) {
    console.error('Load error:', e);
  }
}

async function loadAnalytics() {
  try {
    const r = await fetch(WEBAPP + '/api/analytics?days=14');
    if (!r.ok) return;
    const stats = await r.json();
    const ev = stats.by_event || {};
    document.getElementById('stat-calcs').textContent = ev.calculate || 0;
    document.getElementById('stat-portfolios').textContent = ev.portfolio_upload || 0;
    document.getElementById('stat-compares').textContent = ev.compare_banks || 0;
    renderAnalyticsChart(stats.by_day || {});
  } catch (e) {
    console.error('Analytics error:', e);
  }
}

function renderAnalyticsChart(byDay) {
  const chart = document.getElementById('analytics-chart');
  const days = Object.keys(byDay).sort().slice(-14);
  if (!days.length) { chart.innerHTML = '<div class="empty" style="width:100%">No usage data yet</div>'; return; }

  // Fill in missing days
  const allDays = [];
  if (days.length > 0) {
    const start = new Date(days[0]);
    const end = new Date(days[days.length - 1]);
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      allDays.push(d.toISOString().slice(0, 10));
    }
  }

  const maxVal = Math.max(...allDays.map(d => {
    const ev = byDay[d] || {};
    return Object.values(ev).reduce((a, b) => a + b, 0);
  }), 1);

  const colors = {calculate:'var(--accent)',portfolio_upload:'var(--green)',compare_banks:'#a855f7',solve:'var(--yellow)',sensitivity:'var(--muted)'};

  chart.innerHTML = allDays.map(d => {
    const ev = byDay[d] || {};
    const total = Object.values(ev).reduce((a, b) => a + b, 0);
    const pct = Math.max((total / maxVal) * 100, 2);
    const label = d.slice(5); // MM-DD
    const parts = Object.entries(ev).map(([k,v]) => `${k}: ${v}`).join(', ');
    return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;" title="${d}: ${parts || 'no events'}">
      <div style="width:100%;height:80px;display:flex;flex-direction:column;justify-content:flex-end;">
        <div style="width:100%;height:${pct}%;background:var(--accent);border-radius:3px;min-height:2px;"></div>
      </div>
      <div style="font-size:9px;color:var(--muted);transform:rotate(-45deg);white-space:nowrap;">${label}</div>
      <div style="font-size:10px;color:var(--text);font-weight:600;">${total||''}</div>
    </div>`;
  }).join('');
}

function fmtDate(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function fmtDateTime(iso) {
  if (!iso) return 'Never';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function isExpired(iso) {
  if (!iso) return false;
  return new Date(iso) < new Date();
}

function render() {
  if (!data) return;
  const allKeys = data.flatMap(c => (c.keys || []).map(k => ({...k, email: c.email})));
  const activeKeys = allKeys.filter(k => k.active && !isExpired(k.expires_at));
  const today = new Date().toISOString().slice(0, 10);
  const callsToday = allKeys.filter(k => k.last_used && k.last_used.slice(0, 10) === today).length;

  document.getElementById('stat-customers').textContent = data.length;
  document.getElementById('stat-keys').textContent = activeKeys.length;
  document.getElementById('customer-count').textContent = data.length;
  document.getElementById('key-count').textContent = allKeys.length;

  // Customers table
  const ctbody = document.getElementById('customer-tbody');
  if (data.length === 0) {
    ctbody.innerHTML = '<tr><td colspan="5" class="empty">No customers yet</td></tr>';
  } else {
    ctbody.innerHTML = data.map(c => `<tr>
      <td>${esc(c.email)}</td>
      <td>${esc(c.organization || '-')}</td>
      <td><span class="status-${c.status === 'active' ? 'active' : 'revoked'}">${c.status}</span></td>
      <td>${fmtDate(c.created_at)}</td>
      <td>${(c.keys || []).filter(k => k.active).length} / ${(c.keys || []).length}</td>
    </tr>`).join('');
  }

  // Keys table
  const ktbody = document.getElementById('key-tbody');
  if (allKeys.length === 0) {
    ktbody.innerHTML = '<tr><td colspan="7" class="empty">No API keys yet</td></tr>';
  } else {
    ktbody.innerHTML = allKeys.map(k => {
      const expired = isExpired(k.expires_at);
      const statusClass = !k.active ? 'revoked' : expired ? 'expired' : 'active';
      const statusText = !k.active ? 'Revoked' : expired ? 'Expired' : 'Active';
      return `<tr>
        <td class="key-text" title="${esc(k.key)}">${esc(k.key.slice(0, 12))}...</td>
        <td>${esc(k.email)}</td>
        <td><span class="status-${statusClass}">${statusText}</span></td>
        <td>${fmtDate(k.created_at)}</td>
        <td>${fmtDate(k.expires_at)}</td>
        <td>${fmtDateTime(k.last_used)}</td>
        <td>${k.active ? `<button class="btn btn-red" onclick="revokeKey('${esc(k.key)}')">Revoke</button>` : ''}</td>
      </tr>`;
    }).join('');
  }
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

async function createKey() {
  const email = document.getElementById('new-email').value.trim();
  const org = document.getElementById('new-org').value.trim();
  const expires = parseInt(document.getElementById('new-expires').value) || 365;
  if (!email || !email.includes('@')) { document.getElementById('new-email').style.borderColor = 'var(--red)'; return; }
  document.getElementById('new-email').style.borderColor = '';

  const r = await fetch(apiBase() + '/admin/api/keys', {
    method: 'POST', headers: headers(),
    body: JSON.stringify({ email, organization: org, expires_days: expires }),
  });
  if (r.ok) {
    const result = await r.json();
    document.getElementById('new-email').value = '';
    document.getElementById('new-org').value = '';
    alert('Key created: ' + result.key.key);
    loadData();
  }
}

async function revokeKey(key) {
  if (!confirm('Revoke this key? The customer will lose API access.')) return;
  const r = await fetch(apiBase() + '/admin/api/keys/' + encodeURIComponent(key), {
    method: 'DELETE', headers: headers(),
  });
  if (r.ok) loadData();
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (type || '');
  setTimeout(() => { t.className = 'toast'; }, 4000);
}

async function sendReminders() {
  const btn = document.getElementById('btn-reminders');
  btn.disabled = true; btn.textContent = 'Sending...';
  try {
    const r = await fetch(apiBase() + '/admin/api/send-reminders', { method: 'POST', headers: headers() });
    const d = await r.json();
    if (d.sent > 0) {
      showToast('Sent ' + d.sent + ' reminder(s): ' + d.reminders.map(r => r.email).join(', '), 'success');
    } else {
      showToast('No reminders needed today', 'success');
    }
  } catch (e) { showToast('Error: ' + e.message, 'error'); }
  btn.disabled = false; btn.textContent = 'Send Reminders';
}

async function sendDataUpdate() {
  const msg = document.getElementById('update-message').value.trim();
  if (!msg) { document.getElementById('update-message').style.borderColor = 'var(--red)'; return; }
  document.getElementById('update-message').style.borderColor = '';
  const btn = document.getElementById('btn-update');
  btn.disabled = true; btn.textContent = 'Sending...';
  try {
    const r = await fetch(apiBase() + '/admin/api/send-data-update', {
      method: 'POST', headers: headers(), body: JSON.stringify({ message: msg }),
    });
    const d = await r.json();
    if (d.sent > 0) {
      showToast('Sent data update to ' + d.sent + ' customer(s)', 'success');
      document.getElementById('update-message').value = '';
    } else {
      showToast('No active customers to notify', 'success');
    }
  } catch (e) { showToast('Error: ' + e.message, 'error'); }
  btn.disabled = false; btn.textContent = 'Send to All Customers';
}

// Auto-login if key saved
if (adminKey) {
  document.getElementById('auth-overlay').style.display = 'none';
  loadData();
}

// Auto-refresh every 30s
setInterval(() => { if (adminKey) loadData(); }, 30000);
</script>
</body>
</html>"""


@app.get("/admin/", response_class=HTMLResponse)
async def admin_dashboard():
    return ADMIN_HTML
