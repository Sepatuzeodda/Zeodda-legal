import hmac
import hashlib
import time
import requests
import os
from datetime import datetime

SHOPEE_PARTNER_ID   = int(os.environ.get("SHOPEE_PARTNER_ID", "1234324"))
SHOPEE_PARTNER_KEY  = os.environ.get("SHOPEE_PARTNER_KEY", "")
SHOPEE_SHOP_ID      = int(os.environ.get("SHOPEE_SHOP_ID", "963980234"))
SHOPEE_ACCESS_TOKEN = os.environ.get("SHOPEE_ACCESS_TOKEN", "")
SHOPEE_BASE_URL     = "https://openplatform.sandbox.test-stable.shopee.sg"
# SHOPEE_BASE_URL = "https://partner.shopeemobile.com"  # Production

LARK_USER_TOKEN = os.environ.get("LARK_USER_TOKEN", "")
LARK_APP_TOKEN  = "Nql3bfZtqaNABdslc1jlYFRqgCc"
LARK_BASE_URL   = "https://open.larksuite.com"

TABLE_DAILY_OVERVIEW = "tblOIk5Rv5wTrbOM"
TABLE_PRODUCT_PERF   = "tbl1TS2Hk26v5HB1"
TABLE_ADS_SHOP       = "tblxgI3Ia1YmCR6L"
TABLE_ADS_PRODUCT    = "tblpy5kqHrSPaoxk"
TABLE_KOMPARASI      = "tbljsQISLBtRDkeh"
TABLE_SOCIAL_MEDIA   = "tbllk68BO9607IO4"
TABLE_FINANCIAL      = "tbl2Or8DO3wywwxn"
TABLE_ALERT_LOG      = "tblCutzEM4Bp0DmN"

# ============================================================
# SAFE TYPE HELPERS
# ============================================================

def safe_int(val):
    """Semua field angka di Lark = Number Thousands separator → harus int"""
    if val is None:
        return 0
    if isinstance(val, (dict, list)):
        print(f"  ⚠️ safe_int got {type(val).__name__}: {repr(val)[:80]}")
        return 0
    try:
        return int(float(str(val)))
    except Exception as e:
        print(f"  ⚠️ safe_int conversion error: {repr(val)} → {e}")
        return 0

def safe_str(val):
    if val is None or isinstance(val, (dict, list)):
        return ""
    return str(val)

def safe_dict(d, key):
    """Get a sub-dict safely, always returns dict"""
    if not isinstance(d, dict):
        return {}
    v = d.get(key, {})
    return v if isinstance(v, dict) else {}

def safe_list(d, key):
    """Get a list from dict safely, always returns list"""
    if not isinstance(d, dict):
        return []
    v = d.get(key, [])
    return v if isinstance(v, list) else []

# ============================================================
# SHOPEE HELPERS
# ============================================================

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
        resp = data.get("response")
        return resp if isinstance(resp, dict) else {}
    except Exception as e:
        print(f"❌ Request error {path}: {e}")
        return {}

# ============================================================
# LARK HELPERS
# ============================================================

def get_lark_headers():
    if not LARK_USER_TOKEN:
        raise Exception("LARK_USER_TOKEN tidak ditemukan!")
    return {
        "Authorization": f"Bearer {LARK_USER_TOKEN}",
        "Content-Type": "application/json",
    }

def lark_add(table_id, fields):
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records"
    try:
        r = requests.post(url, headers=get_lark_headers(), json={"fields": fields}, timeout=30)
        result = r.json()
        if result.get("code") != 0:
            print(f"❌ Lark error {result.get('code')}: {result.get('msg')}")
            print(f"🔍 Fields dikirim: {fields}")
        return result
    except Exception as e:
        print(f"❌ Lark request error: {e}")
        return {"code": -1}

def lark_add_batch(table_id, records_list):
    if not records_list:
        return {"code": 0}
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/batch_create"
    try:
        r = requests.post(url, headers=get_lark_headers(),
            json={"records": [{"fields": f} for f in records_list]}, timeout=30)
        result = r.json()
        if result.get("code") != 0:
            print(f"❌ Lark batch error {result.get('code')}: {result.get('msg')}")
            print(f"🔍 Sample: {records_list[0]}")
        return result
    except Exception as e:
        print(f"❌ Lark batch error: {e}")
        return {"code": -1}

# ============================================================
# AMBIL DATA SHOPEE
# ============================================================

def fetch_all_shopee_data():
    print("📥 Mengambil semua data Shopee...")
    today    = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
    now      = int(time.time())
    date_str = datetime.now().strftime("%Y-%m-%d")

    data = {}
    data["shop_info"]        = shopee_get("/api/v2/shop/get_shop_info")
    data["shop_perf"]        = shopee_get("/api/v2/account_health/get_shop_performance")
    data["orders"]           = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time", "time_from": today,
        "time_to": now, "page_size": 100,
    })
    data["cancelled_orders"] = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time", "time_from": today,
        "time_to": now, "page_size": 100, "order_status": "CANCELLED",
    })
    data["returns"]          = shopee_get("/api/v2/returns/get_return_list", {
        "page_no": 1, "page_size": 100,
        "create_time_from": today, "create_time_to": now,
    })
    data["income"]           = shopee_get("/api/v2/payment/get_income_overview", {
        "start_date": date_str, "end_date": date_str,
    })
    data["balance"]          = shopee_get("/api/v2/ads/get_total_balance")
    data["penalty"]          = shopee_get("/api/v2/account_health/get_penalty_point_history")
    data["late_orders"]      = shopee_get("/api/v2/account_health/get_late_orders")
    data["issues"]           = shopee_get("/api/v2/account_health/get_listings_with_issues")
    data["ads"]              = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {
        "start_date": date_str, "end_date": date_str,
    })
    items_resp               = shopee_get("/api/v2/product/get_item_list", {
        "offset": 0, "page_size": 50, "item_status": "NORMAL",
    })
    data["items"] = items_resp.get("item", []) if isinstance(items_resp, dict) else []

    # DEBUG: print raw responses untuk diagnosa
    print("🔍 RAW income:", repr(data["income"])[:120])
    print("🔍 RAW balance:", repr(data["balance"])[:120])
    print("🔍 RAW shop_info keys:", list(data["shop_info"].keys()) if isinstance(data["shop_info"], dict) else repr(data["shop_info"])[:80])

    print("✅ Data Shopee berhasil diambil!")
    return data

# ============================================================
# INPUT KE LARK BASE
# ============================================================

def input_daily_overview(d):
    print("📋 Input Daily Overview...")
    today_ms = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp() * 1000)

    # Akses semua sub-dict dengan safe_dict agar tidak crash kalau None/list
    shop_perf    = safe_dict(d, "shop_perf")
    overall_perf = safe_dict(shop_perf, "overall_performance")
    income       = safe_dict(d, "income")
    shop_info    = safe_dict(d, "shop_info")
    penalty      = safe_dict(d, "penalty")
    late_orders  = safe_dict(d, "late_orders")
    issues       = safe_dict(d, "issues")
    balance      = safe_dict(d, "balance")

    all_orders       = safe_list(d.get("orders", {}),           "order_list")
    cancelled_orders = safe_list(d.get("cancelled_orders", {}), "order_list")
    returns_list     = safe_list(d.get("returns", {}),          "return_list")

    fields = {
        "Tanggal":                today_ms,
        "Platform":               "Shopee",
        "Total Order Masuk":      safe_int(len(all_orders)),
        "Total Order Dibatalkan": safe_int(len(cancelled_orders)),
        "Total Retur":            safe_int(len(returns_list)),
        "Omzet Harian":           safe_int((income.get("total_income") or {}).get("released_amount", 0)),
        "Follower Toko":          safe_int(shop_info.get("follower_count", 0)),
        "Skor Performa Toko":     safe_int(overall_perf.get("rating", 0)),
        "Poin Penalti":           safe_int(penalty.get("total_penalty_point", 0)),
        "Order Terlambat":        safe_int(late_orders.get("total_count", 0)),
        "Produk Bermasalah":      safe_int(issues.get("total_count", 0)),
        "Saldo Iklan":            safe_int(balance.get("total_balance", 0)),
    }

    print("🔍 DEBUG Daily Overview fields:")
    for k, v in fields.items():
        print(f"   {k}: {repr(v)} ({type(v).__name__})")

    result = lark_add(TABLE_DAILY_OVERVIEW, fields)
    print("✅ Daily Overview done!" if result.get("code") == 0 else "❌ Gagal")

def input_product_performance(items):
    print("⭐ Input Product Performance...")
    if not items:
        print("⚠️ Tidak ada produk di sandbox, skip.")
        return

    today_ms = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp() * 1000)
    records = []

    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id")
        comment_resp = shopee_get("/api/v2/product/get_comment", {
            "item_id": item_id, "cursor": "", "page_size": 100,
        })
        comments = comment_resp.get("comment_list", [])
        if not isinstance(comments, list):
            comments = []

        star = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for c in comments:
            if isinstance(c, dict):
                rv = safe_int(c.get("rating_star", 0))
                if rv in star:
                    star[rv] += 1

        avg = sum(k * v for k, v in star.items()) // len(comments) if comments else 0

        records.append({
            "Tanggal":             today_ms,
            "Platform":            "Shopee",
            "Nama Produk":         safe_str(item.get("item_name", "")),
            "Item ID":             safe_str(item_id),
            "Rating Bintang":      safe_int(avg),
            "Total Review":        safe_int(len(comments)),
            "Review Bintang 5":    safe_int(star[5]),
            "Review Bintang 4":    safe_int(star[4]),
            "Review Bintang 3":    safe_int(star[3]),
            "Review Bintang 2":    safe_int(star[2]),
            "Review Bintang 1":    safe_int(star[1]),
            "Review Negatif Baru": safe_int(star[1] + star[2]),
        })

    if records:
        result = lark_add_batch(TABLE_PRODUCT_PERF, records)
        print(f"✅ Product Performance {len(records)} produk!" if result.get("code") == 0 else "❌ Gagal")

def input_ads_shop(d):
    print("📢 Input Ads Shop Level...")
    today_ms = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp() * 1000)
    ads     = safe_dict(d, "ads")
    balance = safe_dict(d, "balance")

    fields = {
        "Tanggal":                today_ms,
        "Platform":               "Shopee",
        "Saldo Iklan":            safe_int(balance.get("total_balance", 0)),
        "Total Spend":            safe_int(ads.get("cost", 0)),
        "Total Impresi":          safe_int(ads.get("impression", 0)),
        "Total Klik":             safe_int(ads.get("click", 0)),
        "Total Order dari Iklan": safe_int(ads.get("order", 0)),
        "Revenue dari Iklan":     safe_int(ads.get("order_amount", 0)),
    }
    result = lark_add(TABLE_ADS_SHOP, fields)
    print("✅ Ads Shop Level done!" if result.get("code") == 0 else "❌ Gagal")

def input_financial(d):
    print("💰 Input Financial Summary...")
    today_ms = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp() * 1000)
    income  = safe_dict(d, "income")
    ads     = safe_dict(d, "ads")

    fields = {
        "Tanggal":        today_ms,
        "Platform":       "Shopee",
        "Gross Revenue":  safe_int((income.get("total_income") or {}).get("released_amount", 0)),
        "Biaya Platform": safe_int((income.get("escrow_amount") or {}).get("released_amount", 0)),
        "Spend Iklan":    safe_int(ads.get("cost", 0)),
    }
    result = lark_add(TABLE_FINANCIAL, fields)
    print("✅ Financial Summary done!" if result.get("code") == 0 else "❌ Gagal")

def input_alerts(d):
    print("🚨 Cek dan input Alert Log...")
    today_ms = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp() * 1000)
    balance  = safe_dict(d, "balance")
    penalty  = safe_dict(d, "penalty")
    issues   = safe_dict(d, "issues")
    late     = safe_dict(d, "late_orders")
    alerts   = []

    saldo = safe_int(balance.get("total_balance", 0))
    if saldo < 100000:
        alerts.append({
            "Tanggal": today_ms, "Platform": "Shopee",
            "Tipe Alert": "Iklan Hampir Habis",
            "Detail": f"Saldo iklan Rp {saldo:,} — segera top up!",
            "Nilai Saat Ini": saldo, "Nilai Normal": 100000,
            "Prioritas": "🔴 Kritis", "Status": "Baru",
        })

    pen = safe_int(penalty.get("total_penalty_point", 0))
    if pen > 0:
        alerts.append({
            "Tanggal": today_ms, "Platform": "Shopee",
            "Tipe Alert": "Penalti",
            "Detail": f"Toko dapat {pen} poin penalti!",
            "Nilai Saat Ini": pen, "Nilai Normal": 0,
            "Prioritas": "🔴 Kritis", "Status": "Baru",
        })

    isu = safe_int(issues.get("total_count", 0))
    if isu > 0:
        alerts.append({
            "Tanggal": today_ms, "Platform": "Shopee",
            "Tipe Alert": "Produk Bermasalah",
            "Detail": f"{isu} produk bermasalah.",
            "Nilai Saat Ini": isu, "Nilai Normal": 0,
            "Prioritas": "🟡 Penting", "Status": "Baru",
        })

    terlambat = safe_int(late.get("total_count", 0))
    if terlambat > 5:
        alerts.append({
            "Tanggal": today_ms, "Platform": "Shopee",
            "Tipe Alert": "Order Terlambat",
            "Detail": f"{terlambat} order terlambat.",
            "Nilai Saat Ini": terlambat, "Nilai Normal": 5,
            "Prioritas": "🟡 Penting", "Status": "Baru",
        })

    if alerts:
        result = lark_add_batch(TABLE_ALERT_LOG, alerts)
        print(f"✅ {len(alerts)} alert dibuat!" if result.get("code") == 0 else "❌ Gagal")
    else:
        print("✅ Tidak ada alert hari ini!")

# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print(f"🚀 ZEODDA AUTOMATION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not LARK_USER_TOKEN:
        raise Exception("❌ LARK_USER_TOKEN tidak ada!")

    print("✅ Lark user token tersedia")

    data = fetch_all_shopee_data()

    print("\n📤 MENGINPUT KE LARK BASE...")
    input_daily_overview(data)
    input_product_performance(data["items"])
    input_ads_shop(data)
    input_financial(data)
    input_alerts(data)

    print("\n" + "=" * 60)
    print("✅ SELESAI! Semua data sudah masuk ke Lark Base.")
    print("=" * 60)

if __name__ == "__main__":
    main()
