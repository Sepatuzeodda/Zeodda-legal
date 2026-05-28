import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timezone

# ============================================================
# CONFIG - SHOPEE
# ============================================================
SHOPEE_PARTNER_ID    = int(os.environ.get("SHOPEE_PARTNER_ID", "2035358"))
SHOPEE_PARTNER_KEY   = os.environ.get("SHOPEE_PARTNER_KEY", "")
SHOPEE_SHOP_ID       = int(os.environ.get("SHOPEE_SHOP_ID", "963980234"))
SHOPEE_ACCESS_TOKEN  = os.environ.get("SHOPEE_ACCESS_TOKEN", "")
SHOPEE_REFRESH_TOKEN = os.environ.get("SHOPEE_REFRESH_TOKEN", "")
SHOPEE_BASE_URL      = "https://partner.shopeemobile.com"

# ============================================================
# CONFIG - LARK
# ============================================================
LARK_APP_ID     = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN  = "ItPfb0MPNaD6KhsVc65lT6p1gTh"
LARK_BASE_URL   = "https://open.larksuite.com"

TABLE_BOOST     = "tblzcjLMZX2KZ4aW"

MAX_BOOST       = 5   # Shopee max 5 produk per boost

_lark_tenant_token = None

# ============================================================
# HELPERS
# ============================================================
def safe_int(val):
    if val is None or isinstance(val, (dict, list)):
        return 0
    try:
        return int(float(str(val)))
    except:
        return 0

def refresh_shopee_access_token():
    global SHOPEE_ACCESS_TOKEN
    if not SHOPEE_REFRESH_TOKEN:
        print("⚠️ SHOPEE_REFRESH_TOKEN kosong.")
        return False
    path = "/api/v2/auth/access_token/get"
    ts   = int(time.time())
    sign = hmac.new(
        SHOPEE_PARTNER_KEY.encode(),
        f"{SHOPEE_PARTNER_ID}{path}{ts}".encode(),
        hashlib.sha256
    ).hexdigest()
    try:
        r   = requests.post(
            f"{SHOPEE_BASE_URL}{path}",
            params={"partner_id": SHOPEE_PARTNER_ID, "timestamp": ts, "sign": sign},
            json={"refresh_token": SHOPEE_REFRESH_TOKEN.strip(), "partner_id": SHOPEE_PARTNER_ID, "shop_id": SHOPEE_SHOP_ID},
            timeout=30
        )
        res = r.json()
        if "access_token" in res:
            SHOPEE_ACCESS_TOKEN = res["access_token"]
            print("🔄 Access token refreshed OK")
            return True
        print(f"❌ Refresh gagal: {res}")
        return False
    except Exception as e:
        print(f"❌ Refresh error: {e}")
        return False

def shopee_sign(path, timestamp):
    base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}{SHOPEE_ACCESS_TOKEN}{SHOPEE_SHOP_ID}"
    return hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()

def shopee_post(path, payload):
    ts = int(time.time())
    params = {
        "partner_id":   SHOPEE_PARTNER_ID,
        "timestamp":    ts,
        "access_token": SHOPEE_ACCESS_TOKEN,
        "shop_id":      SHOPEE_SHOP_ID,
        "sign":         shopee_sign(path, ts),
    }
    try:
        r    = requests.post(f"{SHOPEE_BASE_URL}{path}", params=params, json=payload, timeout=30)
        data = r.json()
        if data.get("error") and data.get("error") != "":
            print(f"  ⚠️ [{path}] {data.get('error')}: {data.get('message','')[:80]}")
        return data.get("response") if isinstance(data.get("response"), dict) else {}
    except Exception as e:
        print(f"  ❌ {path}: {e}")
        return {}

def get_lark_tenant_token():
    global _lark_tenant_token
    if _lark_tenant_token:
        return _lark_tenant_token
    try:
        r    = requests.post(
            f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET},
            timeout=30
        )
        data = r.json()
        _lark_tenant_token = data.get("tenant_access_token")
        print("✅ Lark token OK")
        return _lark_tenant_token
    except Exception as e:
        print(f"❌ Lark token error: {e}")
        return ""

def get_lark_headers():
    return {"Authorization": f"Bearer {get_lark_tenant_token()}", "Content-Type": "application/json"}

# ============================================================
# BACA TABEL BOOST DARI LARK
# ============================================================
def get_boost_candidates():
    """
    Ambil semua record dari tabel Naikkan Produk.
    Filter: Aktifkan Boost = true
    Urutkan: Prioritas ASC, Terakhir Di-Boost ASC (yang paling lama duluan)
    Ambil max 5 teratas.
    """
    url = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_BOOST}/records/search"
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "Aktifkan Boost", "operator": "is", "value": ["true"]}
            ]
        }
    }
    try:
        r    = requests.post(url, headers=get_lark_headers(), json=payload, timeout=30)
        data = r.json()
        if data.get("code") != 0:
            print(f"❌ Lark search error: {data.get('code')} {data.get('msg')}")
            return []
        items = data.get("data", {}).get("items", [])
        print(f"📋 Total produk aktif boost: {len(items)}")
        return items
    except Exception as e:
        print(f"❌ get_boost_candidates error: {e}")
        return []

def sort_candidates(items):
    """
    Urutkan: Prioritas ASC dulu, lalu Terakhir Di-Boost ASC.
    Record tanpa timestamp dianggap paling lama (boost duluan).
    """
    def sort_key(item):
        fields    = item.get("fields", {})
        prioritas = fields.get("Prioritas") or 9999
        timestamp = fields.get("Terakhir Di-Boost") or 0
        # Kalau timestamp adalah dict (Lark DateTime format), ambil value-nya
        if isinstance(timestamp, dict):
            timestamp = timestamp.get("timestamp", 0) or 0
        return (safe_int(prioritas), safe_int(timestamp))

    return sorted(items, key=sort_key)

# ============================================================
# BOOST PRODUK
# ============================================================
def boost_items(item_ids):
    """Kirim request boost ke Shopee."""
    if not item_ids:
        return False
    resp = shopee_post("/api/v2/product/boost_item", {
        "item_id_list": item_ids
    })
    # Response boost_item: {"failed_list": [...]}
    failed = resp.get("failed_list", [])
    if failed:
        print(f"  ⚠️ Gagal boost: {failed}")
    success_ids = [i for i in item_ids if i not in [f.get("item_id") for f in failed]]
    if success_ids:
        print(f"  ✅ Berhasil boost: {success_ids}")
    return success_ids

# ============================================================
# UPDATE TERAKHIR DI-BOOST DI LARK
# ============================================================
def update_boost_timestamp(record_id):
    """Update field Terakhir Di-Boost dengan timestamp sekarang."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    url    = f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_BOOST}/records/{record_id}"
    try:
        r      = requests.put(
            url,
            headers=get_lark_headers(),
            json={"fields": {"Terakhir Di-Boost": now_ms}},
            timeout=30
        )
        result = r.json()
        if result.get("code") != 0:
            print(f"  ❌ Update timestamp gagal: {result.get('code')} {result.get('msg')}")
    except Exception as e:
        print(f"  ❌ Update timestamp error: {e}")

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 50)
    print("🚀 zeodda_boost.py — START")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 50)

    if not LARK_APP_ID or not LARK_APP_SECRET:
        print("❌ LARK credentials tidak ada!")
        return

    refresh_shopee_access_token()
    get_lark_tenant_token()

    # Ambil kandidat boost dari Lark
    candidates = get_boost_candidates()
    if not candidates:
        print("⚠️ Tidak ada produk yang diaktifkan untuk boost.")
        return

    # Urutkan dan ambil max 5
    sorted_candidates = sort_candidates(candidates)
    to_boost          = sorted_candidates[:MAX_BOOST]

    print(f"\n🎯 Produk yang akan di-boost ({len(to_boost)}):")
    item_ids   = []
    record_map = {}  # item_id → record_id untuk update timestamp

    for c in to_boost:
        fields    = c.get("fields", {})
        record_id = c.get("record_id")
        kode      = str(fields.get("Kode Produk", "")).strip()
        prioritas = fields.get("Prioritas", "-")
        last_boost = fields.get("Terakhir Di-Boost", "belum pernah")

        if not kode:
            print(f"  ⚠️ Skip — Kode Produk kosong (record {record_id})")
            continue

        try:
            item_id = int(kode)
        except ValueError:
            print(f"  ⚠️ Skip — Kode Produk '{kode}' bukan angka valid")
            continue

        print(f"  • {kode} | Prioritas: {prioritas} | Terakhir boost: {last_boost}")
        item_ids.append(item_id)
        record_map[item_id] = record_id

    if not item_ids:
        print("⚠️ Tidak ada item_id valid untuk di-boost.")
        return

    # Boost
    print(f"\n📤 Boost {len(item_ids)} produk...")
    success_ids = boost_items(item_ids)

    # Update timestamp di Lark untuk yang berhasil
    if success_ids:
        print(f"\n📝 Update Terakhir Di-Boost di Lark...")
        for item_id in success_ids:
            record_id = record_map.get(item_id)
            if record_id:
                update_boost_timestamp(record_id)
                print(f"  ✅ Updated: {item_id}")

    print(f"\n✅ zeodda_boost.py — DONE")
    print(f"   Berhasil boost: {len(success_ids) if success_ids else 0} produk")
    print(f"   Next run: ~4 jam lagi")

if __name__ == "__main__":
    main()
