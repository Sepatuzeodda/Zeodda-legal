import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timedelta

# ============================================================
# CONFIG - SHOPEE PRODUCTION
# ============================================================
SHOPEE_PARTNER_ID    = int(os.environ.get("SHOPEE_PARTNER_ID", "2035358"))
SHOPEE_PARTNER_KEY   = os.environ.get("SHOPEE_PARTNER_KEY", "")
SHOPEE_SHOP_ID       = int(os.environ.get("SHOPEE_SHOP_ID", "963980234"))
SHOPEE_ACCESS_TOKEN  = os.environ.get("SHOPEE_ACCESS_TOKEN", "")
SHOPEE_REFRESH_TOKEN = os.environ.get("SHOPEE_REFRESH_TOKEN", "")
SHOPEE_BASE_URL      = "https://partner.shopeemobile.com"

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

def safe_float(val):
    if val is None or isinstance(val, (dict, list)):
        return 0.0
    try:
        return float(str(val))
    except Exception:
        return 0.0

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
        print("⚠️ SHOPEE_REFRESH_TOKEN kosong, skip refresh.")
        return False
    path = "/api/v2/auth/access_token/get"
    ts = int(time.time())
    base_string = f"{str(SHOPEE_PARTNER_ID)}{path}{str(ts)}"
    sign = hmac.new(SHOPEE_PARTNER_KEY.encode('utf-8'), base_string.encode('utf-8'), hashlib.sha256).hexdigest()
    url     = f"{SHOPEE_BASE_URL}{path}"
    params  = {"partner_id": SHOPEE_PARTNER_ID, "timestamp": ts, "sign": sign}
    payload = {"refresh_token": SHOPEE_REFRESH_TOKEN.strip(), "partner_id": SHOPEE_PARTNER_ID, "shop_id": SHOPEE_SHOP_ID}
    try:
        r   = requests.post(url, params=params, json=payload, timeout=30)
        res = r.json()
        if "access_token" in res:
            SHOPEE_ACCESS_TOKEN = res["access_token"]
            print("🔄 Access token refreshed OK")
            return True
        print(f"❌ Refresh token gagal: {res}")
        return False
    except Exception as e:
        print(f"❌ Refresh token error: {e}")
        return False

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
            print(f"  ⚠️ [{path}] error: {data.get('error')} - {data.get('message','')[:80]}")
        return data.get("response") if isinstance(data.get("response"), dict) else {}
    except Exception as e:
        print(f"  ❌ Request error {path}: {e}")
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
        r    = requests.post(url, json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=30)
        data = r.json()
        _lark_tenant_token = data.get("tenant_access_token")
        print("✅ Lark token OK")
        return _lark_tenant_token
    except Exception as e:
        print(f"❌ Lark token error: {e}")
        return ""

def get_lark_headers():
    return {"Authorization": f"Bearer {get_lark_tenant_token()}", "Content-Type": "application/json"}

def lark_get_fields(table_id):
    """Print semua nama field di tabel Lark untuk debug."""
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/fields"
    try:
        r    = requests.get(url, headers=get_lark_headers(), timeout=30)
        data = r.json()
        if data.get("code") == 0:
            fields = data.get("data", {}).get("items", [])
            print(f"\n📋 Field di tabel Lark ({len(fields)} field):")
            for f in fields:
                print(f"   '{f.get('field_name')}' — type={f.get('type')}")
        else:
            print(f"  ❌ get_fields error: {data.get('code')} {data.get('msg')}")
    except Exception as e:
        print(f"  ❌ get_fields error: {e}")

def lark_delete_duplicates(table_id, date_str, platform_name):
    """
    Hapus duplikat pakai filter text pada field Tanggal (date string YYYY-MM-DD)
    bukan timestamp ms — lebih kompatibel dengan berbagai tipe field Lark.
    """
    search_url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/search"
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "Platform", "operator": "is", "value": [platform_name]}
            ]
        }
    }
    try:
        r        = requests.post(search_url, headers=get_lark_headers(), json=payload, timeout=30)
        res_data = r.json()
        if res_data.get("code") == 0:
            items = res_data.get("data", {}).get("items", [])
            deleted = 0
            for item in items:
                # Cek apakah tanggal record match dengan date_str
                tanggal_val = item.get("fields", {}).get("Tanggal")
                # Lark Date field return timestamp ms — convert ke date string
                if tanggal_val:
                    try:
                        record_date = datetime.utcfromtimestamp(tanggal_val / 1000).strftime("%Y-%m-%d")
                        if record_date == date_str:
                            record_id = item.get("record_id")
                            del_url   = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/{record_id}"
                            dr        = requests.delete(del_url, headers=get_lark_headers(), timeout=30)
                            print(f"  🗑️  Hapus duplikat {record_id} ({record_date}): code={dr.json().get('code')}")
                            deleted += 1
                    except Exception:
                        pass
            if deleted == 0:
                print(f"  ✅ Tidak ada duplikat untuk {date_str}")
        else:
            print(f"  ⚠️ Search duplikat gagal: {res_data.get('code')} {res_data.get('msg')}")
    except Exception as e:
        print(f"  ❌ lark_delete_duplicates error: {e}")

def lark_add(table_id, fields, date_str):
    lark_delete_duplicates(table_id, date_str, fields.get("Platform", "Shopee"))
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records"
    try:
        r      = requests.post(url, headers=get_lark_headers(), json={"fields": fields}, timeout=30)
        result = r.json()
        if result.get("code") != 0:
            print(f"  ❌ Lark add error {result.get('code')}: {result.get('msg')}")
            print(f"  📄 Full response: {result}")
        else:
            print("  ✅ Lark record added OK")
        return result
    except Exception as e:
        print(f"  ❌ Lark add error: {e}")
        return {"code": -1}

# ============================================================
# PROCESSING PIPELINE
# ============================================================
def fetch_all_shopee_data():
    refresh_shopee_access_token()

    now_wib       = datetime.utcnow() + timedelta(hours=7)
    yesterday_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    ts_start_yesterday = int((yesterday_wib - timedelta(hours=7)).timestamp())
    ts_end_yesterday   = ts_start_yesterday + 86399
    yesterday_ms       = int(yesterday_wib.timestamp() * 1000)
    date_str           = yesterday_wib.strftime("%Y-%m-%d")

    print(f"📅 Tanggal target : {date_str} WIB")
    print(f"⏱️  ts_start={ts_start_yesterday} | ts_end={ts_end_yesterday}")

    data = {}
    data["date_str"]      = date_str
    data["yesterday_ms"]  = yesterday_ms
    data["balance"]       = shopee_get("/api/v2/ads/get_total_balance")
    data["shop_perf"]     = shopee_get("/api/v2/account_health/get_shop_performance")
    data["penalty"]       = shopee_get("/api/v2/account_health/get_penalty_point_history")
    data["late_orders"]   = shopee_get("/api/v2/account_health/get_late_orders")
    data["issues"]        = shopee_get("/api/v2/account_health/get_listings_with_issues")

    orders_resp = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from":        ts_start_yesterday,
        "time_to":          ts_end_yesterday,
        "page_size":        100,
    })
    data["orders"] = orders_resp

    cancelled_resp = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from":        ts_start_yesterday,
        "time_to":          ts_end_yesterday,
        "page_size":        100,
        "order_status":     "CANCELLED",
    })
    data["cancelled_orders"] = cancelled_resp

    data["returns"] = shopee_get("/api/v2/returns/get_return_list", {
        "page_no":          1,
        "page_size":        100,
        "create_time_from": ts_start_yesterday,
        "create_time_to":   ts_end_yesterday,
    })

    omzet_harian  = 0.0
    omzet_gross   = 0.0
    total_subsidi = 0.0

    order_list = safe_list(orders_resp, "order_list")
    print(f"\n📦 Total order ditemukan: {len(order_list)}")

    if order_list:
        order_sn_list = [o.get("order_sn") for o in order_list if o.get("order_sn")]

        for i in range(0, len(order_sn_list), 50):
            batch_sn    = order_sn_list[i:i+50]
            detail_resp = shopee_get("/api/v2/order/get_order_detail", {
                "order_sn_list":            ",".join(batch_sn),
                "response_optional_fields": "total_amount,estimated_shipping_fee,order_status,item_list",
            })

            for order in safe_list(detail_resp, "order_list"):
                sn           = order.get("order_sn", "")
                status       = order.get("order_status", "")
                total_amount = safe_float(order.get("total_amount", 0))
                shipping_fee = safe_float(order.get("estimated_shipping_fee", 0))

                if status == "CANCELLED":
                    print(f"   ⏭️  Skip CANCELLED: {sn}")
                    continue

                if total_amount == 0 and status == "UNPAID":
                    item_sum = sum(
                        safe_float(item.get("model_discounted_price", 0)) *
                        safe_float(item.get("model_quantity_purchased", 1))
                        for item in safe_list(order, "item_list")
                    )
                    omzet_harian += item_sum
                    omzet_gross  += item_sum + shipping_fee
                    print(f"   📝 UNPAID {sn}: item_sum={item_sum:.0f} ongkir={shipping_fee:.0f}")
                else:
                    omzet_harian += total_amount - shipping_fee
                    omzet_gross  += total_amount
                    print(f"   ✅ {status} {sn}: total={total_amount:.0f} ongkir={shipping_fee:.0f} harian+={total_amount - shipping_fee:.0f}")

                escrow       = shopee_get("/api/v2/payment/get_escrow_detail", {"order_sn": sn})
                order_income = safe_dict(escrow, "order_income")
                subsidi      = (
                    safe_float(order_income.get("shopee_discount", 0)) +
                    safe_float(order_income.get("voucher_from_shopee", 0)) +
                    safe_float(order_income.get("coins", 0))
                )
                total_subsidi += subsidi
                if subsidi > 0:
                    print(f"   💰 Subsidi {sn}: Rp {subsidi:.0f}")

    print(f"\n💵 Omzet Harian  : Rp {omzet_harian:,.0f}")
    print(f"💵 Omzet Gross   : Rp {omzet_gross:,.0f}")
    print(f"🎁 Total Subsidi : Rp {total_subsidi:,.0f}")

    data["calculated_omzet_harian"] = safe_int(omzet_harian)
    data["calculated_omzet_gross"]  = safe_int(omzet_gross)
    data["calculated_subsidi_mp"]   = safe_int(total_subsidi)

    return data


def input_daily_overview(d):
    shop_perf    = safe_dict(d, "shop_perf")
    overall_perf = safe_dict(shop_perf, "overall_performance")
    penalty      = safe_dict(d, "penalty")
    late_orders  = safe_dict(d, "late_orders")
    issues       = safe_dict(d, "issues")
    balance      = safe_dict(d, "balance")

    all_orders       = safe_list(d.get("orders", {}), "order_list")
    cancelled_orders = safe_list(d.get("cancelled_orders", {}), "order_list")
    returns_list     = safe_list(d.get("returns", {}), "return_list")

    fields = {
        "Tanggal":                d["yesterday_ms"],
        "Platform":               "Shopee",
        "Total Order Masuk":      safe_int(len(all_orders)),
        "Total Order Dibatalkan": safe_int(len(cancelled_orders)),
        "Total Retur":            safe_int(len(returns_list)),
        "Omzet Harian":           d["calculated_omzet_harian"],
        "Omzet Gross":            d["calculated_omzet_gross"],
        "Subsidi MP":             d["calculated_subsidi_mp"],
        "Follower Toko":          0,
        "Skor Performa Toko":     safe_int(overall_perf.get("rating", 0)),
        "Poin Penalti":           safe_int(penalty.get("total_penalty_point", 0)),
        "Order Terlambat":        safe_int(late_orders.get("total_count", 0)),
        "Produk Bermasalah":      safe_int(issues.get("total_count", 0)),
        "Saldo Iklan":            safe_int(balance.get("total_balance", 0)),
    }

    print(f"\n📊 Fields yang akan di-push ke Lark:")
    for k, v in fields.items():
        print(f"   '{k}': {v}")

    # Print semua field yang ada di Lark dulu untuk debug
    lark_get_fields(TABLE_DAILY_OVERVIEW)

    lark_add(TABLE_DAILY_OVERVIEW, fields, d["date_str"])


def main():
    if not LARK_APP_ID or not LARK_APP_SECRET:
        print("❌ LARK_APP_ID atau LARK_APP_SECRET tidak ada!")
        return
    shopee_data = fetch_all_shopee_data()
    input_daily_overview(shopee_data)
    print("\n✅ Daily Overview selesai.")

if __name__ == "__main__":
    main()
