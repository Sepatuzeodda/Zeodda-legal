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

LARK_APP_ID     = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN  = "WficwtQQGi0nx5k8yv2lAJLYg0g"
LARK_BASE_URL   = "https://open.larksuite.com"

TABLE_DAILY_OVERVIEW = "tblOIk5Rv5wTrbOM"
TABLE_PRODUCT_PERF   = "tbl1TS2Hk26v5HB1"
TABLE_ADS_SHOP       = "tblxgI3Ia1YmCR6L"
TABLE_ADS_PRODUCT    = "tblpy5kqHrSPaoxk"
TABLE_KOMPARASI      = "tbljsQISLBtRDkeh"
TABLE_SOCIAL_MEDIA   = "tbllk68BO9607IO4"
TABLE_FINANCIAL      = "tbl2Or8DO3wywwxn"
TABLE_ALERT_LOG      = "tblCutzEM4Bp0DmN"

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
        # FIX: selalu return dict, tidak pernah None
        return data.get("response") or {}
    except Exception as e:
        print(f"❌ Request error {path}: {e}")
        return {}

def get_lark_token():
    url = f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
    r = requests.post(url, json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=30)
    data = r.json()
    if data.get("code") == 0:
        return data["tenant_access_token"]
    print(f"❌ Lark token error: {data}")
    return None

def lark_add(token, table_id, fields):
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records"
    r = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"fields": fields}, timeout=30)
    result = r.json()
    if result.get("code") != 0:
        print(f"❌ Lark error code {result.get('code')}: {result.get('msg')}")
    return result

def lark_add_batch(token, table_id, records_list):
    if not records_list:
        return {}
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/batch_create"
    r = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"records": [{"fields": f} for f in records_list]}, timeout=30)
    result = r.json()
    if result.get("code") != 0:
        print(f"❌ Lark batch error code {result.get('code')}: {result.get('msg')}")
    return result

def fetch_all_shopee_data():
    print("📥 Mengambil semua data Shopee...")
    today = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
    now = int(time.time())
    date_str = datetime.now().strftime("%Y-%m-%d")

    data = {}
    data["shop_info"]   = shopee_get("/api/v2/shop/get_shop_info")
    data["shop_perf"]   = shopee_get("/api/v2/account_health/get_shop_performance")
    data["orders"]      = shopee_get("/api/v2/order/get_order_list", {"time_range_field": "create_time", "time_from": today, "time_to": now, "page_size": 100})
    data["returns"]     = shopee_get("/api/v2/returns/get_return_list", {"page_no": 1, "page_size": 100, "create_time_from": today, "create_time_to": now})
    data["income"]      = shopee_get("/api/v2/payment/get_income_overview", {"start_date": date_str, "end_date": date_str})
    data["balance"]     = shopee_get("/api/v2/ads/get_total_balance")
    data["penalty"]     = shopee_get("/api/v2/account_health/get_penalty_point_history")
    data["late_orders"] = shopee_get("/api/v2/account_health/get_late_orders")
    data["issues"]      = shopee_get("/api/v2/account_health/get_listings_with_issues")
    data["ads"]         = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {"start_date": date_str, "end_date": date_str})
    data["items"]       = shopee_get("/api/v2/product/get_item_list", {"offset": 0, "page_size": 50, "item_status": "NORMAL"}).get("item", [])

    print("✅ Data Shopee berhasil diambil!")
    return data

def input_daily_overview(token, d):
    print("📋 Input Daily Overview...")
    perf_map = {1: "Poor", 2: "Improvement Needed", 3: "Good", 4: "Excellent"}
    today_ms = int(datetime.now().replace(hour=0,minute=0,second=0).timestamp() * 1000)

    fields = {
        "Tanggal": today_ms,
        "Platform": "Shopee",
        "Total Order Masuk": len(d["orders"].get("order_list", [])),
        "Total Retur": len(d["returns"].get("return_list", [])),
        "Omzet Harian": float(d["income"].get("total_income", 0) or 0),
        "Follower Toko": int(d["shop_info"].get("follower_count", 0) or 0),
        "Skor Performa Toko": perf_map.get(d["shop_perf"].get("overall_performance", {}).get("rating", 0), "Unknown"),
        "Poin Penalti": int(d["penalty"].get("total_penalty_point", 0) or 0),
        "Order Terlambat": int(d["late_orders"].get("total_count", 0) or 0),
        "Produk Bermasalah": int(d["issues"].get("total_count", 0) or 0),
        "Saldo Iklan": float(d["balance"].get("total_balance", 0) or 0),
    }
    result = lark_add(token, TABLE_DAILY_OVERVIEW, fields)
    print("✅ Daily Overview done!" if result.get("code") == 0 else f"❌ Gagal")

def input_product_performance(token, items):
    print("⭐ Input Product Performance...")
    if not items:
        print("⚠️ Tidak ada produk di sandbox, skip.")
        return

    today_ms = int(datetime.now().replace(hour=0,minute=0,second=0).timestamp() * 1000)
    records = []

    for item in items[:20]:
        item_id = item.get("item_id")
        comment_resp = shopee_get("/api/v2/product/get_comment", {"item_id": item_id, "cursor": "", "page_size": 100})
        comments = comment_resp.get("comment_list", [])

        star = {1:0, 2:0, 3:0, 4:0, 5:0}
        for c in comments:
            r = c.get("rating_star", 0)
            if r in star: star[r] += 1

        avg = sum(k*v for k,v in star.items()) / len(comments) if comments else 0

        records.append({
            "Tanggal": today_ms,
            "Platform": "Shopee",
            "Nama Produk": item.get("item_name", ""),
            "Item ID": str(item_id),
            "Rating Bintang": round(avg, 2),
            "Total Review": len(comments),
            "Review Bintang 5": star[5],
            "Review Bintang 4": star[4],
            "Review Bintang 3": star[3],
            "Review Bintang 2": star[2],
            "Review Bintang 1": star[1],
            "Review Negatif Baru": star[1] + star[2],
        })

    if records:
        result = lark_add_batch(token, TABLE_PRODUCT_PERF, records)
        print(f"✅ Product Performance done {len(records)} produk!" if result.get("code") == 0 else "❌ Gagal")

def input_ads_shop(token, d):
    print("📢 Input Ads Shop Level...")
    today_ms = int(datetime.now().replace(hour=0,minute=0,second=0).timestamp() * 1000)
    # FIX: ads bisa kosong di sandbox, handle dengan default {}
    ads = d.get("ads") or {}

    fields = {
        "Tanggal": today_ms,
        "Platform": "Shopee Ads",
        "Saldo Iklan": float(d["balance"].get("total_balance", 0) or 0),
        "Total Spend": float(ads.get("cost", 0) or 0),
        "Total Impresi": int(ads.get("impression", 0) or 0),
        "Total Klik": int(ads.get("click", 0) or 0),
        "Total Order dari Iklan": int(ads.get("order", 0) or 0),
        "Revenue dari Iklan": float(ads.get("order_amount", 0) or 0),
    }
    result = lark_add(token, TABLE_ADS_SHOP, fields)
    print("✅ Ads Shop Level done!" if result.get("code") == 0 else "❌ Gagal")

def input_financial(token, d):
    print("💰 Input Financial Summary...")
    today_ms = int(datetime.now().replace(hour=0,minute=0,second=0).timestamp() * 1000)
    ads = d.get("ads") or {}
    fields = {
        "Tanggal": today_ms,
        "Platform": "Shopee",
        "Gross Revenue": float(d["income"].get("total_income", 0) or 0),
        "Biaya Platform": float(d["income"].get("escrow_amount", 0) or 0),
        "Spend Iklan": float(ads.get("cost", 0) or 0),
    }
    result = lark_add(token, TABLE_FINANCIAL, fields)
    print("✅ Financial Summary done!" if result.get("code") == 0 else "❌ Gagal")

def input_alerts(token, d):
    print("🚨 Cek dan input Alert Log...")
    today_ms = int(datetime.now().replace(hour=0,minute=0,second=0).timestamp() * 1000)
    alerts = []

    saldo = float(d["balance"].get("total_balance", 0) or 0)
    if saldo < 100000:
        alerts.append({"Tanggal": today_ms, "Platform": "Shopee", "Tipe Alert": "Iklan Hampir Habis", "Detail": f"Saldo iklan Rp {saldo:,.0f} — segera top up!", "Nilai Saat Ini": saldo, "Nilai Normal": 100000, "Prioritas": "🔴 Kritis", "Status": "Baru"})

    penalty = int(d["penalty"].get("total_penalty_point", 0) or 0)
    if penalty > 0:
        alerts.append({"Tanggal": today_ms, "Platform": "Shopee", "Tipe Alert": "Penalti", "Detail": f"Toko dapat {penalty} poin penalti!", "Nilai Saat Ini": penalty, "Nilai Normal": 0, "Prioritas": "🔴 Kritis", "Status": "Baru"})

    issues = int(d["issues"].get("total_count", 0) or 0)
    if issues > 0:
        alerts.append({"Tanggal": today_ms, "Platform": "Shopee", "Tipe Alert": "Produk Bermasalah", "Detail": f"{issues} produk bermasalah.", "Nilai Saat Ini": issues, "Nilai Normal": 0, "Prioritas": "🟡 Penting", "Status": "Baru"})

    late = int(d["late_orders"].get("total_count", 0) or 0)
    if late > 5:
        alerts.append({"Tanggal": today_ms, "Platform": "Shopee", "Tipe Alert": "Order Terlambat", "Detail": f"{late} order terlambat.", "Nilai Saat Ini": late, "Nilai Normal": 5, "Prioritas": "🟡 Penting", "Status": "Baru"})

    if alerts:
        result = lark_add_batch(token, TABLE_ALERT_LOG, alerts)
        print(f"✅ {len(alerts)} alert dibuat!" if result.get("code") == 0 else "❌ Gagal")
    else:
        print("✅ Tidak ada alert hari ini!")

def main():
    print("=" * 60)
    print(f"🚀 ZEODDA AUTOMATION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    lark_token = get_lark_token()
    if not lark_token:
        raise Exception("Gagal dapat Lark token!")

    data = fetch_all_shopee_data()

    print("\n📤 MENGINPUT KE LARK BASE...")
    input_daily_overview(lark_token, data)
    input_product_performance(lark_token, data["items"])
    input_ads_shop(lark_token, data)
    input_financial(lark_token, data)
    input_alerts(lark_token, data)

    print("\n" + "=" * 60)
    print("✅ SELESAI! Semua data sudah masuk ke Lark Base.")
    print("=" * 60)

if __name__ == "__main__":
    main()
