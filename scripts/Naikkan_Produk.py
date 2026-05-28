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
        print(f"✅ Lark tenant token OK")
        return _lark_tenant_token
    except Exception as e:
        raise Exception(f"❌ get_lark_tenant_token error: {e}")

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
        if data.get("error") and data.get("error") != "":
            print(f"  ⚠️ Shopee API error [{path}]: {data.get('error')} - {data.get('message','')[:80]}")
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
            print(f"🔍 Fields: {fields}")
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

    # Ambil data KEMARIN (H-1) — script jalan jam 00:00 WIB
    now_wib       = datetime.utcnow() + timedelta(hours=7)
    yesterday_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    ts_start      = int((yesterday_wib - timedelta(hours=7)).timestamp())
    ts_end        = int((yesterday_wib + timedelta(hours=17) - timedelta(seconds=1)).timestamp())
    date_str      = yesterday_wib.strftime("%Y-%m-%d")
    yesterday_ms  = int(yesterday_wib.timestamp() * 1000)

    print(f"📅 Data kemarin: {date_str} WIB")

    d = {
        "yesterday_ms": yesterday_ms,
        "date_str":     date_str,
        "ts_start":     ts_start,
        "ts_end":       ts_end,
    }

    # === SHOP ===
    d["shop_info"]  = shopee_get("/api/v2/shop/get_shop_info")
    print(f"  shop_info keys: {list(d['shop_info'].keys()) if d['shop_info'] else 'EMPTY'}")

    # === ACCOUNT HEALTH ===
    d["shop_perf"]   = shopee_get("/api/v2/account_health/get_shop_performance")
    d["penalty"]     = shopee_get("/api/v2/account_health/get_penalty_point_history")
    d["late_orders"] = shopee_get("/api/v2/account_health/get_late_orders")
    d["issues"]      = shopee_get("/api/v2/account_health/get_listings_with_issues")

    # === ADS ===
    # Format tanggal untuk Ads API: DD-MM-YYYY (beda dengan Payment yang YYYY-MM-DD)
    date_str_dmy = yesterday_wib.strftime("%d-%m-%Y")

    d["date_str_dmy"] = date_str_dmy

    d["balance"] = shopee_get("/api/v2/ads/get_total_balance")
    d["ads"]     = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {
        "start_date": date_str_dmy, "end_date": date_str_dmy,
    })
    d["toggle"]  = shopee_get("/api/v2/ads/get_shop_toggle_info")

    # === ORDERS ===
    d["orders"] = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from": ts_start, "time_to": ts_end, "page_size": 100,
    })
    d["cancelled_orders"] = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from": ts_start, "time_to": ts_end,
        "page_size": 100, "order_status": "CANCELLED",
    })

    # === RETURNS ===
    d["returns"] = shopee_get("/api/v2/returns/get_return_list", {
        "page_no": 1, "page_size": 100,
        "create_time_from": ts_start, "create_time_to": ts_end,
    })

    # === PAYMENT / FINANCIAL ===
    d["income"]  = shopee_get("/api/v2/payment/get_income_overview", {
        "start_date": date_str, "end_date": date_str,
    })
    d["payout"]  = shopee_get("/api/v2/payment/get_payout_info", {
        "page_size": 20, "page_no": 1,
    })
    d["escrow"]  = shopee_get("/api/v2/payment/get_escrow_list", {
        "release_time_from": ts_start, "release_time_to": ts_end,
        "page_no": 1, "page_size": 100,
    })
    d["billing"] = shopee_get("/api/v2/payment/get_billing_transaction_info", {
        "create_time_from": ts_start, "create_time_to": ts_end,
        "page_size": 100, "cursor": "",
    })

    # === PRODUK — ambil semua item aktif ===
    items_resp = shopee_get("/api/v2/product/get_item_list", {
        "offset": 0, "page_size": 50, "item_status": "NORMAL",
    })
    d["items"] = items_resp.get("item", []) if isinstance(items_resp, dict) else []
    item_ids   = [str(i.get("item_id")) for i in d["items"] if i.get("item_id")]

    # Boosted items
    boosted_resp = shopee_get("/api/v2/product/get_boosted_list")
    boosted_ids  = set()
    if isinstance(boosted_resp, dict):
        for bi in (boosted_resp.get("item_list") or []):
            if isinstance(bi, dict):
                boosted_ids.add(str(bi.get("item_id", "")))
    d["boosted_ids"] = boosted_ids
    print(f"  Boosted items: {len(boosted_ids)}")

    # === OMZET dari order detail (include ongkir = buyer_paid_amount) ===
    all_orders    = safe_list(d.get("orders", {}), "order_list")
    order_sn_list = [o.get("order_sn") for o in all_orders if o.get("order_sn")]

    omzet_harian = 0  # exclude ongkir
    omzet_gross  = 0  # include ongkir (= Seller Center)

    if order_sn_list:
        print(f"  → Detail {len(order_sn_list)} order...")
        for i in range(0, len(order_sn_list), 50):
            batch       = order_sn_list[i:i+50]
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
                buyer_paid    = od.get("buyer_paid_amount", 0)
                if buyer_paid:
                    omzet_gross += safe_int(buyer_paid)
                else:
                    omzet_gross += safe_int(od.get("total_amount", 0)) + safe_int(od.get("actual_shipping_fee", 0))

    d["omzet_harian"] = omzet_harian
    d["omzet_gross"]  = omzet_gross

    print(f"💰 Omzet (excl ongkir): Rp {omzet_harian:,} | Gross (incl ongkir): Rp {omzet_gross:,}")
    print(f"  Balance: Rp {safe_int(d['balance'].get('total_balance',0)):,}")
    print("✅ Data Shopee OK!")
    return d

# ============================================================
# FETCH DATA PER PRODUK (dipanggil sekali, dipakai banyak tabel)
# ============================================================

def fetch_product_details(d):
    """
    Fetch detail semua produk: base_info, extra_info, comment, promotion, ads perf, ams perf.
    Return dict keyed by item_id (string).
    """
    items    = d.get("items", [])
    date_str = d["date_str"]
    ts_start = d["ts_start"]
    ts_end   = d["ts_end"]

    if not items:
        return {}

    item_ids = [str(i.get("item_id")) for i in items if i.get("item_id")]
    print(f"  → Fetch detail {len(item_ids)} produk...")

    # --- Base info (batch, max 50) ---
    base_map = {}
    for i in range(0, len(item_ids), 50):
        batch = item_ids[i:i+50]
        resp  = shopee_get("/api/v2/product/get_item_base_info", {
            "item_id_list": ",".join(batch),
        })
        for item in (resp.get("item_list", []) or []):
            if isinstance(item, dict):
                base_map[str(item.get("item_id", ""))] = item

    # --- Extra info (stok, terjual, views) ---
    extra_map = {}
    for i in range(0, len(item_ids), 50):
        batch = item_ids[i:i+50]
        resp  = shopee_get("/api/v2/product/get_item_extra_info", {
            "item_id_list": ",".join(batch),
        })
        for item in (resp.get("item_list", []) or []):
            if isinstance(item, dict):
                extra_map[str(item.get("item_id", ""))] = item

    # --- Promotion: pakai get_discount_list (bukan get_item_promotion yg butuh mpsku) ---
    promo_set = set()
    promo_resp = shopee_get("/api/v2/discount/get_discount_list", {
        "discount_status": "ongoing",
        "page_no": 1, "page_size": 100,
    })
    for disc in (promo_resp.get("discount_list", []) or []):
        if not isinstance(disc, dict):
            continue
        for it in (disc.get("item_list", []) or []):
            if isinstance(it, dict):
                promo_set.add(str(it.get("item_id", "")))
    print(f"  Produk promo aktif: {len(promo_set)}")

    # --- Comment/Review per produk ---
    comment_map = {}
    for iid in item_ids[:20]:
        resp     = shopee_get("/api/v2/product/get_comment", {
            "item_id": int(iid), "cursor": "", "page_size": 100,
        })
        comments = resp.get("comment_list", []) if isinstance(resp, dict) else []
        if not isinstance(comments, list):
            comments = []
        star = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for c in comments:
            if isinstance(c, dict):
                rv = safe_int(c.get("rating_star", 0))
                if rv in star:
                    star[rv] += 1
        total    = len(comments)
        avg      = sum(k * v for k, v in star.items()) // total if total else 0
        comment_map[iid] = {"star": star, "total": total, "avg": avg}

    # --- AMS: SKIP — butuh permission tambahan di Shopee Console ---
    # Aktifkan setelah centang AMS permission di App Management
    ams_map = {}
    # for iid in item_ids[:20]:
    #     resp = shopee_get("/api/v2/ams/get_product_performance", {...})
    #     if isinstance(resp, dict): ams_map[iid] = resp

    # --- Ads Product Level: campaign per produk ---
    date_str_dmy = d.get("date_str_dmy", date_str)  # DD-MM-YYYY untuk Ads API
    camp_resp = shopee_get("/api/v2/ads/get_product_level_campaign_id_list", {
        "start_date": date_str_dmy, "end_date": date_str_dmy,
    })
    camp_ids = []
    if isinstance(camp_resp, dict):
        camp_ids = camp_resp.get("campaign_id_list", []) or []

    ads_perf_map = {}  # keyed by campaign_id
    camp_setting_map = {}
    if camp_ids:
        for i in range(0, len(camp_ids), 50):
            batch = camp_ids[i:i+50]
            # Performa harian
            perf_resp = shopee_get("/api/v2/ads/get_product_campaign_daily_performance", {
                "start_date": date_str_dmy, "end_date": date_str_dmy,
                "campaign_id_list": ",".join(str(c) for c in batch),
            })
            for cp in (perf_resp.get("campaign_performance_list", []) or []):
                if isinstance(cp, dict):
                    ads_perf_map[str(cp.get("campaign_id", ""))] = cp
            # Setting (status, bid)
            setting_resp = shopee_get("/api/v2/ads/get_product_level_campaign_setting_info", {
                "campaign_id_list": ",".join(str(c) for c in batch),
            })
            for cs in (setting_resp.get("campaign_setting_list", []) or []):
                if isinstance(cs, dict):
                    camp_setting_map[str(cs.get("campaign_id", ""))] = cs

    return {
        "base":         base_map,
        "extra":        extra_map,
        "promo_set":    promo_set,
        "comment":      comment_map,
        "ams":          ams_map,
        "camp_ids":     camp_ids,
        "ads_perf":     ads_perf_map,
        "camp_setting": camp_setting_map,
    }

# ============================================================
# INPUT KE LARK BASE
# ============================================================

def input_daily_overview(d):
    print("📋 Input Daily Overview...")

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

    follower = safe_int(shop_info.get("follower_count", 0))
    print(f"  follower_count raw: {shop_info.get('follower_count')} → {follower}")

    fields = {
        "Tanggal":                d["yesterday_ms"],
        "Platform":               "Shopee",
        "Total Order Masuk":      safe_int(len(all_orders)),
        "Total Order Dibatalkan": safe_int(len(cancelled_orders)),
        "Total Retur":            safe_int(len(returns_list)),
        "Omzet Harian":           safe_int(d.get("omzet_harian", 0)),
        "Omzet Gross":            safe_int(d.get("omzet_gross", 0)),
        "Follower Toko":          follower,
        "Skor Performa Toko":     safe_int(overall_perf.get("rating", 0)),
        "Poin Penalti":           safe_int(penalty.get("total_penalty_point", 0)),
        "Order Terlambat":        safe_int(late_orders.get("total_count", 0)),
        "Produk Bermasalah":      safe_int(issues.get("total_count", 0)),
        "Saldo Iklan":            safe_int(balance.get("total_balance", 0)),
    }

    result = lark_add(TABLE_DAILY_OVERVIEW, fields)
    if result.get("code") == 0:
        print(f"✅ Daily Overview OK — {len(all_orders)} order, Rp {d.get('omzet_gross',0):,} gross")
    else:
        print("❌ Gagal Daily Overview")


def input_product_performance(d, pd):
    print("⭐ Input Product Performance...")
    items    = d.get("items", [])
    boosted  = d.get("boosted_ids", set())
    if not items:
        print("⚠️ Tidak ada produk, skip.")
        return

    REVIEW_FIELD = {
        5: "Review Bintang 5 ⭐⭐⭐⭐⭐",
        4: "Review Bintang 4 ⭐⭐⭐⭐",
        3: "Review Bintang 3 ⭐⭐⭐",
        2: "Review Bintang 2 ⭐⭐",
        1: "Review Bintang 1 ⭐",
    }

    records = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        iid       = str(item.get("item_id", ""))
        base      = pd["base"].get(iid, {})
        extra     = pd["extra"].get(iid, {})
        cmt       = pd["comment"].get(iid, {"star": {1:0,2:0,3:0,4:0,5:0}, "total":0, "avg":0})
        has_promo = iid in pd["promo_set"]
        is_boost  = iid in boosted

        # Nama & harga dari base
        nama   = safe_str(base.get("item_name", item.get("item_name", "")))
        models = base.get("model", []) or []
        harga  = 0
        for m in models:
            if not isinstance(m, dict):
                continue
            pi = m.get("price_info", [])
            if pi and isinstance(pi, list):
                harga = safe_int(pi[0].get("current_price", 0))
                break

        # Stok, terjual, views dari extra_info
        stok             = safe_int(extra.get("total_available_stock", 0))
        terjual_hari_ini = safe_int(extra.get("sold", 0))        # sold hari ini
        total_terjual    = safe_int(extra.get("overall_sold", 0)) # kumulatif
        views            = safe_int(extra.get("page_view", 0))

        # Status dari base
        status_produk = safe_str(base.get("item_status", ""))

        star  = cmt["star"]
        total = cmt["total"]
        avg   = cmt["avg"]

        records.append({
            "Tanggal":                    d["yesterday_ms"],
            "Platform":                   "Shopee",
            "Nama Produk":                nama,
            "Item ID":                    iid,
            "Kategori Produk":            "",
            "Harga Jual":                 harga,
            "Stok Tersisa":               stok,
            "Terjual Hari Ini":           terjual_hari_ini,
            "Total Terjual Kumulatif":    total_terjual,
            "Rating Bintang":             safe_int(avg),
            "Total Review":               safe_int(total),
            REVIEW_FIELD[5]:              safe_int(star.get(5, 0)),
            REVIEW_FIELD[4]:              safe_int(star.get(4, 0)),
            REVIEW_FIELD[3]:              safe_int(star.get(3, 0)),
            REVIEW_FIELD[2]:              safe_int(star.get(2, 0)),
            REVIEW_FIELD[1]:              safe_int(star.get(1, 0)),
            "Review Negatif Baru":        safe_int(star.get(1,0) + star.get(2,0)),
            "Views Produk":               views,
            "Status Boost":               "Aktif" if is_boost else "Tidak Aktif",
            "Ada Promo Aktif":            has_promo,
            "Status Produk":              status_produk,
            "Revenue Produk":             0,
            "CTR Listing":                "",
            "Conversion Rate":            "",
        })

    if records:
        result = lark_add_batch(TABLE_PRODUCT_PERF, records)
        print(f"✅ Product Performance {len(records)} produk!" if result.get("code") == 0 else "❌ Gagal")


def input_ads_shop(d):
    print("📢 Input Ads Shop Level...")
    ads     = safe_dict(d, "ads")
    balance = safe_dict(d, "balance")
    toggle  = safe_dict(d, "toggle")

    fields = {
        "Tanggal":                d["yesterday_ms"],
        "Platform":               "Shopee Ads",
        "Saldo Iklan":            safe_int(balance.get("total_balance", 0)),
        "Total Spend":            safe_int(ads.get("cost", 0)),
        "Total Impresi":          safe_int(ads.get("impression", 0)),
        "Total Klik":             safe_int(ads.get("click", 0)),
        "Total Order dari Iklan": safe_int(ads.get("order", 0)),
        "Revenue dari Iklan":     safe_int(ads.get("order_amount", 0)),
        "Toggle Iklan Aktif":     toggle.get("toggle_status") == 1,
    }
    result = lark_add(TABLE_ADS_SHOP, fields)
    print("✅ Ads Shop Level OK!" if result.get("code") == 0 else "❌ Gagal Ads Shop")


def input_ads_product_level(d, pd):
    print("🎯 Input Ads Product Level...")

    camp_ids    = pd.get("camp_ids", [])
    ads_perf    = pd.get("ads_perf", {})
    camp_setting= pd.get("camp_setting", {})

    if not camp_ids:
        print("⚠️ Tidak ada campaign produk, skip.")
        return

    records = []
    for cid in [str(c) for c in camp_ids]:
        perf    = ads_perf.get(cid, {})
        setting = camp_setting.get(cid, {})
        if not perf:
            continue

        status_raw = safe_str(setting.get("campaign_status", perf.get("campaign_status", "")))
        # Normalize status ke Single Select options: Aktif, Pause, Habis
        status_map = {
            "ongoing": "Aktif", "active": "Aktif",
            "paused": "Pause",  "pause": "Pause",
            "ended": "Habis",   "expired": "Habis",
        }
        status = status_map.get(status_raw.lower(), status_raw)

        records.append({
            "Tanggal":            d["yesterday_ms"],
            "Platform":           "Shopee Ads",
            "Nama Produk":        safe_str(perf.get("campaign_name", setting.get("campaign_name", ""))),
            "Campaign ID":        cid,
            "Spend":              safe_int(perf.get("cost", 0)),
            "Impresi":            safe_int(perf.get("impression", 0)),
            "Klik":               safe_int(perf.get("click", 0)),
            "Order dari Iklan":   safe_int(perf.get("order", 0)),
            "Revenue dari Iklan": safe_int(perf.get("order_amount", 0)),
            "Status Campaign":    status,
            "Rekomendasi Bid":    safe_int(setting.get("bid", 0)),
        })

    if records:
        result = lark_add_batch(TABLE_ADS_PRODUCT, records)
        print(f"✅ Ads Product Level {len(records)} campaign!" if result.get("code") == 0 else "❌ Gagal")
    else:
        print("⚠️ Tidak ada data performa campaign.")


def input_komparasi_produk(d, pd):
    print("📊 Input Komparasi Produk...")
    items = d.get("items", [])
    if not items:
        print("⚠️ Tidak ada produk, skip.")
        return

    records = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        iid      = str(item.get("item_id", ""))
        base     = pd["base"].get(iid, {})
        cmt      = pd["comment"].get(iid, {"avg": 0})
        ams      = pd["ams"].get(iid, {})
        is_boost = iid in d.get("boosted_ids", set())
        nama     = safe_str(base.get("item_name", item.get("item_name", "")))

        records.append({
            "Tanggal":            d["yesterday_ms"],
            "Nama Produk":        nama,
            "Platform":           "Shopee",
            "Rating Bintang":     safe_int(cmt.get("avg", 0)),
            "Terjual Organik":    safe_int(ams.get("sold_count", 0)),
            "Revenue Organik":    safe_int(ams.get("order_amount", 0)),
            "Terjual dari Iklan": 0,   # dari Ads Product Level
            "Revenue dari Iklan": 0,
            "Spend Iklan":        0,
            "Status Boost":       "Aktif" if is_boost else "Tidak Aktif",
            "Rekomendasi":        "",
        })

    if records:
        result = lark_add_batch(TABLE_KOMPARASI, records)
        print(f"✅ Komparasi {len(records)} produk!" if result.get("code") == 0 else "❌ Gagal Komparasi")


def input_financial(d):
    print("💰 Input Financial Summary...")

    income  = safe_dict(d, "income")
    ads     = safe_dict(d, "ads")
    payout  = safe_dict(d, "payout")
    escrow  = safe_dict(d, "escrow")
    billing = safe_dict(d, "billing")
    returns = safe_dict(d, "returns")

    # Biaya platform dari billing transactions
    biaya = 0
    for txn in (billing.get("transactions", []) or []):
        if isinstance(txn, dict):
            biaya += safe_int(abs(float(txn.get("amount", 0) or 0)))

    # Escrow pending
    escrow_total = safe_int(escrow.get("total_escrow_amount", 0))

    # Pencairan hari ini
    pencairan = safe_int(payout.get("total_payout_amount", 0))

    # Total retur (nilai)
    returns_list = safe_list(d.get("returns", {}), "return_list")
    total_retur_val = sum(safe_int(r.get("refund_amount", 0)) for r in returns_list if isinstance(r, dict))

    fields = {
        "Tanggal":              d["yesterday_ms"],
        "Platform":             "Shopee",
        "Gross Revenue":        safe_int(d.get("omzet_gross", 0)),
        "Biaya Platform":       biaya if biaya else safe_int((income.get("escrow_amount") or {}).get("released_amount", 0)),
        "Spend Iklan":          safe_int(ads.get("cost", 0)),
        "Dana Escrow Pending":  escrow_total,
        "Pencairan Hari Ini":   pencairan,
        "Total Retur":          total_retur_val,
    }

    result = lark_add(TABLE_FINANCIAL, fields)
    print("✅ Financial OK!" if result.get("code") == 0 else "❌ Gagal Financial")


def input_alerts(d):
    print("🚨 Cek Alert Log...")
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
            "Detail": f"Toko kena {pen} poin penalti!",
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
        print(f"✅ {len(alerts)} alert dibuat!" if result.get("code") == 0 else "❌ Gagal Alert")
    else:
        print("✅ Tidak ada alert.")

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

    # Ambil semua data Shopee
    shopee_data = fetch_all_shopee_data()

    # Fetch detail produk sekali, dipakai 3 tabel sekaligus
    print("\n🔍 Fetch detail produk...")
    product_details = fetch_product_details(shopee_data)

    # Input ke semua tabel
    print("\n📤 Input ke Lark Base...")
    input_daily_overview(shopee_data)
    input_product_performance(shopee_data, product_details)
    input_ads_shop(shopee_data)
    input_ads_product_level(shopee_data, product_details)
    input_komparasi_produk(shopee_data, product_details)
    input_financial(shopee_data)
    input_alerts(shopee_data)

    print("\n" + "=" * 60)
    print("✅ SELESAI!")
    print("=" * 60)

if __name__ == "__main__":
    main()
