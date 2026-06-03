import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timedelta, timezone

# Konfigurasi Kredensial Environment Shopee & Lark Core
SHOPEE_PARTNER_ID      = int(os.environ.get("SHOPEE_PARTNER_ID") or "2035358")
SHOPEE_PARTNER_KEY     = os.environ.get("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_BASE_URL        = "https://partner.shopeemobile.com"
LARK_APP_ID            = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET        = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN         = "ItPfb0MPNaD6KhsVc65lT6p1gTh"
LARK_BASE_URL          = "https://open.larksuite.com"

# Definisi ID Tabel Riil Lark Base Zeodda
TABLE_GMS_CONTROL      = "tbl28sCpu1ZtR73l"      # Nama di Lark: Ads Control
TABLE_ADS_PERFORMANCE  = "tblx5PwfnB8Oi7lf"      # Nama di Lark: Performa Ads

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
    # Mengambil konfigurasi target ROAS dari tabel Ads Control (tbl28sCpu1ZtR73l)
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_GMS_CONTROL}/records/search"
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "Status Sync", "operator": "is", "value": ["Success"]}
            ]
        }
    }
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
    except Exception as e:
        print(f"  ⚠️ Gagal mengambil data referensi Target ROAS dari Lark: {e}")
        return {}

def batch_push_to_lark(records):
    # Kirim kumpulan data performa harian ke tabel Performa Ads (tblx5PwfnB8Oi7lf)
    if not records: return
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_ADS_PERFORMANCE}/records/batch_create"
    try:
        r = requests.post(url, headers=lark_headers(), json={"records": records}, timeout=30)
        res = r.json()
        if res.get("code") != 0:
            print(f"  ❌ Lark Error: {res.get('msg')}")
    except Exception as e:
        print(f"  ❌ Gagal push batch ke Lark: {e}")

def pull_shop_ads_with_target(shop_id, target_mapping):
    token = get_active_token_for_shop(shop_id)
    if not token: return

    # Ambil daftar ID produk berstatus normal di toko
    item_resp = shopee_get("/api/v2/product/get_item_list", shop_id, token, {"page_size": 50, "item_status": "NORMAL"})
    if not item_resp: return
    items = item_resp.get("item", [])
    if not items: return

    # Ambil rentang waktu data kemarin (H-1)
    kemarin = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    lark_records = []

    for item in items:
        item_id = item["item_id"]
        
        # Ambil data statistik dari Shopee API Ads
        ads_resp = shopee_get("/api/v2/ads/get_product_campaign_daily_performance", shop_id, token, {
            "item_id": item_id,
            "start_date": kemarin,
            "end_date": kemarin
        })
        
        if not ads_resp or not ads_resp.get("performance_data"):
            continue
            
        ads_data = ads_resp["performance_data"][0]
        
        # Ambil setelan target ROAS dari mapping tabel kontrol, default 0.0 jika tidak ada
        set_roas_val = target_mapping.get(str(item_id), 0.0)
        
        # Konversi desimal dengan pemisah koma (,) untuk kebutuhan standardisasi Excel
        target_roas_str = f"{set_roas_val:.2f}".replace(".", ",")
        realisasi_roas_str = f"{ads_data.get('roi', 0.0):.2f}".replace(".", ",")
        ctr_str = f"{ads_data.get('ctr', 0.0) * 100:.2f}".replace(".", ",")

        # Susun payload data harian
        record = {
            "fields": {
                "Tanggal Data": kemarin,
                "Shop ID": int(shop_id),
                "ID Produk": str(item_id),
                "Impresi": ads_data.get("impression", 0),
                "Klik": ads_data.get("click", 0),
                "Biaya Iklan": ads_data.get("cost", 0),
                "Order Dihasilkan": ads_data.get("order", 0),
                "GMV Iklan": ads_data.get("gmv", 0),
                "CTR Iklan (%)": ctr_str,
                "Target ROAS (Set ROAS)": target_roas_str,
                "ROAS Realisasi": realisasi_roas_str
            }
        }
        lark_records.append(record)

    if lark_records:
        batch_push_to_lark(lark_records)
        print(f"  ✅ Toko {shop_id}: {len(lark_records)} log histori iklan berhasil disimpan.")

def main():
    print("🚀 Pull Daily Ads Performance — START")
    if not LARK_APP_ID or not LARK_APP_SECRET: return
    
    print("🔄 Mengambil data referensi Set ROAS dari tabel Ads Control...")
    target_mapping = get_target_roas_from_lark()
    
    # 7 Toko Cabang Aktif Zeodda (Sesuaikan / ganti isi array dengan Shop ID riil Anda)
    shop_list = [2035358, 112233, 445566, 778899] 
    for shop_id in shop_list:
        pull_shop_ads_with_target(shop_id, target_mapping)
        
    print("✅ Pull Daily Ads Performance — DONE")

if __name__ == "__main__":
    main()
