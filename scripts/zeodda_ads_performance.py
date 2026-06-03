import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timedelta, timezone

# Konfigurasi Kredensial Otomatis dari GitHub Secrets
SHOPEE_PARTNER_ID      = int(os.environ.get("SHOPEE_PARTNER_ID") or "2035358")
SHOPEE_PARTNER_KEY     = os.environ.get("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_BASE_URL        = "https://partner.shopeemobile.com"
LARK_APP_ID            = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET        = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN         = "ItPfb0MPNaD6KhsVc65lT6p1gTh"
LARK_BASE_URL          = "https://open.larksuite.com"

# ID Tabel Resmi Lark Base Zeodda
TABLE_GMS_CONTROL      = "tbl28sCpu1ZtR73l"      # Ads Control
TABLE_ADS_PERFORMANCE  = "tblx5PwfnB8Oi7lf"      # Performa Ads

_GLOBAL_REFRESH_TOKEN  = os.environ.get("SHOPEE_REFRESH_TOKEN", "").strip()
_lark_token            = None

def get_lark_token():
    global _lark_token
    if _lark_token: return _lark_token
    r = requests.post(f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal", 
                      json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=30)
    _lark_token = r.json().get("tenant_access_token")
    return _lark_token

def lark_headers():
    return {"Authorization": f"Bearer {get_lark_token()}", "Content-Type": "application/json"}

def parse_text(val):
    if isinstance(val, list) and val: return str(val[0].get("text", "")).strip()
    return str(val).strip() if val else ""

def get_active_token_for_shop(shop_id):
    global _GLOBAL_REFRESH_TOKEN
    env_key       = f"SHOPEE_REFRESH_TOKEN_{shop_id}"
    local_refresh = os.environ.get(env_key, "").strip() or _GLOBAL_REFRESH_TOKEN
    if not local_refresh: return None

    path = "/api/v2/auth/access_token/get"
    ts   = int(time.time())
    sign = hmac.new(SHOPEE_PARTNER_KEY.encode(), f"{SHOPEE_PARTNER_ID}{path}{ts}".encode(), hashlib.sha256).hexdigest()
    try:
        r = requests.post(f"{SHOPEE_BASE_URL}{path}", 
                          params={"partner_id": SHOPEE_PARTNER_ID, "timestamp": ts, "sign": sign},
                          json={"refresh_token": local_refresh, "partner_id": SHOPEE_PARTNER_ID, "shop_id": int(shop_id)}, timeout=30)
        res = r.json()
        return res.get("access_token")
    except:
        return None

def shopee_get(path, shop_id, access_token, extra={}):
    ts   = int(time.time())
    base = f"{SHOPEE_PARTNER_ID}{path}{ts}{access_token}{shop_id}"
    sign = hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()
    params = {"partner_id": SHOPEE_PARTNER_ID, "timestamp": ts, "access_token": access_token, "shop_id": int(shop_id), "sign": sign}
    params.update(extra)
    try:
        r = requests.get(f"{SHOPEE_BASE_URL}{path}", params=params, timeout=30)
        data = r.json()
        if data.get("error") and data.get("error") != "": return None
        return data.get("response", {})
    except:
        return None

def get_target_roas_from_lark():
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_GMS_CONTROL}/records/search"
    payload = {"filter": {"conjunction": "and", "conditions": [{"field_name": "Status Sync", "operator": "is", "value": ["Success"]}]}}
    mapping = {}
    try:
        r = requests.post(url, headers=lark_headers(), json=payload, timeout=30)
        items = r.json().get("data", {}).get("items", [])
        for item in items:
            fields = item.get("fields", {})
            prod_id = parse_text(fields.get("ID Produk"))
            roas_target = fields.get("ROAS Target")
            if prod_id and roas_target is not None:
                mapping[prod_id] = float(roas_target)
        return mapping
    except:
        return {}

def batch_push_to_lark(records):
    if not records: return
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_ADS_PERFORMANCE}/records/batch_create"
    try:
        requests.post(url, headers=lark_headers(), json={"records": records}, timeout=30)
    except:
        pass

def pull_shop_ads_with_target(shop_id, target_mapping):
    token = get_active_token_for_shop(shop_id)
    if not token: return

    item_resp = shopee_get("/api/v2/product/get_item_list", shop_id, token, {"page_size": 50, "item_status": "NORMAL"})
    if not item_resp: return
    items = item_resp.get("item", [])
    if not items: return

    kemarin = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    lark_records = []
