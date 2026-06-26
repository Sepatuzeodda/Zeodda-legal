"""
scripts/zeodda_helpers.py
Shared utilities untuk semua Zeodda automation scripts.
Revisi: Menambahkan mekanisme auto-refresh SHOPEE_ACCESS_TOKEN menggunakan SHOPEE_REFRESH_TOKEN.
"""

import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timedelta

SHOPEE_PARTNER_ID    = int(os.environ.get("SHOPEE_PARTNER_ID", "2035358"))
SHOPEE_PARTNER_KEY   = os.environ.get("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_SHOP_ID       = int(os.environ.get("SHOPEE_SHOP_ID", "963980234"))
SHOPEE_REFRESH_TOKEN = os.environ.get("SHOPEE_REFRESH_TOKEN", "").strip() # Wajib ditambahkan di GitHub Secrets
SHOPEE_BASE_URL      = "https://partner.shopeemobile.com"

# Global variable untuk menampung token aktif hasil refresh otomatis
_SHOPEE_ACTIVE_TOKEN = os.environ.get("SHOPEE_ACCESS_TOKEN", "").strip()

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

def shopee_sign(path, timestamp, access_token=None):
    # Menggunakan token aktif baru jika ada
    tok = access_token if access_token is not None else _SHOPEE_ACTIVE_TOKEN
    base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}{tok}{SHOPEE_SHOP_ID}"
    return hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()

def refresh_shopee_token():
    """Fungsi otomatis untuk memperbarui access_token memakai refresh_token."""
    global _SHOPEE_ACTIVE_TOKEN
    if not SHOPEE_REFRESH_TOKEN:
        print("⚠️ [REFRESH] SHOPEE_REFRESH_TOKEN tidak ditemukan di Environment Variables!")
        return
        
    path = "/api/v2/auth/access_token/get"
    ts = int(time.time())
    
    # Signature untuk refresh token tidak menggunakan access_token & shop_id
    base_sign = f"{SHOPEE_PARTNER_ID}{path}{ts}"
    sign = hmac.new(SHOPEE_PARTNER_KEY.encode(), base_sign.encode(), hashlib.sha256).hexdigest()
    
    url = f"{SHOPEE_BASE_URL}{path}"
    params = {
        "partner_id": SHOPEE_PARTNER_ID,
        "timestamp": ts,
        "sign": sign
    }
    payload = {
        "refresh_token": SHOPEE_REFRESH_TOKEN,
        "partner_id": SHOPEE_PARTNER_ID,
        "shop_id": SHOPEE_SHOP_ID
    }
    
    try:
        r = requests.post(url, params=params, json=payload, timeout=30)
        res_data = r.json()
        if "access_token" in res_data:
            _SHOPEE_ACTIVE_TOKEN = res_data["access_token"]
            print(f"🔄 [REFRESH] Sukses memperbarui Access Token Shopee untuk sesi ini.")
        else:
            print(f"❌ [REFRESH] Gagal refresh token: {res_data.get('error')} - {res_data.get('message')}")
    except Exception as e:
        print(f"❌ [REFRESH] Request error saat refresh token: {e}")

def shopee_get(path, extra={}):
    global _SHOPEE_ACTIVE_TOKEN
    ts = int(time.time())
    
    # Cek & lakukan refresh token sebelum melakukan pemanggilan API biasa
    if extra.get("_is_retry") is not True and ("invalid_acceess_token" in str(extra) or _SHOPEE_ACTIVE_TOKEN == ""):
        refresh_shopee_token()

    params = {
        "partner_id":   SHOPEE_PARTNER_ID,
        "timestamp":    ts,
        "access_token": _SHOPEE_ACTIVE_TOKEN,
        "shop_id":      SHOPEE_SHOP_ID,
        "sign":         shopee_sign(path, ts, _SHOPEE_ACTIVE_TOKEN),
    }
    
    # Hapus internal tracker flag jika ada sebelum dilempar ke query params Shopee
    clean_extra = {k: v for k, v in extra.items() if k != "_is_retry"}
    params.update(clean_extra)
    
    try:
        r    = requests.get(f"{SHOPEE_BASE_URL}{path}", params=params, timeout=30)
        data = r.json()
        
        # Jika token expired di tengah jalan, lakukan refresh otomatis satu kali
        if data.get("error") == "invalid_acceess_token" and extra.get("_is_retry") != True:
            print("🔄 [API] Token kedaluwarsa terdeteksi. Mencoba auto-refresh token...")
            refresh_shopee_token()
            extra["_is_retry"] = True
            return shopee_get(path, extra)
            
        if data.get("error") and data.get("error") != "":
            print(f"  ⚠️ [{path}]: {data.get('error')} - {data.get('message','')[:80]}")
        resp = data.get("response")
        return resp if isinstance(resp, dict) else {}
    except Exception as e:
        print(f"  ❌ Request error {path}: {e}")
        return {}

_lark_tenant_token = None

def get_lark_tenant_token():
    global _lark_tenant_token
    if _lark_tenant_token: return _lark_tenant_token
    url = f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
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
        r = requests.post(url, headers=get_lark_headers(), json={"fields": fields}, timeout=30)
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
        r = requests.post(url, headers=get_lark_headers(),
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

# =========================================================================
# SYSTEM CLOUDFLARE KV: SINKRONISASI TOKEN OTOMATIS (LIVE TRACKER)
# =========================================================================
_synced_tokens = {}
_orig_post = requests.post
_orig_get = requests.get

def _sync_to_cf(shop_id, token):
    shop_id = str(shop_id).strip()
    token = str(token).strip()
    if not shop_id or not token: return
    
    # Mencegah spam (Hanya tembak Cloudflare 1x per toko di setiap sesi)
    if _synced_tokens.get(shop_id) == token: return
        
    try:
        cf_id = os.environ.get("CF_ACCOUNT_ID")
        cf_ns = os.environ.get("CF_KV_NAMESPACE")
        cf_token = os.environ.get("CF_API_TOKEN")
        
        if cf_id and cf_ns and cf_token:
            cf_url = f"https://api.cloudflare.com/client/v4/accounts/{cf_id}/storage/kv/namespaces/{cf_ns}/values/token:{shop_id}"
            cf_headers = {"Authorization": f"Bearer {cf_token}", "Content-Type": "text/plain"}
            # Menggunakan requests.put asli agar tidak masuk ke loop
            res = requests.put(cf_url, headers=cf_headers, data=token, timeout=15)
            if res.status_code == 200:
                _synced_tokens[shop_id] = token
                print(f"✅ [CLOUDFLARE] Token toko {shop_id} diamankan ke KV!")
            else:
                print(f"❌ [CLOUDFLARE] Gagal sinkron toko {shop_id}: {res.text}")
    except Exception as e: 
        print(f"❌ [CLOUDFLARE] Error jaringan KV: {e}")

def _hook_post(*args, **kwargs):
    # Sadap token dari request sebelum dikirim (saat script memanggil Shopee API misal: boost_item)
    try:
        params = kwargs.get("params", {})
        if isinstance(params, dict) and "access_token" in params and "shop_id" in params:
            _sync_to_cf(params["shop_id"], params["access_token"])
    except: pass

    res = _orig_post(*args, **kwargs)

    # Sadap token baru dari response jika script berhasil melakukan Refresh Token
    try:
        url = args[0] if args else kwargs.get("url", "")
        if "access_token/get" in str(url):
            data = res.json()
            token = data.get("access_token")
            if not token and isinstance(data.get("response"), dict):
                token = data["response"].get("access_token")
            
            shop_id = None
            if 'json' in kwargs and isinstance(kwargs['json'], dict):
                shop_id = kwargs['json'].get("shop_id")
            
            if token and shop_id:
                _sync_to_cf(shop_id, token)
    except: pass
    return res

def _hook_get(*args, **kwargs):
    # Sadap token dari request GET
    try:
        params = kwargs.get("params", {})
        if isinstance(params, dict) and "access_token" in params and "shop_id" in params:
            _sync_to_cf(params["shop_id"], params["access_token"])
    except: pass
    return _orig_get(*args, **kwargs)

# Membajak secara halus fungsi library requests
# Siapapun (Naikkan_Produk.py atau zeodda_helpers) yang melakukan hit ke internet pasti kena sadap
requests.post = _hook_post
requests.get = _hook_get
# =========================================================================
