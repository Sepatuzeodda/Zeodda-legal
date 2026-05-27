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
SHOPEE_BASE_URL     = "https://partner.shopeemobile.com"  # Production

# ============================================================
# CONFIG - TIKTOK SHOP
# ============================================================

TIKTOK_APP_KEY       = os.environ.get("TIKTOK_SHOP_APP_KEY", "")
TIKTOK_APP_SECRET    = os.environ.get("TIKTOK_SHOP_APP_SECRET", "")
TIKTOK_ACCESS_TOKEN  = os.environ.get("TIKTOK_SHOP_ACCESS_TOKEN", "").strip()
TIKTOK_REFRESH_TOKEN = os.environ.get("TIKTOK_SHOP_REFRESH_TOKEN", "").strip()
TIKTOK_SHOP_ID       = os.environ.get("TIKTOK_SHOP_SHOP_ID", "")
TIKTOK_BASE_URL      = "https://open-api.tiktokglobalshop.com"
TIKTOK_TOKEN_URL     = "https://auth.tiktok-shops.com/api/v2/token/get"

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

TABLE_DAILY_OVERVIEW = "tblSVQG08nHr7tXD"
TABLE_PRODUCT_PERF   = "tblRlDzWXK5gQXzT"
TABLE_ADS_SHOP       = "tbl6EhWSzZumBR4L"
TABLE_ADS_PRODUCT    = "tbl3r112gUTEhHCe"
TABLE_KOMPARASI      = "tblZoIIwUj0RN93p"
TABLE_SOCIAL_MEDIA   = "tblkQ9voE785tQ1i"
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
    return {
        "Authorization": f"Bearer {get_lark_tenant_token()}",
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

def lark_add_debug(table_id, fields):
    """
    Kirim field satu per satu untuk debug FieldNameNotFound.
    Return field mana yang sukses dan mana yang gagal.
    """
    print(f"🔬 DEBUG MODE: Kirim {len(fields)} field satu per satu...")
    failed = []
    ok = []
    for key, val in fields.items():
        result = lark_add(table_id, {key: val})
        if result.get("code") != 0:
            print(f"  ❌ FIELD GAGAL: '{key}' = {repr(val)}")
            failed.append(key)
        else:
            ok.append(key)
    print(f"  ✅ OK: {ok}")
    print(f"  ❌ GAGAL: {failed}")
    return failed

# ============================================================
# TIKTOK SHOP HELPERS (minimal, skip untuk sekarang)
# ============================================================

TIKTOK_SHOP_CIPHER = os.environ.get("TIKTOK_SHOP_CIPHER", "").strip()

def tiktok_sign(path: str, params: dict, body: dict = None) -> str:
    excluded = {"sign", "access_token"}
    params_str = "".join(
        f"{k}{v}"
        for k, v in params.items()
        if k not in excluded
    )
    base = TIKTOK_APP_SECRET + path + params_str + TIKTOK_APP_SECRET
    sign = hmac.new(
        TIKTOK_APP_SECRET.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return sign

def tiktok_base_params() -> dict:
    params = {
        "app_key":   TIKTOK_APP_KEY,
        "timestamp": str(int(time.time())),
    }
    if TIKTOK_SHOP_CIPHER:
        params["shop_cipher"] = TIKTOK_SHOP_CIPHER
    elif TIKTOK_SHOP_ID:
        params["shop_id"] = str(TIKTOK_SHOP_ID)
    return params

def tiktok_refresh_token() -> bool:
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
            return True
        else:
            print(f"❌ Token refresh gagal: {data}")
            return False
    except Exception as e:
        print(f"❌ Token refresh error: {e}")
        return False

def tiktok_get(path: str, extra: dict = {}, _retry: bool = True) -> dict:
    params = tiktok_base_params()
    params.update(extra)
    params["sign"] = tiktok_sign(path, params)
    headers = {
        "x-tts-access-token": TIKTOK_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    try:
        r = requests.get(f"{TIKTOK_BASE_URL}{path}", params=params, headers=headers, timeout=30)
        data = r.json()
        print(f"🔍 TikTok GET [{path}] raw: code={data.get('code')} msg={data.get('message','')[:80]}")
        if data.get("code") in (40001, 40002, 40003) and _retry:
            if tiktok_refresh_token():
                return tiktok_get(path, extra, _retry=False)
        if data.get("code") != 0:
            return {}
        return data.get("data", {})
    except Exception as e:
        print(f"❌ TikTok GET error [{path}]: {e}")
        return {}

def tiktok_post(path: str, body: dict = {}, extra: dict = {}, _retry: bool = True) -> dict:
    params = tiktok_base_params()
    params.update(extra)
    params["sign"] = tiktok_sign(path, params)
    headers = {
        "x-tts-access-token": TIKTOK_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(f"{TIKTOK_BASE_URL}{path}", params=params, json=body, headers=headers, timeout=30)
        data = r.json()
        print(f"🔍 TikTok POST [{path}] raw: code={data.get('code')} msg={data.get('message','')[:80]}")
        if data.get("code") in (40001, 40002, 40003) and _retry:
            if tiktok_refresh_token():
                return tiktok_post(path, body, extra, _retry=False)
        if data.get("code") != 0:
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

    # Rentang waktu hari ini (WIB = UTC+7)
    # GitHub Actions jalan di UTC, jadi kita set range hari ini UTC+7
    now_wib      = datetime.utcnow() + timedelta(hours=7)
    today_wib    = now_wib.replace(hour=0, minute=0, second=0, microsecond=0)
    ts_start     = int((today_wib - timedelta(hours=7)).timestamp())  # convert back ke UTC epoch
    ts_end       = int((today_wib + timedelta(hours=17) - timedelta(seconds=1)).timestamp())  # 23:59:59 WIB
    date_str     = today_wib.strftime("%Y-%m-%d")

    print(f"📅 Rentang waktu: {today_wib.strftime('%Y-%m-%d')} WIB ({ts_start} → {ts_end})")

    data = {}
    data["shop_info"]        = shopee_get("/api/v2/shop/get_shop_info")
    data["shop_perf"]        = shopee_get("/api/v2/account_health/get_shop_performance")

    # Semua order hari ini
    data["orders"]           = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from": ts_start,
        "time_to": ts_end,
        "page_size": 100,
    })

    # Order dibatalkan hari ini
    data["cancelled_orders"] = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from": ts_start,
        "time_to": ts_end,
        "page_size": 100,
        "order_status": "CANCELLED",
    })

    data["returns"]          = shopee_get("/api/v2/returns/get_return_list", {
        "page_no": 1, "page_size": 100,
        "create_time_from": ts_start, "create_time_to": ts_end,
    })

    # Income overview untuk Biaya Platform saja (bukan omzet)
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

    items_resp = shopee_get("/api/v2/product/get_item_list", {
        "offset": 0, "page_size": 50, "item_status": "NORMAL",
    })
    data["items"] = items_resp.get("item", []) if isinstance(items_resp, dict) else []

    # === Hitung Omzet Harian dari order list (bukan income overview) ===
    # Ambil detail order untuk dapat total_amount per order
    all_orders = safe_list(data.get("orders", {}), "order_list")
    order_sn_list = [o.get("order_sn") for o in all_orders if o.get("order_sn")]

    omzet_harian = 0
    order_details_map = {}

    if order_sn_list:
        print(f"  → Fetching detail {len(order_sn_list)} order untuk omzet...")
        # Shopee limit 50 order per request
        for i in range(0, len(order_sn_list), 50):
            batch = order_sn_list[i:i+50]
            detail_resp = shopee_get("/api/v2/order/get_order_detail", {
                "order_sn_list": ",".join(batch),
                "response_optional_fields": "buyer_user_id,total_amount,item_list",
            })
            order_list = detail_resp.get("order_list", [])
            if not isinstance(order_list, list):
                order_list = []
            for od in order_list:
                if not isinstance(od, dict):
                    continue
                sn = od.get("order_sn", "")
                order_details_map[sn] = od
                status = od.get("order_status", "")
                if status not in ("CANCELLED", "UNPAID"):
                    omzet_harian += safe_int(od.get("total_amount", 0))

    data["omzet_harian"] = omzet_harian
    data["order_details_map"] = order_details_map

    print(f"🔍 RAW income: {repr(data['income'])[:120]}")
    print(f"🔍 RAW balance: {repr(data['balance'])[:120]}")
    print(f"🔍 RAW shop_info keys: {list(data['shop_info'].keys()) if isinstance(data['shop_info'], dict) else repr(data['shop_info'])[:80]}")
    print(f"💰 Omzet Harian (dari order detail): Rp {omzet_harian:,} dari {len(order_sn_list)} order")
    print("✅ Data Shopee berhasil diambil!")
    return data

# ============================================================
# AMBIL DATA TIKTOK SHOP
# ============================================================

def fetch_all_tiktok_data():
    print("\n📥 Mengambil semua data TikTok Shop...")

    yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    ts_start  = int(yesterday.timestamp())
    ts_end    = ts_start + 86399
    date_str  = yesterday.strftime("%Y-%m-%d")

    data = {}

    print("  → Fetching orders...")
    orders_resp = tiktok_post("/order/202309/orders/search", body={
        "create_time_ge": ts_start,
        "create_time_lt": ts_end,
        "page_size":      50,
    })
    data["orders"] = orders_resp.get("orders", []) if orders_resp else []

    print("  → Fetching order details...")
    order_ids = [o["id"] for o in data["orders"] if o.get("id")]
    all_details = []
    for i in range(0, len(order_ids), 50):
        batch = order_ids[i:i+50]
        detail_resp = tiktok_post("/order/202309/orders/detail/query",
                                  body={"order_id_list": batch})
        all_details.extend(detail_resp.get("orders", []) if detail_resp else [])
    data["order_details"] = all_details

    print("  → Fetching products...")
    all_products = []
    page_token = ""
    while True:
        body = {"page_size": 100}
        if page_token:
            body["page_token"] = page_token
        prod_resp = tiktok_post("/product/202309/products/search", body=body)
        if not prod_resp:
            break
        products = prod_resp.get("products", [])
        all_products.extend(products)
        page_token = prod_resp.get("next_page_token", "")
        if not products or not page_token:
            break
    data["products"] = all_products

    print("  → Fetching finance...")
    finance_resp = tiktok_get("/finance/202309/statements", {
        "create_time_ge": str(ts_start),
        "create_time_lt": str(ts_end),
        "page_size":      "100",
        "sort_field":     "statement_time",
        "sort_order":     "DESC",
    })
    data["finance"] = finance_resp.get("statements", []) if finance_resp else []

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

    # Omzet dari order detail (bukan income overview)
    omzet = d.get("omzet_harian", 0)

    fields = {
        "Tanggal":                today_ms,
        "Platform":               "Shopee",
        "Total Order Masuk":      safe_int(len(all_orders)),
        "Total Order Dibatalkan": safe_int(len(cancelled_orders)),
        "Total Retur":            safe_int(len(returns_list)),
        "Omzet Harian":           safe_int(omzet),
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
        print("⚠️ Tidak ada produk, skip.")
        return

    today_ms = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp() * 1000)

    # Field yang boleh dikirim ke Lark (exclude formula fields)
    # Sesuai tabel Product Performance
    EXCLUDED_FIELDS = set()  # Tambahkan nama field formula di sini kalau sudah diset

    records = []
    debug_done = False  # hanya debug record pertama

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

        # Fetch item detail untuk nama produk dan harga
        item_detail = shopee_get("/api/v2/product/get_item_base_info", {
            "item_id_list": str(item_id),
        })
        item_info_list = item_detail.get("item_list", []) if isinstance(item_detail, dict) else []
        item_info = item_info_list[0] if item_info_list else {}

        nama_produk = safe_str(item_info.get("item_name", item.get("item_name", "")))
        # Ambil harga dari model pertama
        models = item_info.get("model", []) or []
        harga = 0
        stok = 0
        for m in models:
            if isinstance(m, dict):
                price_info = m.get("price_info", [])
                if price_info and isinstance(price_info, list):
                    harga = safe_int(price_info[0].get("current_price", 0))
                stok += safe_int(m.get("stock_info", {}).get("total_available_stock", 0) if isinstance(m.get("stock_info"), dict) else 0)

        record = {
            "Tanggal":               today_ms,
            "Platform":              "Shopee",
            "Nama Produk":           nama_produk,
            "Item ID":               safe_str(item_id),
            "Kategori Produk":       "",
            "Harga Jual":            harga,
            "Stok Tersisa":          stok,
            "Terjual Hari Ini":      0,
            "Total Terjual Kumulatif": safe_int(item_info.get("sold", 0)),
            "Rating Bintang":        safe_int(avg),
            "Total Review":          safe_int(len(comments)),
            "Review Bintang 5":      safe_int(star[5]),
            "Review Bintang 4":      safe_int(star[4]),
            "Review Bintang 3":      safe_int(star[3]),
            "Review Bintang 2":      safe_int(star[2]),
            "Review Bintang 1":      safe_int(star[1]),
            "Review Negatif Baru":   safe_int(star[1] + star[2]),
            "Views Produk":          0,
            "Status Boost":          "",
            "Ada Promo Aktif":       False,
            "Status Produk":         safe_str(item_info.get("item_status", "")),
            "Revenue Produk":        0,
            "CTR Listing":           "",
            "Conversion Rate":       "",
        }

        # Exclude formula fields kalau ada
        for f in EXCLUDED_FIELDS:
            record.pop(f, None)

        # Debug: kirim record pertama field per field untuk detect masalah
        if not debug_done and len(records) == 0:
            print(f"🔬 Debug record pertama (item_id={item_id})...")
            url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_PRODUCT_PERF}/records"
            test_result = requests.post(url, headers=get_lark_headers(),
                json={"fields": record}, timeout=30).json()
            if test_result.get("code") != 0:
                print(f"  ❌ Full record gagal: {test_result.get('msg')}")
                print(f"  → Mencoba kirim field per field...")
                failed = []
                for key, val in record.items():
                    tr = requests.post(url, headers=get_lark_headers(),
                        json={"fields": {key: val}}, timeout=30).json()
                    if tr.get("code") != 0:
                        print(f"    ❌ FIELD GAGAL: '{key}' = {repr(val)} → {tr.get('msg')}")
                        failed.append(key)
                    else:
                        print(f"    ✅ OK: '{key}'")
                if failed:
                    print(f"  ⚠️ Field bermasalah: {failed} — akan di-skip")
                    for f in failed:
                        record.pop(f, None)
                        EXCLUDED_FIELDS.add(f)
            else:
                print(f"  ✅ Record pertama OK!")
            debug_done = True

        records.append(record)

    if records:
        # Bersihkan semua record dari field bermasalah
        clean_records = []
        for rec in records:
            for f in EXCLUDED_FIELDS:
                rec.pop(f, None)
            clean_records.append(rec)

        result = lark_add_batch(TABLE_PRODUCT_PERF, clean_records)
        print(f"✅ Product Performance (Shopee) {len(clean_records)} produk!" if result.get("code") == 0 else "❌ Gagal batch")

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

    # Omzet dari order detail (hari ini)
    omzet = d.get("omzet_harian", 0)

    fields = {
        "Tanggal":        today_ms,
        "Platform":       "Shopee",
        "Gross Revenue":  safe_int(omzet),
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
    print("📋 Input Daily Overview (TikTok Shop)...")
    yesterday_ms = int(yesterday.timestamp() * 1000)
    orders         = tiktok_data.get("orders", [])
    order_details  = tiktok_data.get("order_details", [])
    total_orders   = len(orders)

    if total_orders == 0:
        print("⚠️ Tidak ada order TikTok kemarin, tetap push row 0.")

    cancelled_count = 0
    units_sold      = 0
    total_revenue   = 0
    returns_count   = 0

    for o in order_details:
        if not isinstance(o, dict):
            continue
        status = o.get("status", o.get("order_status", ""))
        payment = o.get("payment", o.get("payment_info", {})) or {}
        if status not in ("CANCELLED", "UNPAID"):
            total_revenue += safe_int(float(payment.get("total_amount", 0) or 0) / 100)
        for item in (o.get("line_items", o.get("item_list", [])) or []):
            if isinstance(item, dict) and status not in ("CANCELLED",):
                units_sold += safe_int(item.get("quantity", 0))
        if status == "CANCELLED":
            cancelled_count += 1
        if status in ("RETURN_SUCCESS", "RETURN_REQUEST"):
            returns_count += 1

    fields = {
        "Tanggal":                yesterday_ms,
        "Platform":               "Tiktok",
        "Total Order Masuk":      safe_int(total_orders),
        "Total Order Dibatalkan": safe_int(cancelled_count),
        "Total Retur":            safe_int(returns_count),
        "Omzet Harian":           safe_int(total_revenue),
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
        detail = tiktok_get("/api/products/details", {"product_id": prod_id}) if prod_id else {}
        quality      = detail.get("quality_tier_info", {}) or {} if isinstance(detail, dict) else {}
        avg_rating   = safe_int(float(quality.get("average_star_rating", 0) or 0))
        review_count = safe_int(quality.get("review_count", 0))
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

        records.append({
            "Tanggal":               yesterday_ms,
            "Platform":              "Tiktok",
            "Nama Produk":           prod_name,
            "Item ID":               prod_id,
            "Kategori Produk":       "",
            "Harga Jual":            0,
            "Stok Tersisa":          safe_int(total_stock),
            "Terjual Hari Ini":      0,
            "Total Terjual Kumulatif": 0,
            "Rating Bintang":        avg_rating,
            "Total Review":          review_count,
            "Review Bintang 5":      0,
            "Review Bintang 4":      0,
            "Review Bintang 3":      0,
            "Review Bintang 2":      0,
            "Review Bintang 1":      0,
            "Review Negatif Baru":   0,
            "Views Produk":          0,
            "Status Boost":          "",
            "Ada Promo Aktif":       False,
            "Status Produk":         "",
            "Revenue Produk":        0,
            "CTR Listing":           "",
            "Conversion Rate":       "",
        })

    if records:
        for i in range(0, len(records), 500):
            result = lark_add_batch(TABLE_PRODUCT_PERF, records[i:i+500])
            print(f"✅ Product Performance (TikTok) {len(records[i:i+500])} produk!" if result.get("code") == 0 else "❌ Gagal")

def input_tiktok_financial(tiktok_data, yesterday: datetime):
    print("💰 Input Financial Summary (TikTok Shop)...")
    yesterday_ms = int(yesterday.timestamp() * 1000)
    transactions = tiktok_data.get("finance", [])
    gross_revenue  = 0
    biaya_platform = 0
    spend_iklan    = 0

    for txn in (transactions or []):
        if not isinstance(txn, dict):
            continue
        txn_type = safe_str(txn.get("transaction_type", txn.get("type", "")))
        amount = safe_int(float(txn.get("amount", 0) or 0) / 100)
        if txn_type in ("ORDER", "SALE", "SETTLEMENT", "RELEASED"):
            gross_revenue += amount
        elif txn_type in ("FEE", "COMMISSION", "SERVICE_FEE", "PLATFORM_FEE", "TRANSACTION_FEE"):
            biaya_platform += abs(amount)
        elif txn_type in ("ADS_FEE", "ADVERTISEMENT"):
            spend_iklan += abs(amount)
        elif txn_type in ("REFUND", "RETURN", "REVERSE"):
            gross_revenue -= abs(amount)

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
    print("🚨 Cek Alert Log (TikTok Shop)...")
    yesterday_ms = int(yesterday.timestamp() * 1000)
    orders        = tiktok_data.get("orders", [])
    order_details = tiktok_data.get("order_details", [])
    alerts        = []

    if len(orders) == 0:
        alerts.append({
            "Tanggal": yesterday_ms, "Platform": "Tiktok",
            "Tipe Alert": "Tidak Ada Order",
            "Detail": "Tidak ada order masuk di TikTok Shop kemarin.",
            "Nilai Saat Ini": 0, "Nilai Normal": 1,
            "Prioritas": "🟡 Penting", "Status": "Baru",
        })

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

    if not LARK_APP_ID or not LARK_APP_SECRET:
        raise Exception("❌ LARK_APP_ID atau LARK_APP_SECRET tidak ada!")
    get_lark_tenant_token()

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

    if not TIKTOK_APP_KEY or not TIKTOK_ACCESS_TOKEN or not TIKTOK_SHOP_ID:
        print("⚠️ TikTok credentials belum lengkap, skip TikTok Shop.")
    else:
        tiktok_data, yesterday = fetch_all_tiktok_data()

        print("\n📤 Menginput data TikTok ke Lark Base...")
        input_tiktok_daily_overview(tiktok_data, yesterday)
        input_tiktok_product_performance(tiktok_data, yesterday)
        input_tiktok_financial(tiktok_data, yesterday)
        input_tiktok_alerts(tiktok_data, yesterday)

    print("\n" + "=" * 60)
    print("✅ SELESAI! Semua data sudah masuk ke Lark Base.")
    print("=" * 60)

if __name__ == "__main__":
    main()
