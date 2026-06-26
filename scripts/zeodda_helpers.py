"""
scripts/zeodda_helpers.py
Shared utilities untuk semua Zeodda automation scripts.
Revisi: multi-shop refresh + Cloudflare KV push.
"""

import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timedelta

# ─── Shopee credentials ───────────────────────────────────────────────────────
SHOPEE_PARTNER_ID  = int(os.environ.get("SHOPEE_PARTNER_ID", "2035358"))
SHOPEE_PARTNER_KEY = os.environ.get("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_BASE_URL    = "https://partner.shopeemobile.com"

# Default shop (untuk backward compat kode lama yg pakai shopee_get tanpa shop_id)
SHOPEE_SHOP_ID = int(os.environ.get("SHOPEE_SHOP_ID", "963980234"))

# ─── Multi-shop: active tokens per shop_id ────────────────────────────────────
# Key: int(shop_id), Value: access_token string
# Diisi oleh refresh_and_push_all_shops() di awal workflow
_active_tokens = {}

# Backward compat: token tunggal (dipakai shopee_get lama)
_SHOPEE_ACTIVE_TOKEN = os.environ.get("SHOPEE_ACCESS_TOKEN", "").strip()
if _SHOPEE_ACTIVE_TOKEN:
    _active_tokens[SHOPEE_SHOP_ID] = _SHOPEE_ACTIVE_TOKEN

# ─── Cloudflare KV credentials ────────────────────────────────────────────────
CF_ACCOUNT_ID   = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_KV_NAMESPACE = os.environ.get("CF_KV_NAMESPACE", "").strip()
CF_API_TOKEN    = os.environ.get("CF_API_TOKEN", "").strip()

# ─── Lark credentials ─────────────────────────────────────────────────────────
LARK_APP_ID     = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN  = "ItPfb0MPNaD6KhsVc65lT6p1gTh"
LARK_BASE_URL   = "https://open.larksuite.com"

TABLE_DAILY_OVERVIEW = "tblSVQG08nHr7tXD"
TABLE_PRODUCT_PERF   = "tblRlDzWXK5gQXzT"
TABLE_ADS_SHOP       = "tbl6EhWSzZumBR4L"
TABLE_ADS_PRODUCT    = "tbl3r112gUTEhHCe"
TABLE_KOMPARASI      = "tblZoIIwUj0RN93p"
TABLE_FINANCIAL      = "tblLh7liZZxPzEpl"
TABLE_ALERT_LOG      = "tblobivbXf5KBsUK"

# ─── Safe type helpers ────────────────────────────────────────────────────────
def safe_int(val):
    if val is None: return 0
    if isinstance(val, (dict, list)): return 0
    try: return int(float(str(val)))
    except: return 0

def safe_str(val):
    if val is None or isinstance(val, (dict, list)): return ""
    return str(val)

def safe_dict(d, key):
    if not isinstance(d, dict): return {}
    v = d.get(key, {})
    return v if isinstance(v, dict) else {}

def safe_list(d, key):
    if not isinstance(d, dict): return []
    v = d.get(key, [])
    return v if isinstance(v, list) else []

# ─── Date helpers ─────────────────────────────────────────────────────────────
def get_yesterday_range():
    now_wib       = datetime.utcnow() + timedelta(hours=7)
    yesterday_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    return {
        "yesterday_ms": int(yesterday_wib.timestamp() * 1000),
        "date_str":     yesterday_wib.strftime("%Y-%m-%d"),
        "date_str_dmy": yesterday_wib.strftime("%d-%m-%Y"),
        "ts_start":     int((yesterday_wib - timedelta(hours=7)).timestamp()),
        "ts_end":       int((yesterday_wib + timedelta(hours=17) - timedelta(seconds=1)).timestamp()),
        "label":        yesterday_wib.strftime("%Y-%m-%d"),
    }

# ─── Shopee: HMAC-SHA256 signature ───────────────────────────────────────────
def shopee_sign(path, timestamp, access_token=None, shop_id=None):
    """
    Dengan access_token + shop_id → signature untuk API biasa.
    Tanpa keduanya           → signature untuk refresh_token (tidak butuh auth).
    """
    if access_token and shop_id:
        base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}{access_token}{shop_id}"
    else:
        base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}"
    return hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()

# ─── Cloudflare KV: push satu token ──────────────────────────────────────────
def push_token_to_kv(shop_id, access_token):
    """
    Push access_token ke Cloudflare KV dengan key 'token:{shop_id}'.
    Return True jika berhasil.
    """
    if not all([CF_ACCOUNT_ID, CF_KV_NAMESPACE, CF_API_TOKEN]):
        print(f"  ⚠️ [KV] Kredensial CF belum lengkap — skip push shop {shop_id}")
        return False

    # Key pakai format token:{shop_id} — URL-encode ':' jadi %3A
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}"
        f"/storage/kv/namespaces/{CF_KV_NAMESPACE}/values/token%3A{shop_id}"
    )
    try:
        r      = requests.put(
            url,
            headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
            data=str(access_token),
            timeout=30
        )
        result = r.json()
        if result.get("success"):
            print(f"  ✅ [KV] shop {shop_id}: token berhasil di-push ke KV")
            return True
        errors = result.get("errors", [])
        print(f"  ❌ [KV] shop {shop_id}: gagal push — {errors}")
        return False
    except Exception as e:
        print(f"  ❌ [KV] shop {shop_id}: request error — {e}")
        return False

# ─── Shopee: refresh token satu toko ─────────────────────────────────────────
def refresh_shop_token(shop_id, refresh_token):
    """
    Refresh access_token untuk satu shop_id menggunakan refresh_token-nya.
    Return access_token baru (str) atau None jika gagal.
    """
    if not refresh_token:
        print(f"  ⚠️ [REFRESH] shop {shop_id}: refresh_token kosong, skip")
        return None

    path = "/api/v2/auth/access_token/get"
    ts   = int(time.time())
    # Signature refresh: TANPA access_token & shop_id
    sign = shopee_sign(path, ts)

    try:
        r = requests.post(
            f"{SHOPEE_BASE_URL}{path}",
            params={"partner_id": SHOPEE_PARTNER_ID, "timestamp": ts, "sign": sign},
            json={"refresh_token": refresh_token, "partner_id": SHOPEE_PARTNER_ID, "shop_id": shop_id},
            timeout=30
        )
        data = r.json()
        tok  = data.get("access_token")
        if tok:
            _active_tokens[int(shop_id)] = tok
            print(f"  ✅ [REFRESH] shop {shop_id}: token baru didapat")
            return tok
        print(f"  ❌ [REFRESH] shop {shop_id}: {data.get('error')} — {data.get('message', '')}")
        return None
    except Exception as e:
        print(f"  ❌ [REFRESH] shop {shop_id}: request error — {e}")
        return None

# ─── Refresh + push SEMUA toko ke KV ─────────────────────────────────────────
def refresh_and_push_all_shops():
    """
    Loop semua shop ID dari SHOPEE_SHOP_IDS, refresh token tiap toko
    (dari SHOPEE_REFRESH_TOKEN_{shop_id}), lalu push ke Cloudflare KV.
    Dipanggil SATU KALI di awal setiap workflow run.
    """
    raw = os.environ.get("SHOPEE_SHOP_IDS", "").strip()
    if not raw:
        print("⚠️ [REFRESH_ALL] SHOPEE_SHOP_IDS kosong — tidak ada toko yang di-refresh")
        return

    shop_ids = []
    for s in raw.replace(" ", "").split(","):
        s = s.strip()
        if s:
            try: shop_ids.append(int(s))
            except ValueError: pass

    print(f"\n{'='*55}")
    print(f"🔄 Refresh & push token untuk {len(shop_ids)} toko ke Cloudflare KV")
    print(f"{'='*55}")

    ok_count = 0
    for sid in shop_ids:
        rt  = os.environ.get(f"SHOPEE_REFRESH_TOKEN_{sid}", "").strip()
        tok = refresh_shop_token(sid, rt)
        if tok:
            success = push_token_to_kv(sid, tok)
            if success:
                ok_count += 1
        time.sleep(0.5)  # hindari rate limit Shopee & Cloudflare

    print(f"{'='*55}")
    print(f"✅ Selesai: {ok_count}/{len(shop_ids)} toko berhasil refresh + push ke KV")
    print(f"{'='*55}\n")

# ─── Shopee: refresh token (backward compat, satu toko) ──────────────────────
def refresh_shopee_token():
    """
    Backward compat: refresh token untuk SHOPEE_SHOP_ID default.
    Sekarang juga push ke KV otomatis.
    """
    global _SHOPEE_ACTIVE_TOKEN
    rt = os.environ.get("SHOPEE_REFRESH_TOKEN", "").strip()
    tok = refresh_shop_token(SHOPEE_SHOP_ID, rt)
    if tok:
        _SHOPEE_ACTIVE_TOKEN = tok
        push_token_to_kv(SHOPEE_SHOP_ID, tok)

# ─── Shopee GET (single shop, backward compat) ───────────────────────────────
def shopee_get(path, extra={}):
    global _SHOPEE_ACTIVE_TOKEN
    tok = _active_tokens.get(SHOPEE_SHOP_ID, _SHOPEE_ACTIVE_TOKEN)
    ts  = int(time.time())

    params = {
        "partner_id":   SHOPEE_PARTNER_ID,
        "timestamp":    ts,
        "access_token": tok,
        "shop_id":      SHOPEE_SHOP_ID,
        "sign":         shopee_sign(path, ts, tok, SHOPEE_SHOP_ID),
    }
    clean_extra = {k: v for k, v in extra.items() if k != "_is_retry"}
    params.update(clean_extra)

    try:
        r    = requests.get(f"{SHOPEE_BASE_URL}{path}", params=params, timeout=30)
        data = r.json()

        if data.get("error") == "invalid_acceess_token" and extra.get("_is_retry") is not True:
            print("🔄 [API] Token kedaluwarsa, mencoba refresh...")
            refresh_shopee_token()
            extra["_is_retry"] = True
            return shopee_get(path, extra)

        if data.get("error") and data.get("error") != "":
            print(f"  ⚠️ [{path}]: {data.get('error')} — {data.get('message','')[:80]}")
        return data.get("response") or {}
    except Exception as e:
        print(f"  ❌ Request error {path}: {e}")
        return {}

# ─── Shopee GET multi-shop ────────────────────────────────────────────────────
def shopee_get_shop(path, shop_id, extra={}):
    """Panggil Shopee GET API untuk shop_id tertentu (multi-shop)."""
    tok = _active_tokens.get(int(shop_id), "")
    if not tok:
        print(f"  ⚠️ [API] Token shop {shop_id} tidak ada di _active_tokens")
        return {}

    ts = int(time.time())
    params = {
        "partner_id":   SHOPEE_PARTNER_ID,
        "timestamp":    ts,
        "access_token": tok,
        "shop_id":      shop_id,
        "sign":         shopee_sign(path, ts, tok, shop_id),
    }
    clean_extra = {k: v for k, v in extra.items() if k != "_is_retry"}
    params.update(clean_extra)

    try:
        r    = requests.get(f"{SHOPEE_BASE_URL}{path}", params=params, timeout=30)
        data = r.json()

        if data.get("error") == "invalid_acceess_token" and extra.get("_is_retry") is not True:
            print(f"🔄 [API] Token shop {shop_id} kedaluwarsa, refresh...")
            rt  = os.environ.get(f"SHOPEE_REFRESH_TOKEN_{shop_id}", "").strip()
            new = refresh_shop_token(shop_id, rt)
            if new:
                push_token_to_kv(shop_id, new)
            extra["_is_retry"] = True
            return shopee_get_shop(path, shop_id, extra)

        if data.get("error") and data.get("error") != "":
            print(f"  ⚠️ [{path}] shop {shop_id}: {data.get('error')} — {data.get('message','')[:80]}")
        return data.get("response") or {}
    except Exception as e:
        print(f"  ❌ Request error {path} shop {shop_id}: {e}")
        return {}

# ─── Lark helpers ─────────────────────────────────────────────────────────────
_lark_tenant_token = None

def get_lark_tenant_token():
    global _lark_tenant_token
    if _lark_tenant_token: return _lark_tenant_token
    url  = f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
    r    = requests.post(url, json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=30)
    data = r.json()
    if data.get("code") != 0:
        raise Exception(f"Lark token error: {data.get('msg')}")
    _lark_tenant_token = data["tenant_access_token"]
    return _lark_tenant_token

def get_lark_headers():
    return {"Authorization": f"Bearer {get_lark_tenant_token()}", "Content-Type": "application/json"}

def lark_add(table_id, fields):
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records"
    try:
        r      = requests.post(url, headers=get_lark_headers(), json={"fields": fields}, timeout=30)
        result = r.json()
        if result.get("code") != 0:
            print(f"  ❌ Lark error {result.get('code')}: {result.get('msg')}")
        return result
    except Exception as e:
        print(f"  ❌ Lark request error: {e}")
        return {"code": -1}

def lark_add_batch(table_id, records_list):
    if not records_list: return {"code": 0}
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/batch_create"
    try:
        r      = requests.post(url, headers=get_lark_headers(),
                     json={"records": [{"fields": f} for f in records_list]}, timeout=30)
        result = r.json()
        if result.get("code") != 0:
            print(f"  ❌ Lark batch error {result.get('code')}: {result.get('msg')}")
        return result
    except Exception as e:
        print(f"  ❌ Lark batch error: {e}")
        return {"code": -1}

def lark_init():
    if not LARK_APP_ID or not LARK_APP_SECRET:
        raise Exception("❌ LARK_APP_ID atau LARK_APP_SECRET tidak ada!")
    get_lark_tenant_token()
