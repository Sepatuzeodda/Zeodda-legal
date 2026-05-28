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

# Lark Table IDs
TABLE_DAILY_OVERVIEW = "tblSVQG08nHr7tXD"
TABLE_ALERT_LOG      = "tblobivbXf5KBsUK"

# Cache token
_lark_tenant_token = None

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
    except Exception:
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
# SHOPEE TOKEN AUTOMATION & REQUEST HELPERS
# ============================================================
def refresh_shopee_access_token():
    """Otomatis refresh access_token menggunakan refresh_token dari GitHub Secrets"""
    global SHOPEE_ACCESS_TOKEN
    if not SHOPEE_REFRESH_TOKEN:
        print("⚠️ SHOPEE_REFRESH_TOKEN kosong, mencoba jalan dengan ACCESS_TOKEN yang ada.")
        return False
        
    path = "/api/v2/auth/access_token/get"
    ts = int(time.time())
    base_string = f"{str(SHOPEE_PARTNER_ID)}{path}{str(ts)}"
    sign = hmac.new(SHOPEE_PARTNER_KEY.encode('utf-8'), base_string.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f"{SHOPEE_BASE_URL}{path}"
    params = {"partner_id": SHOPEE_PARTNER_ID, "timestamp": ts, "sign": sign}
    payload = {
        "refresh_token": SHOPEE_REFRESH_TOKEN.strip(),
        "partner_id": SHOPEE_PARTNER_ID,
        "shop_id": SHOPEE_SHOP_ID
    }
    
    try:
        r = requests.post(url, params=params, json=payload, timeout=30)
        res = r.json()
        if "access_token" in res:
            SHOPEE_ACCESS_TOKEN = res["access_token"]
            print("🔄 [Shopee] Access Token berhasil diperbarui via Refresh Token.")
            return True
        else:
            print(f"❌ [Shopee] Gagal refresh token otomatis: {res}")
            return False
    except Exception as e:
        print(f"❌ [Shopee] Error saat auto-refresh token: {e}")
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
        if "error" in data and data["error"] != "":
            print(f"  ⚠️ [{path}]: {data.get('error')} - {data.get('message')}")
            return {}
        resp = data.get("response")
        return resp if isinstance(resp, dict) else {}
    except Exception as e:
        print(f"❌ Request error {path}: {e}")
        return {}

# ============================================================
# LARK BASE ENGINE & ANTI-DUPLICATE
# ============================================================
def get_lark_tenant_token() -> str:
    global _lark_tenant_token
    if _lark_tenant_token:
        return _lark_tenant_token
    url = f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
    try:
        r = requests.post(url, json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}, timeout=30)
        data = r.json()
        if data.get("code") != 0:
            raise Exception(f"Gagal get tenant token: {data.get('msg')}")
        _lark_tenant_token = data["tenant_access_token"]
        return _lark_tenant_token
    except Exception as e:
        raise Exception(f"❌ get_lark_tenant_token error: {e}")

def get_lark_headers():
    return {
        "Authorization": f"Bearer {get_lark_tenant_token()}",
        "Content-Type": "application/json",
    }

def lark_delete_duplicates(table_id, timestamp_ms, platform_name):
    """Mencari dan membersihkan data duplikat berdasarkan Tanggal & Platform sebelum insert"""
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
            if items:
                print(f"♻️  Ditemukan {len(items)} baris duplikat lama untuk {platform_name}. Membersihkan...")
                for item in items:
                    record_id = item.get("record_id")
                    del_url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/{record_id}"
                    requests.delete(del_url, headers=get_lark_headers(), timeout=30)
                print(f"✅ Pembersihan duplikat selesai.")
    except Exception as e:
        print(f"⚠️ Gagal menjalankan pengecekan duplikat Lark: {e}")

def lark_add(table_id, fields):
    if "Tanggal" in fields and "Platform" in fields:
        lark_delete_duplicates(table_id, fields["Tanggal"], fields["Platform"])

    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records"
    try:
        r = requests.post(url, headers=get_lark_headers(), json={"fields": fields}, timeout=30)
        return r.json()
    except Exception as e:
        print(f"❌ Lark request error: {e}")
        return {"code": -1}

def lark_add_batch(table_id, records_list):
    if not records_list:
        return {"code": 0}
    
    sample = records_list[0]
    if "Tanggal" in sample and "Platform" in sample:
        lark_delete_duplicates(table_id, sample["Tanggal"], sample["Platform"])

    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{table_id}/records/batch_create"
    try:
        r = requests.post(url, headers=get_lark_headers(), json={"records": [{"fields": f} for f in records_list]}, timeout=30)
        return r.json()
    except Exception as e:
        print(f"❌ Lark batch error: {e}")
        return {"code": -1}

# ============================================================
# PULL DATA FROM SHOPEE PRODUCTION (H-1 TIMELINE)
# ============================================================
def fetch_all_shopee_data():
    print("📥 Mengambil semua data Shopee Jalur Production...")
    refresh_shopee_access_token()
    
    # Konfigurasi penanggalan akurat H-1 (Kemarin penuh)
    yesterday = datetime.now() - timedelta(days=1)
    date_str_yesterday = yesterday.strftime("%Y-%m-%d")
    
    ts_start_yesterday = int(yesterday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    ts_end_yesterday   = ts_start_yesterday + 86399  # Selesai jam 23:59:59
    
    yesterday_ms = int(yesterday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    data = {}
    
    # 1. Endpoint Real-time Toko & Saldo
    data["shop_info"]   = shopee_get("/api/v2/shop/get_shop_info")
    data["balance"]     = shopee_get("/api/v2/ads/get_total_balance")
    
    # FIX ENDPOINT: Menggunakan struktur modul resmi /account_health/ untuk Production
    data["shop_perf"]   = shopee_get("/api/v2/account_health/get_shop_performance")
    data["penalty"]     = shopee_get("/api/v2/account_health/get_penalty_point_history")
    data["late_orders"] = shopee_get("/api/v2/account_health/get_late_orders")
    data["issues"]      = shopee_get("/api/v2/account_health/get_listings_with_issues")
    
    # 2. Data Transaksi Rentang Waktu H-1
    data["orders"] = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time", "time_from": ts_start_yesterday, "time_to": ts_end_yesterday, "page_size": 100,
    })
    data["cancelled_orders"] = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time", "time_from": ts_start_yesterday, "time_to": ts_end_yesterday, "page_size": 100, "order_status": "CANCELLED",
    })
    
    # FIX ENDPOINT: Jalur resmi penarikan retur v2 menggunakan /returns/
    data["returns"] = shopee_get("/api/v2/returns/get_return_list", {
        "page_no": 1, "page_size": 100, "create_time_from": ts_start_yesterday, "create_time_to": ts_end_yesterday,
    })
    
    # 3. Data Finansial Pendapatan & Iklan Kemarin (H-1)
    data["income"] = shopee_get("/api/v2/payment/get_income_overview", {
        "start_date": date_str_yesterday, "end_date": date_str_yesterday,
    })
    data["ads"] = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {
        "start_date": date_str_yesterday, "end_date": date_str_yesterday,
    })
    
    print(f"✅ Seluruh data Shopee Production untuk tanggal {date_str_yesterday} berhasil dikumpulkan.")
    return data, yesterday_ms

# ============================================================
# INTEGRASI KE LARK BASE
# ============================================================
def input_daily_overview(d, yesterday_ms):
    print("📋 Memproses input data ke tabel Daily Overview Lark Base...")
    
    shop_perf    = safe_dict(d, "shop_perf")
    overall_perf = safe_dict(shop_perf, "overall_performance")
    income       = safe_dict(d, "income")
    shop_info    = safe_dict(d, "shop_info")
    penalty      = safe_dict(d, "penalty")
    late_orders  = safe_dict(d, "late_orders")
    issues       = safe_dict(d, "issues")
    balance      = safe_dict(d, "balance")

    all_orders       = safe_list(d.get("orders", {}), "order_list")
    cancelled_orders = safe_list(d.get("cancelled_orders", {}), "order_list")
    returns_list     = safe_list(d.get("returns", {}), "return_list")

    # Mapping aman agar tipe ribuan koma (,) Excel Lark Base terproses sebagai angka murni
    fields = {
        "Tanggal":                yesterday_ms,
        "Platform":               "Shopee",
        "Total Order Masuk":      safe_int(len(all_orders)),
        "Total Order Dibatalkan": safe_int(len(cancelled_orders)),
        "Total Retur":            safe_int(len(returns_list)),
        "Omzet Harian":           safe_int((income.get("total_income") or {}).get("released_amount", 0)),
        "Omzet Gross":            safe_int((income.get("total_income") or {}).get("released_amount", 0)),
        "Follower Toko":          safe_int(shop_info.get("follower_count", 0)),
        "Skor Performa Toko":     safe_int(overall_perf.get("rating", 0)),
        "Poin Penalti":           safe_int(penalty.get("total_penalty_point", 0)),
        "Order Terlambat":        safe_int(late_orders.get("total_count", 0)),
        "Produk Bermasalah":      safe_int(issues.get("total_count", 0)),
        "Saldo Iklan":            safe_int(balance.get("total_balance", 0)),
    }

    print(f"📤 [DEBUG LARK] Mengirim data payload ke Lark Base: {fields}")
    result = lark_add(TABLE_DAILY_OVERVIEW, fields)
    print(f"📥 [DEBUG LARK] Respon balik dari Lark Base API: {result}")

def input_alerts(d, yesterday_ms):
    print("🚨 Memeriksa ambang batas anomali untuk pembuatan Alert Log...")
    balance  = safe_dict(d, "balance")
    income   = safe_dict(d, "income")
    alerts   = []

    saldo = safe_int(balance.get("total_balance", 0))
    if saldo < 100000:
        alerts.append({
            "Tanggal": yesterday_ms, "Platform": "Shopee",
            "Tipe Alert": "Iklan Hampir Habis",
            "Detail": f"Saldo iklan kritis Rp {saldo:,} — segera lakukan top up!",
            "Nilai Saat Ini": saldo, "Nilai Normal": 100000,
            "Prioritas": "High", "Status": "Open",
        })

    omzet_gross = safe_int((income.get("total_income") or {}).get("released_amount", 0))
    all_orders = safe_list(d.get("orders", {}), "order_list")
    
    if len(all_orders) > 0 and omzet_gross == 0:
        alerts.append({
            "Tanggal": yesterday_ms, "Platform": "Shopee",
            "Tipe Alert": "Omzet Gross 0",
            "Detail": f"Ada {len(all_orders)} order masuk kemarin, tapi omzet gross tercatat 0. Periksa status pelepasan dana API.",
            "Nilai Saat Ini": 0, "Nilai Normal": 1,
            "Prioritas": "High", "Status": "Open",
        })

    if alerts:
        result = lark_add_batch(TABLE_ALERT_LOG, alerts)
        print(f"🤖 [DEBUG ALERT] Respon penulisan Alert Log ke Lark Base: {result}")
    else:
        print("✅ Kondisi operasional toko normal, tidak ada alert baru hari ini.")

# ============================================================
# MAIN ORCHESTRATOR
# ============================================================
def main():
    print("=" * 60)
    print(f"🚀 ZEODDA SYSTEM AUTOMATION — START CONTROL")
    print("=" * 60)

    if not LARK_APP_ID or not LARK_APP_SECRET:
        raise Exception("❌ Environment Variable LARK_APP_ID atau LARK_APP_SECRET belum dikonfigurasi!")
        
    # Inisialisasi token Lark Base
    get_lark_tenant_token()

    # Eksekusi proses penarikan data produksi Shopee
    shopee_data, target_date_ms = fetch_all_shopee_data()

    # Push data bersih ke Lark Base
    input_daily_overview(shopee_data, target_date_ms)
    input_alerts(shopee_data, target_date_ms)

    print("=" * 60)
    print("✅ ZEODDA SYSTEM AUTOMATION — DONE WORKFLOW SUCCESS")
    print("=" * 60)

if __name__ == "__main__":
    main()
