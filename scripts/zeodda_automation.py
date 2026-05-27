import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timedelta

# ============================================================
# CONFIG - SHOPEE
# ============================================================

SHOPEE_PARTNER_ID   = int(os.environ.get("SHOPEE_PARTNER_ID", "1234324"))
SHOPEE_PARTNER_KEY  = os.environ.get("SHOPEE_PARTNER_KEY", "")
SHOPEE_SHOP_ID      = int(os.environ.get("SHOPEE_SHOP_ID", "963980234"))
SHOPEE_ACCESS_TOKEN = os.environ.get("SHOPEE_ACCESS_TOKEN", "")
SHOPEE_BASE_URL     = "https://openplatform.sandbox.test-stable.shopee.sg"
# SHOPEE_BASE_URL = "https://partner.shopeemobile.com"  # Production

# ============================================================
# CONFIG - TIKTOK SHOP
# ============================================================

TIKTOK_APP_KEY       = os.environ.get("TIKTOK_SHOP_APP_KEY", "")
TIKTOK_APP_SECRET    = os.environ.get("TIKTOK_SHOP_APP_SECRET", "")
TIKTOK_ACCESS_TOKEN  = os.environ.get("TIKTOK_SHOP_ACCESS_TOKEN", "")
TIKTOK_REFRESH_TOKEN = os.environ.get("TIKTOK_SHOP_REFRESH_TOKEN", "")
TIKTOK_SHOP_ID       = os.environ.get("TIKTOK_SHOP_SHOP_ID", "")
TIKTOK_BASE_URL      = "https://open-api.tiktokglobalshop.com"
TIKTOK_TOKEN_URL     = "https://auth.tiktok-shops.com/api/v2/token/get"

# ============================================================
# CONFIG - LARK
# ============================================================

LARK_APP_ID     = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN  = "Nql3bfZtqaNABdslc1jlYFRqgCc"
LARK_BASE_URL   = "https://open.larksuite.com"

# Cache tenant token dalam satu run (valid 2 jam, lebih dari cukup)
_lark_tenant_token = None

def get_lark_tenant_token() -> str:
    """
    Generate tenant access token dari App ID + App Secret.
    Token ini tidak pernah expired selama script jalan — di-refresh otomatis tiap run.
    Tidak perlu copy-paste token manual ke GitHub Secrets.
    """
    global _lark_tenant_token
    if _lark_tenant_token:
        return _lark_tenant_token
    url = f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
    try:
        r = requests.post(url, json={
            "app_id":     LARK_APP_ID,
            "app_secret": LARK_APP_SECRET,
        }, timeout=30)
        data = r.json()
        if data.get("code") != 0:
            raise Exception(f"Gagal get tenant token: {data.get('msg')} (code={data.get('code')})")
        _lark_tenant_token = data["tenant_access_token"]
        print(f"✅ Lark tenant token berhasil di-generate")
        return _lark_tenant_token
    except Exception as e:
        raise Exception(f"❌ get_lark_tenant_token error: {e}")

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
# TIKTOK SHOP HELPERS
# ============================================================

def tiktok_sign(path: str, params: dict) -> str:
    """
    HMAC-SHA256: app_secret + path + sorted_param_string + app_secret
    Exclude: sign, access_token
    """
    excluded = {"sign", "access_token"}
    sorted_str = "".join(
        f"{k}{v}"
        for k, v in sorted(params.items())
        if k not in excluded
    )
    base = TIKTOK_APP_SECRET + path + sorted_str + TIKTOK_APP_SECRET
    return hmac.new(
        TIKTOK_APP_SECRET.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def tiktok_base_params() -> dict:
    return {
        "app_key":      TIKTOK_APP_KEY,
        "access_token": TIKTOK_ACCESS_TOKEN,
        "timestamp":    str(int(time.time())),
        "shop_id":      TIKTOK_SHOP_ID,
    }

def tiktok_refresh_token() -> bool:
    """Refresh access token. Kembalikan True jika berhasil."""
    global TIKTOK_ACCESS_TOKEN, TIKTOK_REFRESH_TOKEN
    params = {
        "app_key":       TIKTOK_APP_KEY,
        "app_secret":    TIKTOK_APP_SECRET,
        "refresh_token": TIKTOK_REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    }
    try:
        r = requests.get(TIKTOK_TOKEN_URL, params=params, timeout=30)
        data = r.json()
        if data.get("code") == 0:
            TIKTOK_ACCESS_TOKEN  = data["data"]["access_token"]
            TIKTOK_REFRESH_TOKEN = data["data"]["refresh_token"]
            print("🔄 TikTok token refreshed!")
            # ⚠️ CATATAN: Token baru tidak otomatis tersimpan ke GitHub Secrets.
            # Simpan manual atau tambahkan gh CLI call di sini jika diperlukan.
            return True
        else:
            print(f"❌ Token refresh gagal: {data}")
            return False
    except Exception as e:
        print(f"❌ Token refresh error: {e}")
        return False

def tiktok_get(path: str, extra: dict = {}, _retry: bool = True) -> dict:
    """GET request ke TikTok Shop API dengan auto-sign & auto-refresh."""
    params = tiktok_base_params()
    params.update(extra)
    params["sign"] = tiktok_sign(path, params)
    try:
        r = requests.get(f"{TIKTOK_BASE_URL}{path}", params=params, timeout=30)
        data = r.json()
        # Token expired codes
        if data.get("code") in (40001, 40002, 40003) and _retry:
            print("⚠️ TikTok token expired, mencoba refresh...")
            if tiktok_refresh_token():
                return tiktok_get(path, extra, _retry=False)
        if data.get("code") != 0:
            print(f"❌ TikTok GET error [{path}]: {data.get('message')} (code={data.get('code')})")
            return {}
        return data.get("data", {})
    except Exception as e:
        print(f"❌ TikTok GET error [{path}]: {e}")
        return {}

def tiktok_post(path: str, body: dict = {}, extra: dict = {}, _retry: bool = True) -> dict:
    """POST request ke TikTok Shop API dengan auto-sign & auto-refresh."""
    params = tiktok_base_params()
    params.update(extra)
    params["sign"] = tiktok_sign(path, params)
    try:
        r = requests.post(f"{TIKTOK_BASE_URL}{path}", params=params, json=body, timeout=30)
        data = r.json()
        if data.get("code") in (40001, 40002, 40003) and _retry:
            print("⚠️ TikTok token expired, mencoba refresh...")
            if tiktok_refresh_token():
                return tiktok_post(path, body, extra, _retry=False)
        if data.get("code") != 0:
            print(f"❌ TikTok POST error [{path}]: {data.get('message')} (code={data.get('code')})")
            return {}
        return data.get("data", {})
    except Exception as e:
        print(f"❌ TikTok POST error [{path}]: {e}")
        return {}

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

    print("🔍 RAW income:", repr(data["income"])[:120])
    print("🔍 RAW balance:", repr(data["balance"])[:120])
    print("🔍 RAW shop_info keys:", list(data["shop_info"].keys()) if isinstance(data["shop_info"], dict) else repr(data["shop_info"])[:80])
    print("✅ Data Shopee berhasil diambil!")
    return data

# ============================================================
# AMBIL DATA TIKTOK SHOP
# ============================================================

def fetch_all_tiktok_data():
    print("\n📥 Mengambil semua data TikTok Shop...")

    # Rentang waktu: kemarin 00:00 → 23:59:59
    yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    ts_start  = int(yesterday.timestamp())
    ts_end    = ts_start + 86399  # +23j59m59d
    date_str  = yesterday.strftime("%Y-%m-%d")

    data = {}

    # --- Orders ---
    print("  → Fetching orders...")
    orders_resp = tiktok_post("/api/orders/search", body={}, extra={
        "create_time_from": str(ts_start),
        "create_time_to":   str(ts_end),
        "page_size":        "100",
    })
    data["orders"] = orders_resp.get("order_list", []) if orders_resp else []

    # --- Order details (batch 50) untuk revenue & units ---
    print("  → Fetching order details...")
    order_ids = [o["order_id"] for o in data["orders"] if o.get("order_id")]
    all_details = []
    for i in range(0, len(order_ids), 50):
        batch = order_ids[i:i+50]
        detail_resp = tiktok_post("/api/orders/detail/query", body={"order_id_list": batch})
        all_details.extend(detail_resp.get("order_list", []) if detail_resp else [])
    data["order_details"] = all_details

    # --- Products (paginated) ---
    print("  → Fetching products...")
    all_products = []
    page = 1
    while True:
        prod_resp = tiktok_post("/api/products/search", body={}, extra={
            "page_size":   "100",
            "page_number": str(page),
        })
        if not prod_resp:
            break
        products = prod_resp.get("products", [])
        all_products.extend(products)
        total = prod_resp.get("total_count", 0)
        if not products or len(all_products) >= total:
            break
        page += 1
    data["products"] = all_products

    # --- Finance settlements ---
    print("  → Fetching finance...")
    finance_resp = tiktok_get("/api/finance/settlements", {
        "create_time_from": str(ts_start),
        "create_time_to":   str(ts_end),
        "page_size":        "100",
    })
    data["finance"] = finance_resp.get("statement_list", []) if finance_resp else []

    print(f"🔍 TikTok: {len(data['orders'])} orders, {len(data['products'])} produk, {len(data['finance'])} transaksi")
    print("✅ Data TikTok Shop berhasil diambil!")
    return data, yesterday

# ============================================================
# INPUT SHOPEE KE LARK BASE
# ============================================================

def input_daily_overview(d):
    print("📋 Input Daily Overview (Shopee)...")
    today_ms = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp() * 1000)

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
    print("✅ Daily Overview (Shopee) done!" if result.get("code") == 0 else "❌ Gagal")

def input_product_performance(items):
    print("⭐ Input Product Performance (Shopee)...")
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
        print(f"✅ Product Performance (Shopee) {len(records)} produk!" if result.get("code") == 0 else "❌ Gagal")

def input_ads_shop(d):
    print("📢 Input Ads Shop Level (Shopee)...")
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
    print("✅ Ads Shop Level (Shopee) done!" if result.get("code") == 0 else "❌ Gagal")

def input_financial(d):
    print("💰 Input Financial Summary (Shopee)...")
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
    print("✅ Financial Summary (Shopee) done!" if result.get("code") == 0 else "❌ Gagal")

def input_alerts(d):
    print("🚨 Cek dan input Alert Log (Shopee)...")
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
        print("✅ Tidak ada alert hari ini (Shopee)!")

# ============================================================
# INPUT TIKTOK SHOP KE LARK BASE
# ============================================================

def input_tiktok_daily_overview(tiktok_data, yesterday: datetime):
    """
    Hitung metrics dari order_details → push ke Daily Overview (Platform: Tiktok).
    Field names sama persis dengan yang Shopee pakai di tabel yang sama.
    """
    print("📋 Input Daily Overview (TikTok Shop)...")

    # Timestamp kemarin jam 00:00 dalam ms (konsisten dengan Shopee)
    yesterday_ms = int(yesterday.timestamp() * 1000)

    orders         = tiktok_data.get("orders", [])
    order_details  = tiktok_data.get("order_details", [])
    total_orders   = len(orders)

    if total_orders == 0:
        print("⚠️ Tidak ada order TikTok kemarin, tetap push row 0.")

    # Hitung dari detail order
    cancelled_count = 0
    units_sold      = 0
    total_revenue   = 0
    returns_count   = 0

    for o in order_details:
        if not isinstance(o, dict):
            continue
        status = o.get("order_status", "")
        if status == "CANCELLED":
            cancelled_count += 1
        # Revenue: payment_info.total_amount dalam sen (/ 100 → Rupiah)
        payment = o.get("payment_info", {}) or {}
        if status not in ("CANCELLED", "UNPAID"):
            total_revenue += safe_int(float(payment.get("total_amount", 0) or 0) / 100)
        # Units
        for item in (o.get("item_list", []) or []):
            if isinstance(item, dict) and status not in ("CANCELLED",):
                units_sold += safe_int(item.get("quantity", 0))
        # Returns
        if status in ("RETURN_SUCCESS", "RETURN_REQUEST"):
            returns_count += 1

    fields = {
        "Tanggal":                yesterday_ms,
        "Platform":               "Tiktok",
        "Total Order Masuk":      safe_int(total_orders),
        "Total Order Dibatalkan": safe_int(cancelled_count),
        "Total Retur":            safe_int(returns_count),
        "Omzet Harian":           safe_int(total_revenue),
        # Field-field di bawah tidak ada di TikTok API → isi 0 agar tidak error
        "Follower Toko":          0,
        "Skor Performa Toko":     0,
        "Poin Penalti":           0,
        "Order Terlambat":        0,
        "Produk Bermasalah":      0,
        "Saldo Iklan":            0,
    }

    print(f"🔍 TikTok Daily Overview: {total_orders} orders, Rp {total_revenue:,}")
    result = lark_add(TABLE_DAILY_OVERVIEW, fields)
    print("✅ Daily Overview (TikTok) done!" if result.get("code") == 0 else "❌ Gagal")

def input_tiktok_product_performance(tiktok_data, yesterday: datetime):
    """
    Fetch detail setiap produk (rating & review) → push ke Product Performance.
    Field names sama persis dengan Shopee di tabel yang sama.
    """
    print("⭐ Input Product Performance (TikTok Shop)...")

    yesterday_ms = int(yesterday.timestamp() * 1000)
    products = tiktok_data.get("products", [])

    if not products:
        print("⚠️ Tidak ada produk TikTok, skip.")
        return

    records = []
    for prod in products:
        if not isinstance(prod, dict):
            continue

        prod_id   = safe_str(prod.get("id") or prod.get("product_id", ""))
        prod_name = safe_str(prod.get("product_name", ""))

        # Fetch detail produk untuk rating
        detail = tiktok_get("/api/products/details", {"product_id": prod_id}) if prod_id else {}

        # TikTok meletakkan rating di quality_tier_info
        quality      = detail.get("quality_tier_info", {}) or {} if isinstance(detail, dict) else {}
        avg_rating   = safe_int(float(quality.get("average_star_rating", 0) or 0))
        review_count = safe_int(quality.get("review_count", 0))

        # Hitung stok dari SKUs
        skus = (detail.get("skus", []) or []) if isinstance(detail, dict) else []
        if not skus:
            skus = prod.get("skus", []) or []
        total_stock = 0
        for sku in skus:
            if not isinstance(sku, dict):
                continue
            stock_infos = sku.get("stock_infos", []) or []
            if stock_infos and isinstance(stock_infos[0], dict):
                total_stock += safe_int(stock_infos[0].get("available_stock", 0))

        # Field names = SAMA PERSIS dengan Shopee (agar satu tabel bisa multi-platform)
        records.append({
            "Tanggal":             yesterday_ms,
            "Platform":            "Tiktok",
            "Nama Produk":         prod_name,
            "Item ID":             prod_id,
            "Rating Bintang":      avg_rating,
            "Total Review":        review_count,
            # TikTok tidak expose per-bintang breakdown via API ini → isi 0
            "Review Bintang 5":    0,
            "Review Bintang 4":    0,
            "Review Bintang 3":    0,
            "Review Bintang 2":    0,
            "Review Bintang 1":    0,
            "Review Negatif Baru": 0,
        })

    if records:
        # Batch per 500 (limit Lark)
        for i in range(0, len(records), 500):
            result = lark_add_batch(TABLE_PRODUCT_PERF, records[i:i+500])
            print(f"✅ Product Performance (TikTok) {len(records[i:i+500])} produk!" if result.get("code") == 0 else "❌ Gagal")

def input_tiktok_financial(tiktok_data, yesterday: datetime):
    """
    Aggregate transaksi finansial TikTok → push ke Financial Summary.
    Field names sama persis dengan Shopee.
    """
    print("💰 Input Financial Summary (TikTok Shop)...")

    yesterday_ms = int(yesterday.timestamp() * 1000)
    transactions = tiktok_data.get("finance", [])

    gross_revenue  = 0
    biaya_platform = 0  # commission/fee
    spend_iklan    = 0  # ads spend (TikTok ads fee jika ada)

    for txn in (transactions or []):
        if not isinstance(txn, dict):
            continue
        txn_type = safe_str(txn.get("transaction_type", ""))
        # TikTok amount: dalam unit terkecil (fen/sen) → bagi 100
        amount = safe_int(float(txn.get("amount", 0) or 0) / 100)

        if txn_type in ("ORDER", "SALE", "SETTLEMENT"):
            gross_revenue += amount
        elif txn_type in ("FEE", "COMMISSION", "SERVICE_FEE", "PLATFORM_FEE"):
            biaya_platform += abs(amount)
        elif txn_type in ("ADS_FEE", "ADVERTISEMENT"):
            spend_iklan += abs(amount)
        elif txn_type in ("REFUND", "RETURN"):
            gross_revenue -= abs(amount)  # kurangi gross revenue

    fields = {
        "Tanggal":        yesterday_ms,
        "Platform":       "Tiktok",
        "Gross Revenue":  safe_int(gross_revenue),
        "Biaya Platform": safe_int(biaya_platform),
        "Spend Iklan":    safe_int(spend_iklan),
    }

    print(f"🔍 TikTok Financial: Gross={gross_revenue:,} Fee={biaya_platform:,}")
    result = lark_add(TABLE_FINANCIAL, fields)
    print("✅ Financial Summary (TikTok) done!" if result.get("code") == 0 else "❌ Gagal")

def input_tiktok_alerts(tiktok_data, yesterday: datetime):
    """Cek kondisi abnormal TikTok → push ke Alert Log."""
    print("🚨 Cek Alert Log (TikTok Shop)...")

    yesterday_ms = int(yesterday.timestamp() * 1000)
    orders        = tiktok_data.get("orders", [])
    order_details = tiktok_data.get("order_details", [])
    alerts        = []

    # Alert: tidak ada order sama sekali
    if len(orders) == 0:
        alerts.append({
            "Tanggal": yesterday_ms, "Platform": "Tiktok",
            "Tipe Alert": "Tidak Ada Order",
            "Detail": "Tidak ada order masuk di TikTok Shop kemarin.",
            "Nilai Saat Ini": 0, "Nilai Normal": 1,
            "Prioritas": "🟡 Penting", "Status": "Baru",
        })

    # Alert: order dibatalkan > 20%
    if order_details:
        cancelled = sum(1 for o in order_details if isinstance(o, dict) and o.get("order_status") == "CANCELLED")
        cancel_rate = cancelled / len(order_details) * 100
        if cancel_rate > 20:
            alerts.append({
                "Tanggal": yesterday_ms, "Platform": "Tiktok",
                "Tipe Alert": "Cancellation Rate Tinggi",
                "Detail": f"Cancel rate TikTok {cancel_rate:.1f}% ({cancelled}/{len(order_details)} order).",
                "Nilai Saat Ini": safe_int(cancel_rate),
                "Nilai Normal": 20,
                "Prioritas": "🔴 Kritis", "Status": "Baru",
            })

    # Alert: tidak ada data finance
    if not tiktok_data.get("finance"):
        alerts.append({
            "Tanggal": yesterday_ms, "Platform": "Tiktok",
            "Tipe Alert": "Finance Data Kosong",
            "Detail": "Tidak ada data transaksi keuangan TikTok kemarin.",
            "Nilai Saat Ini": 0, "Nilai Normal": 1,
            "Prioritas": "🟡 Penting", "Status": "Baru",
        })

    if alerts:
        result = lark_add_batch(TABLE_ALERT_LOG, alerts)
        print(f"✅ {len(alerts)} alert TikTok dibuat!" if result.get("code") == 0 else "❌ Gagal")
    else:
        print("✅ Tidak ada alert hari ini (TikTok)!")

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

    # --------------------------------------------------------
    # SHOPEE
    # --------------------------------------------------------
    print("\n" + "─" * 40)
    print("🛒 SHOPEE")
    print("─" * 40)
    shopee_data = fetch_all_shopee_data()

    print("\n📤 Menginput data Shopee ke Lark Base...")
    input_daily_overview(shopee_data)
    input_product_performance(shopee_data["items"])
    input_ads_shop(shopee_data)
    input_financial(shopee_data)
    input_alerts(shopee_data)

    # --------------------------------------------------------
    # TIKTOK SHOP
    # --------------------------------------------------------
    print("\n" + "─" * 40)
    print("🎵 TIKTOK SHOP")
    print("─" * 40)

    # Cek credentials tersedia sebelum fetch
    if not TIKTOK_APP_KEY or not TIKTOK_ACCESS_TOKEN or not TIKTOK_SHOP_ID:
        print("⚠️ TikTok credentials belum lengkap, skip TikTok Shop.")
    else:
        tiktok_data, yesterday = fetch_all_tiktok_data()

        print("\n📤 Menginput data TikTok ke Lark Base...")
        input_tiktok_daily_overview(tiktok_data, yesterday)
        input_tiktok_product_performance(tiktok_data, yesterday)
        input_tiktok_financial(tiktok_data, yesterday)
        input_tiktok_alerts(tiktok_data, yesterday)

    # --------------------------------------------------------
    print("\n" + "=" * 60)
    print("✅ SELESAI! Semua data sudah masuk ke Lark Base.")
    print("=" * 60)

if __name__ == "__main__":
    main()
