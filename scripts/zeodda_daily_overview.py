import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timedelta

# ============================================================
# CONFIG - SHOPEE PRODUCTION
# ============================================================
SHOPEE_PARTNER_ID   = int(os.environ.get("SHOPEE_PARTNER_ID", "2035358"))
SHOPEE_PARTNER_KEY  = os.environ.get("SHOPEE_PARTNER_KEY", "")
SHOPEE_SHOP_ID      = int(os.environ.get("SHOPEE_SHOP_ID", "963980234"))
SHOPEE_ACCESS_TOKEN = os.environ.get("SHOPEE_ACCESS_TOKEN", "")
SHOPEE_REFRESH_TOKEN = os.environ.get("SHOPEE_REFRESH_TOKEN", "")
SHOPEE_BASE_URL     = "https://partner.shopeemobile.com"

# ============================================================
# CONFIG - LARK BASE
# ============================================================
LARK_APP_ID     = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN  = "ItPfb0MPNaD6KhsVc65lT6p1gTh"
LARK_BASE_URL   = "https://open.larksuite.com"

TABLE_DAILY_OVERVIEW = "tblSVQG08nHr7tXD"
TABLE_ALERT_LOG      = "tblobivbXf5KBsUK"

_lark_tenant_token = None

# ============================================================
# SAFE TYPE HELPERS
# ============================================================
def safe_int(val):
    if val is None or isinstance(val, (dict, list)):
        return 0
    try:
        return int(float(str(val)))
    except Exception:
        return 0

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
# SHOPEE REQUEST HELPERS
# ============================================================
def refresh_shopee_access_token():
    global SHOPEE_ACCESS_TOKEN
    if not SHOPEE_REFRESH_TOKEN:
        return False
    path = "/api/v2/auth/access_token/get"
    ts = int(time.time())
    base_string = f"{str(SHOPEE_PARTNER_ID)}{path}{str(ts)}"
    sign = hmac.new(SHOPEE_PARTNER_KEY.encode('utf-8'), base_string.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f"{SHOPEE_BASE_URL}{path}"
    params = {"partner_id": SHOPEE_PARTNER_ID, "timestamp": ts, "sign": sign}
    payload = {"refresh_token": SHOPEE_REFRESH_TOKEN.strip(), "partner_id": SHOPEE_PARTNER_ID, "shop_id": SHOPEE_SHOP_ID}
    try:
        r = requests.post(url, params=params, json=payload, timeout=30)
        res = r.json()
        if "access_token" in res:
            SHOPEE_ACCESS_TOKEN = res["access_token"]
            return True
        return False
    except Exception:
        return False

def shopee_sign(path, timestamp):
    base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}{SHOPEE_ACCESS_TOKEN}{SHOPEE_SHOP_ID}"
    return hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()

def shopee_get(path, extra={}):
    ts = int(time.time())
    params = {
        "partner_id": SHOPEE_PARTNER_ID,
        "timestamp": ts,
        "access_token": SHOPEE_ACCESS_TOKEN,
        "shop_id": SHOPEE_SHOP_ID,
        "sign": shopee_sign(path, ts),
    }
    params.update(extra)
    try:
        r = requests.get(f"{SHOPEE_BASE_URL}{path}", params=params, timeout=30)
        data = r.json()
        return data.get("response") if isinstance(data.get("response"), dict) else {}
    except Exception:
        return {}

# ============================================================
# LARK BASE ENGINE
# ============================================================
def get_lark_tenant_token() -> str:
    global _lark_tenant_token
    if _lark_tenant_token:
        return _lark_tenant_token
    url = f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
    try:
        r = requests.post(url, json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=30)
        data = r.json()
        _lark_tenant_token = data.get("tenant_access_token")
        return _lark_tenant_token
    except Exception:
        return ""

def get_lark_headers():
    return {"Authorization": f"Bearer {get_lark_tenant_token()}", "Content-Type": "application/json"}

def lark_delete_duplicates(table_id, timestamp_ms, platform_name):
    search_url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/search"
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "Tanggal", "operator": "is", "value": [timestamp_ms]},
                {"field_name": "Platform", "operator": "is", "value": [platform_name]}
            ]
        }
    }
    try:
        r = requests.post(search_url, headers=get_lark_headers(), json=payload, timeout=30)
        res_data = r.json()
        if res_data.get("code") == 0:
            items = res_data.get("data", {}).get("items", [])
            for item in items:
                record_id = item.get("record_id")
                del_url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/{record_id}"
                requests.delete(del_url, headers=get_lark_headers(), timeout=30)
    except Exception:
        pass

def lark_add(table_id, fields):
    if "Tanggal" in fields and "Platform" in fields:
        lark_delete_duplicates(table_id, fields["Tanggal"], fields["Platform"])
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records"
    try:
        r = requests.post(url, headers=get_lark_headers(), json={"fields": fields}, timeout=30)
        return r.json()
    except Exception:
        return {"code": -1}

# ============================================================
# PROCESSING PIPELINE
# ============================================================
def fetch_all_shopee_data():
    refresh_shopee_access_token()
    
    yesterday = datetime.now() - timedelta(days=1)
    date_str_yesterday = yesterday.strftime("%Y-%m-%d")
    
    ts_start_yesterday = int(yesterday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    ts_end_yesterday   = ts_start_yesterday + 86399
    yesterday_ms = int(yesterday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    data = {}
    
    # PERBAIKAN: Mengambil info merchant untuk bypass data scoping follower_count di shop_info
    data["merchant_info"] = shopee_get("/api/v2/merchant/get_merchant_info")
    data["balance"]       = shopee_get("/api/v2/ads/get_total_balance")
    data["shop_perf"]     = shopee_get("/api/v2/account_health/get_shop_performance")
    data["penalty"]       = shopee_get("/api/v2/account_health/get_penalty_point_history")
    data["late_orders"]   = shopee_get("/api/v2/account_health/get_late_orders")
    data["issues"]        = shopee_get("/api/v2/account_health/get_listings_with_issues")
    
    orders_resp = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time", "time_from": ts_start_yesterday, "time_to": ts_end_yesterday, "page_size": 100
    })
    data["orders"] = orders_resp
    
    cancelled_resp = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time", "time_from": ts_start_yesterday, "time_to": ts_end_yesterday, "page_size": 100, "order_status": "CANCELLED"
    })
    data["cancelled_orders"] = cancelled_resp

    data["returns"] = shopee_get("/api/v2/returns/get_return_list", {
        "page_no": 1, "page_size": 100, "create_time_from": ts_start_yesterday, "create_time_to": ts_end_yesterday
    })

    omzet_harian_tanpa_ongkir = 0
    omzet_gross_plus_ongkir = 0
    total_subsidi_shopee = 0
    
    order_list = safe_list(orders_resp, "order_list")
    if order_list:
        order_sn_list = [o.get("order_sn") for o in order_list if o.get("order_sn")]
        
        for i in range(0, len(order_sn_list), 50):
            batch_sn = order_sn_list[i:i+50]
            detail_resp = shopee_get("/api/v2/order/get_order_detail", {
                "order_sn_list": ",".join(batch_sn),
                "response_optional_fields": "total_amount,estimated_shipping_fee,order_status,seller_absorption_co_sub,item_list"
            })
            
            items_detail = safe_list(detail_resp, "order_list")
            for order in items_detail:
                status = order.get("order_status", "")
                if status == "CANCELLED":
                    continue
                
                total_amount = float(order.get("total_amount", 0))
                shipping_fee = float(order.get("estimated_shipping_fee", 0))
                subsidi = float(order.get("seller_absorption_co_sub", 0))
                
                if total_amount == 0 and status == "UNPAID":
                    item_list = safe_list(order, "item_list")
                    item_sum = 0
                    for item in item_list:
                        qty = float(item.get("model_quantity_purchased", 1))
                        price = float(item.get("item_selling_price", 0))
                        item_sum += (price * qty)
                    
                    omzet_harian_tanpa_ongkir += item_sum
                    omzet_gross_plus_ongkir += (item_sum + shipping_fee)
                else:
                    omzet_harian_tanpa_ongkir += (total_amount - shipping_fee)
                    omzet_gross_plus_ongkir += total_amount
                
                total_subsidi_shopee += subsidi

    data["calculated_omzet_harian"] = safe_int(omzet_harian_tanpa_ongkir)
    data["calculated_omzet_gross"] = safe_int(omzet_gross_plus_ongkir)
    data["calculated_subsidi_mp"] = safe_int(total_subsidi_shopee)
    
    return data, yesterday_ms

def input_daily_overview(d, yesterday_ms):
    shop_perf    = safe_dict(d, "shop_perf")
    overall_perf = safe_dict(shop_perf, "overall_performance")
    merchant_info = safe_dict(d, "merchant_info")
    penalty      = safe_dict(d, "penalty")
    late_orders  = safe_dict(d, "late_orders")
    issues       = safe_dict(d, "issues")
    balance      = safe_dict(d, "balance")

    all_orders       = safe_list(d.get("orders", {}), "order_list")
    cancelled_orders = safe_list(d.get("cancelled_orders", {}), "order_list")
    returns_list     = safe_list(d.get("returns", {}), "return_list")

    # Ambil list shop dari merchant info untuk memetakan follower_count gabungan merchant
    auth_shops = safe_list(merchant_info, "auth_shops")
    total_followers = 0
    for shop in auth_shops:
        if shop.get("shop_id") == SHOPEE_SHOP_ID:
            # Jika Shopee melewatkan total_follower di tingkat object toko merchant
            total_followers = safe_int(shop.get("follower_count", 0))

    fields = {
        "Tanggal":                yesterday_ms,
        "Platform":               "Shopee",
        "Total Order Masuk":      safe_int(len(all_orders)),
        "Total Order Dibatalkan": safe_int(len(cancelled_orders)),
        "Total Retur":            safe_int(len(returns_list)),
        "Omzet Harian":           d["calculated_omzet_harian"],
        "Omzet Gross":            d["calculated_omzet_gross"],
        "Subsidi MP":             d["calculated_subsidi_mp"],
        "Follower Toko":          total_followers,
        "Skor Performa Toko":     safe_int(overall_perf.get("rating", 0)),
        "Poin Penalti":           safe_int(penalty.get("total_penalty_point", 0)),
        "Order Terlambat":        safe_int(late_orders.get("total_count", 0)),
        "Produk Bermasalah":      safe_int(issues.get("total_count", 0)),
        "Saldo Iklan":            safe_int(balance.get("total_balance", 0)),
    }
    lark_add(TABLE_DAILY_OVERVIEW, fields)

def main():
    if not LARK_APP_ID or not LARK_APP_SECRET:
        return
    shopee_data, target_date_ms = fetch_all_shopee_data()
    input_daily_overview(shopee_data, target_date_ms)

if __name__ == "__main__":
    main()
