"""
zeodda_helpers.py
Shared utilities untuk semua Zeodda automation scripts.
Import: from zeodda_helpers import *
"""

import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timedelta

# ============================================================
# CONFIG - SHOPEE
# ============================================================

SHOPEE_PARTNER_ID   = int(os.environ.get("SHOPEE_PARTNER_ID", "2035358"))
SHOPEE_PARTNER_KEY  = os.environ.get("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_SHOP_ID      = int(os.environ.get("SHOPEE_SHOP_ID", "963980234"))
SHOPEE_ACCESS_TOKEN = os.environ.get("SHOPEE_ACCESS_TOKEN", "").strip()
SHOPEE_BASE_URL     = "https://partner.shopeemobile.com"

# ============================================================
# CONFIG - LARK
# ============================================================

LARK_APP_ID     = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN  = "ItPfb0MPNaD6KhsVc65lT6p1gTh"
LARK_BASE_URL   = "https://open.larksuite.com"

# Table IDs
TABLE_DAILY_OVERVIEW = "tblSVQG08nHr7tXD"
TABLE_PRODUCT_PERF   = "tblRlDzWXK5gQXzT"
TABLE_ADS_SHOP       = "tbl6EhWSzZumBR4L"
TABLE_ADS_PRODUCT    = "tbl3r112gUTEhHCe"
TABLE_KOMPARASI      = "tblZoIIwUj0RN93p"
TABLE_FINANCIAL      = "tblLh7liZZxPzEpl"
TABLE_ALERT_LOG      = "tblobivbXf5KBsUK"

# ============================================================
# SAFE TYPE HELPERS
# ============================================================

def safe_int(val):
    if val is None:
        return 0
    if isinstance(val, (dict, list)):
        return 0
    try:
        return int(float(str(val)))
    except:
        return 0

def safe_str(val):
    if val is None or isinstance(val, (dict, list)):
        return ""
    return str(val)

def safe_dict(d, key):
    if not isinstance(d, dict):
        return {}
    v = d.get(key, {})
    return v if isinstance(v, dict) else {}

def safe_list(d, key):
    if not isinstance(d, dict):
        return []
    v = d.get(key, [])
    return v if isinstance(v, list) else []

# ============================================================
# TANGGAL HELPERS
# ============================================================

def get_yesterday_range():
    """
    Return dict berisi semua format tanggal kemarin yang dibutuhkan API.
    Script jalan jam 00:00 WIB → ambil data H-1.
    """
    now_wib       = datetime.utcnow() + timedelta(hours=7)
    yesterday_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    return {
        "yesterday_ms":  int(yesterday_wib.timestamp() * 1000),       # Lark timestamp
        "date_str":      yesterday_wib.strftime("%Y-%m-%d"),           # YYYY-MM-DD (Payment API)
        "date_str_dmy":  yesterday_wib.strftime("%d-%m-%Y"),           # DD-MM-YYYY (Ads API)
        "ts_start":      int((yesterday_wib - timedelta(hours=7)).timestamp()),
        "ts_end":        int((yesterday_wib + timedelta(hours=17) - timedelta(seconds=1)).timestamp()),
        "label":         yesterday_wib.strftime("%Y-%m-%d"),
    }

# ============================================================
# SHOPEE HELPERS
# ============================================================

def shopee_sign(path, timestamp):
    base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}{SHOPEE_ACCESS_TOKEN}{SHOPEE_SHOP_ID}"
    return hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()

def shopee_get(path, extra={}):
    ts = int(time.time())
    params = {
        "partner_id":   SHOPEE_PARTNER_ID,
        "timestamp":    ts,
        "access_token": SHOPEE_ACCESS_TOKEN,
        "shop_id":      SHOPEE_SHOP_ID,
        "sign":         shopee_sign(path, ts),
    }
    params.update(extra)
    try:
        r    = requests.get(f"{SHOPEE_BASE_URL}{path}", params=params, timeout=30)
        data = r.json()
        if data.get("error") and data.get("error") != "":
            print(f"  ⚠️ [{path}]: {data.get('error')} - {data.get('message','')[:80]}")
        resp = data.get("response")
        return resp if isinstance(resp, dict) else {}
    except Exception as e:
        print(f"  ❌ Request error {path}: {e}")
        return {}

# ============================================================
# LARK HELPERS
# ============================================================

_lark_tenant_token = None

def get_lark_tenant_token() -> str:
    global _lark_tenant_token
    if _lark_tenant_token:
        return _lark_tenant_token
    url = f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
    try:
        r    = requests.post(url, json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=30)
        data = r.json()
        if data.get("code") != 0:
            raise Exception(f"code={data.get('code')} msg={data.get('msg')}")
        _lark_tenant_token = data["tenant_access_token"]
        print("✅ Lark token OK")
        return _lark_tenant_token
    except Exception as e:
        raise Exception(f"❌ Lark token error: {e}")

def get_lark_headers():
    return {
        "Authorization": f"Bearer {get_lark_tenant_token()}",
        "Content-Type":  "application/json",
    }

def lark_add(table_id, fields):
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records"
    try:
        r      = requests.post(url, headers=get_lark_headers(), json={"fields": fields}, timeout=30)
        result = r.json()
        if result.get("code") != 0:
            print(f"  ❌ Lark error {result.get('code')}: {result.get('msg')}")
            print(f"     Fields: {fields}")
        return result
    except Exception as e:
        print(f"  ❌ Lark request error: {e}")
        return {"code": -1}

def lark_add_batch(table_id, records_list):
    if not records_list:
        return {"code": 0}
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/batch_create"
    try:
        r      = requests.post(url, headers=get_lark_headers(),
                     json={"records": [{"fields": f} for f in records_list]}, timeout=30)
        result = r.json()
        if result.get("code") != 0:
            print(f"  ❌ Lark batch error {result.get('code')}: {result.get('msg')}")
            print(f"     Sample: {records_list[0]}")
        return result
    except Exception as e:
        print(f"  ❌ Lark batch error: {e}")
        return {"code": -1}

def lark_init():
    """Wajib dipanggil di awal setiap script."""
    if not LARK_APP_ID or not LARK_APP_SECRET:
        raise Exception("❌ LARK_APP_ID atau LARK_APP_SECRET tidak ada!")
    get_lark_tenant_token()
