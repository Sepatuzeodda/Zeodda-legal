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

_lark_tenant_token = None

def get_lark_tenant_token() -> str:
    global _lark_tenant_token
    if _lark_tenant_token:
        return _lark_tenant_token
    url = f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
    try:
        r = requests.post(url, json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=30)
        data = r.json()
        if data.get("code") != 0:
            raise Exception(f"Gagal get tenant token: {data.get('msg')} (code={data.get('code')})")
        _lark_tenant_token = data["tenant_access_token"]
        print(f"✅ Lark tenant token berhasil di-generate")
        return _lark_tenant_token
    except Exception as e:
        raise Exception(f"❌ get_lark_tenant_token error: {e}")

# Table IDs
TABLE_DAILY_OVERVIEW = "tblSVQG08nHr7tXD"
TABLE_PRODUCT_PERF   = "tblRlDzWXK5gQXzT"
TABLE_ADS_SHOP       = "tbl6EhWSzZumBR4L"
TABLE_FINANCIAL      = "tblLh7liZZxPzEpl"
TABLE_ALERT_LOG      = "tblobivbXf5KBsUK"

# ============================================================
# SAFE TYPE HELPERS
# ============================================================

def safe_int(val):
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
    return {
        "Authorization": f"Bearer {get_lark_tenant_token()}",
        "Content-Type":  "application/json",
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

    # Script jalan jam 00:00 WIB → ambil data KEMARIN (H-1)
    now_wib      = datetime.utcnow() + timedelta(hours=7)
    yesterday_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    ts_start     = int((yesterday_wib - timedelta(hours=7)).timestamp())   # 00:00 WIB → UTC epoch
    ts_end       = int((yesterday_wib + timedelta(hours=17) - timedelta(seconds=1)).timestamp())  # 23:59:59 WIB
    date_str     = yesterday_wib.strftime("%Y-%m-%d")
    yesterday_ms = int(yesterday_wib.timestamp() * 1000)

    print(f"📅 Ambil data kemarin: {date_str} WIB ({ts_start} → {ts_end})")

    data = {}
    data["yesterday_ms"] = yesterday_ms
    data["date_str"]     = date_str

    data["shop_info"]  = shopee_get("/api/v2/shop/get_shop_info")
    data["shop_perf"]  = shopee_get("/api/v2/account_health/get_shop_performance")
    data["balance"]    = shopee_get("/api/v2/ads/get_total_balance")   # real-time = snapshot jam 00:00 = closing kemarin
    data["penalty"]    = shopee_get("/api/v2/account_health/get_penalty_point_history")
    data["late_orders"]= shopee_get("/api/v2/account_health/get_late_orders")
    data["issues"]     = shopee_get("/api/v2/account_health/get_listings_with_issues")

    # Order kemarin
    data["orders"] = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from":  ts_start,
        "time_to":    ts_end,
        "page_size":  100,
    })
    data["cancelled_orders"] = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from":  ts_start,
        "time_to":    ts_end,
        "page_size":  100,
        "order_status": "CANCELLED",
    })
    data["returns"] = shopee_get("/api/v2/returns/get_return_list", {
        "page_no": 1, "page_size": 100,
        "create_time_from": ts_start, "create_time_to": ts_end,
    })

    # Income overview kemarin (untuk biaya platform)
    data["income"] = shopee_get("/api/v2/payment/get_income_overview", {
        "start_date": date_str, "end_date": date_str,
    })

    # Ads performance kemarin
    data["ads"] = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {
        "start_date": date_str, "end_date": date_str,
    })

    # Produk aktif (untuk product performance)
    items_resp = shopee_get("/api/v2/product/get_item_list", {
        "offset": 0, "page_size": 50, "item_status": "NORMAL",
    })
    data["items"] = items_resp.get("item", []) if isinstance(items_resp, dict) else []

    # === Omzet dari order detail kemarin ===
    all_orders    = safe_list(data.get("orders", {}), "order_list")
    order_sn_list = [o.get("order_sn") for o in all_orders if o.get("order_sn")]

    omzet_harian = 0  # exclude ongkir (total_amount)
    omzet_gross  = 0  # include ongkir (buyer_paid_amount = sama dengan Seller Center)

    if order_sn_list:
        print(f"  → Fetching detail {len(order_sn_list)} order kemarin untuk omzet...")
        for i in range(0, len(order_sn_list), 50):
            batch = order_sn_list[i:i+50]
            detail_resp = shopee_get("/api/v2/order/get_order_detail", {
                "order_sn_list": ",".join(batch),
                "response_optional_fields": "total_amount,buyer_paid_amount,actual_shipping_fee,item_list",
            })
            for od in (detail_resp.get("order_list", []) or []):
                if not isinstance(od, dict):
                    continue
                if od.get("order_status") in ("CANCELLED", "UNPAID"):
                    continue
                omzet_harian += safe_int(od.get("total_amount", 0))
                # buyer_paid_amount = total_amount + ongkir yang dibayar buyer
                # Jika tidak ada, fallback ke total_amount + actual_shipping_fee
                buyer_paid = od.get("buyer_paid_amount", 0)
                if buyer_paid:
                    omzet_gross += safe_int(buyer_paid)
                else:
                    shipping = safe_int(od.get("actual_shipping_fee", 0))
                    omzet_gross += safe_int(od.get("total_amount", 0)) + shipping

    data["omzet_harian"] = omzet_harian
    data["omzet_gross"]  = omzet_gross

    print(f"🔍 RAW balance (closing kemarin): {repr(data['balance'])[:100]}")
    print(f"💰 Omzet Kemarin (exclude ongkir): Rp {omzet_harian:,}")
    print(f"💰 Omzet Gross   (include ongkir): Rp {omzet_gross:,} ← harusnya sama dengan Seller Center")
    print(f"   dari {len(order_sn_list)} order")
    print("✅ Data Shopee berhasil diambil!")
    return data

# ============================================================
# INPUT KE LARK BASE
# ============================================================

def input_daily_overview(d):
    print("📋 Input Daily Overview (Shopee)...")

    shop_perf    = safe_dict(d, "shop_perf")
    overall_perf = safe_dict(shop_perf, "overall_performance")
    shop_info    = safe_dict(d, "shop_info")
    penalty      = safe_dict(d, "penalty")
    late_orders  = safe_dict(d, "late_orders")
    issues       = safe_dict(d, "issues")
    balance      = safe_dict(d, "balance")

    all_orders       = safe_list(d.get("orders", {}),           "order_list")
    cancelled_orders = safe_list(d.get("cancelled_orders", {}), "order_list")
    returns_list     = safe_list(d.get("returns", {}),          "return_list")

    fields = {
        "Tanggal":                d["yesterday_ms"],
        "Platform":               "Shopee",
        "Total Order Masuk":      safe_int(len(all_orders)),
        "Total Order Dibatalkan": safe_int(len(cancelled_orders)),
        "Total Retur":            safe_int(len(returns_list)),
        "Omzet Harian":           safe_int(d.get("omzet_harian", 0)),   # exclude ongkir
        "Omzet Gross":            safe_int(d.get("omzet_gross", 0)),     # include ongkir (= Seller Center)
        "Follower Toko":          safe_int(shop_info.get("follower_count", 0)),
        "Skor Performa Toko":     safe_int(overall_perf.get("rating", 0)),
        "Poin Penalti":           safe_int(penalty.get("total_penalty_point", 0)),
        "Order Terlambat":        safe_int(late_orders.get("total_count", 0)),
        "Produk Bermasalah":      safe_int(issues.get("total_count", 0)),
        "Saldo Iklan":            safe_int(balance.get("total_balance", 0)),
    }

    print("🔍 Daily Overview:")
    for k, v in fields.items():
        print(f"   {k}: {repr(v)}")

    result = lark_add(TABLE_DAILY_OVERVIEW, fields)
    print("✅ Daily Overview done!" if result.get("code") == 0 else "❌ Gagal")


def input_product_performance(d):
    print("⭐ Input Product Performance (Shopee)...")
    items = d.get("items", [])
    if not items:
        print("⚠️ Tidak ada produk, skip.")
        return

    # Nama field review bintang di Lark (dengan emoji)
    REVIEW_FIELD = {
        5: "Review Bintang 5 ⭐⭐⭐⭐⭐",
        4: "Review Bintang 4 ⭐⭐⭐⭐",
        3: "Review Bintang 3 ⭐⭐⭐",
        2: "Review Bintang 2 ⭐⭐",
        1: "Review Bintang 1 ⭐",
    }

    records    = []
    debug_done = False

    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id")

        # Fetch komentar/review
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

        # Fetch detail produk
        item_detail    = shopee_get("/api/v2/product/get_item_base_info", {
            "item_id_list": str(item_id),
        })
        item_info_list = item_detail.get("item_list", []) if isinstance(item_detail, dict) else []
        item_info      = item_info_list[0] if item_info_list else {}
        nama_produk    = safe_str(item_info.get("item_name", item.get("item_name", "")))

        # Harga & stok dari model
        models = item_info.get("model", []) or []
        harga  = 0
        stok   = 0
        for m in models:
            if not isinstance(m, dict):
                continue
            price_info = m.get("price_info", [])
            if price_info and isinstance(price_info, list):
                harga = safe_int(price_info[0].get("current_price", 0))
            stock_info = m.get("stock_info", {})
            if isinstance(stock_info, dict):
                stok += safe_int(stock_info.get("total_available_stock", 0))

        record = {
            "Tanggal":                    d["yesterday_ms"],
            "Platform":                   "Shopee",
            "Nama Produk":                nama_produk,
            "Item ID":                    safe_str(item_id),
            "Kategori Produk":            "",
            "Harga Jual":                 harga,
            "Stok Tersisa":               stok,
            "Terjual Hari Ini":           0,
            "Total Terjual Kumulatif":    safe_int(item_info.get("sold", 0)),
            "Rating Bintang":             safe_int(avg),
            "Total Review":               safe_int(len(comments)),
            REVIEW_FIELD[5]:              safe_int(star[5]),
            REVIEW_FIELD[4]:              safe_int(star[4]),
            REVIEW_FIELD[3]:              safe_int(star[3]),
            REVIEW_FIELD[2]:              safe_int(star[2]),
            REVIEW_FIELD[1]:              safe_int(star[1]),
            "Review Negatif Baru":        safe_int(star[1] + star[2]),
            "Views Produk":               0,
            "Status Boost":               "",
            "Ada Promo Aktif":            False,
            "Status Produk":              safe_str(item_info.get("item_status", "")),
            "Revenue Produk":             0,
            "CTR Listing":                "",
            "Conversion Rate":            "",
        }

        # Debug record pertama — kirim field per field kalau gagal
        if not debug_done:
            print(f"🔬 Debug record pertama (item_id={item_id})...")
            url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_PRODUCT_PERF}/records"
            test = requests.post(url, headers=get_lark_headers(), json={"fields": record}, timeout=30).json()
            if test.get("code") != 0:
                print(f"  ❌ Full record gagal: {test.get('msg')} — kirim field per field...")
                bad_fields = set()
                for key, val in record.items():
                    tr = requests.post(url, headers=get_lark_headers(),
                        json={"fields": {key: val}}, timeout=30).json()
                    status = "✅" if tr.get("code") == 0 else "❌"
                    print(f"    {status} '{key}'" + (f" → {tr.get('msg')}" if tr.get("code") != 0 else ""))
                    if tr.get("code") != 0:
                        bad_fields.add(key)
                for bf in bad_fields:
                    record.pop(bf, None)
                print(f"  ⚠️ Di-skip: {bad_fields}")
            else:
                print(f"  ✅ Record pertama OK!")
            debug_done = True

        records.append(record)

    if records:
        result = lark_add_batch(TABLE_PRODUCT_PERF, records)
        print(f"✅ Product Performance {len(records)} produk!" if result.get("code") == 0 else "❌ Gagal batch")


def input_ads_shop(d):
    print("📢 Input Ads Shop Level (Shopee)...")
    ads     = safe_dict(d, "ads")
    balance = safe_dict(d, "balance")

    fields = {
        "Tanggal":                d["yesterday_ms"],
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
    print("💰 Input Financial Summary (Shopee)...")
    income = safe_dict(d, "income")
    ads    = safe_dict(d, "ads")

    fields = {
        "Tanggal":        d["yesterday_ms"],
        "Platform":       "Shopee",
        "Gross Revenue":  safe_int(d.get("omzet_harian", 0)),
        "Biaya Platform": safe_int((income.get("escrow_amount") or {}).get("released_amount", 0)),
        "Spend Iklan":    safe_int(ads.get("cost", 0)),
    }
    result = lark_add(TABLE_FINANCIAL, fields)
    print("✅ Financial Summary done!" if result.get("code") == 0 else "❌ Gagal")


def input_alerts(d):
    print("🚨 Cek Alert Log (Shopee)...")
    balance = safe_dict(d, "balance")
    penalty = safe_dict(d, "penalty")
    issues  = safe_dict(d, "issues")
    late    = safe_dict(d, "late_orders")
    alerts  = []

    saldo = safe_int(balance.get("total_balance", 0))
    if saldo < 100000:
        alerts.append({
            "Tanggal": d["yesterday_ms"], "Platform": "Shopee",
            "Tipe Alert": "Iklan Hampir Habis",
            "Detail": f"Saldo iklan Rp {saldo:,} — segera top up!",
            "Nilai Saat Ini": saldo, "Nilai Normal": 100000,
            "Prioritas": "🔴 Kritis", "Status": "Baru",
        })

    pen = safe_int(penalty.get("total_penalty_point", 0))
    if pen > 0:
        alerts.append({
            "Tanggal": d["yesterday_ms"], "Platform": "Shopee",
            "Tipe Alert": "Penalti",
            "Detail": f"Toko dapat {pen} poin penalti!",
            "Nilai Saat Ini": pen, "Nilai Normal": 0,
            "Prioritas": "🔴 Kritis", "Status": "Baru",
        })

    isu = safe_int(issues.get("total_count", 0))
    if isu > 0:
        alerts.append({
            "Tanggal": d["yesterday_ms"], "Platform": "Shopee",
            "Tipe Alert": "Produk Bermasalah",
            "Detail": f"{isu} produk bermasalah.",
            "Nilai Saat Ini": isu, "Nilai Normal": 0,
            "Prioritas": "🟡 Penting", "Status": "Baru",
        })

    terlambat = safe_int(late.get("total_count", 0))
    if terlambat > 5:
        alerts.append({
            "Tanggal": d["yesterday_ms"], "Platform": "Shopee",
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
    print(f"🚀 ZEODDA AUTOMATION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 60)

    if not LARK_APP_ID or not LARK_APP_SECRET:
        raise Exception("❌ LARK_APP_ID atau LARK_APP_SECRET tidak ada!")
    get_lark_tenant_token()

    print("\n" + "─" * 40)
    print("🛒 SHOPEE")
    print("─" * 40)
    shopee_data = fetch_all_shopee_data()

    print("\n📤 Menginput data ke Lark Base...")
    input_daily_overview(shopee_data)
    input_product_performance(shopee_data)
    input_ads_shop(shopee_data)
    input_financial(shopee_data)
    input_alerts(shopee_data)

    print("\n" + "=" * 60)
    print("✅ SELESAI! Semua data sudah masuk ke Lark Base.")
    print("=" * 60)

if __name__ == "__main__":
    main()
