import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
SHOPEE_PARTNER_ID     = int(os.environ.get("SHOPEE_PARTNER_ID") or "2035358")
SHOPEE_PARTNER_KEY    = os.environ.get("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_BASE_URL       = "https://partner.shopeemobile.com"
LARK_APP_ID           = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET       = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN        = "ItPfb0MPNaD6KhsVc65lT6p1gTh"
LARK_BASE_URL         = "https://open.larksuite.com"
TABLE_BOOST           = "tblzcjLMZX2KZ4aW"
GH_PAT                = os.environ.get("GH_PAT", "").strip()
GH_REPO               = os.environ.get("GH_REPO", "").strip()
MAX_BOOST             = 5

_GLOBAL_REFRESH_TOKEN = os.environ.get("SHOPEE_REFRESH_TOKEN", "").strip()
_lark_token           = None

# ============================================================
# SAFE HELPERS
# ============================================================
def safe_list(d, key):
    if not isinstance(d, dict):
        return []
    v = d.get(key, [])
    return v if isinstance(v, list) else []

# ============================================================
# GITHUB SECRET SAVE
# ============================================================
def save_secret_to_github(name, value):
    if not GH_PAT or not GH_REPO:
        return
    try:
        from nacl import encoding, public
        import base64
        r = requests.get(
            f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key",
            headers={"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"},
            timeout=10
        )
        data      = r.json()
        key_id    = data["key_id"]
        pub_key   = data["key"]
        pk        = public.PublicKey(pub_key.encode(), encoding.Base64Encoder())
        encrypted = base64.b64encode(public.SealedBox(pk).encrypt(value.encode())).decode()
        r2 = requests.put(
            f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{name}",
            headers={"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"},
            json={"encrypted_value": encrypted, "key_id": key_id},
            timeout=10
        )
        if r2.status_code in (201, 204):
            print(f"  ✅ Secret {name} berhasil diperbarui di GitHub")
        else:
            print(f"  ❌ Gagal simpan {name}: {r2.status_code}")
    except Exception as e:
        print(f"  ⚠️ save_secret error: {e}")

# ============================================================
# SHOPEE NETWORK METHODS (DENGAN FIX ERROR INTERCEPTOR)
# ============================================================
def get_active_token_for_shop(shop_id):
    global _GLOBAL_REFRESH_TOKEN
    env_key       = f"SHOPEE_REFRESH_TOKEN_{shop_id}"
    local_refresh = os.environ.get(env_key, "").strip() or _GLOBAL_REFRESH_TOKEN

    if not local_refresh:
        print(f"  ❌ Tidak ada REFRESH_TOKEN untuk Toko {shop_id}")
        return None

    path = "/api/v2/auth/access_token/get"
    ts   = int(time.time())
    sign = hmac.new(
        SHOPEE_PARTNER_KEY.encode(),
        f"{SHOPEE_PARTNER_ID}{path}{ts}".encode(),
        hashlib.sha256
    ).hexdigest()

    try:
        r = requests.post(
            f"{SHOPEE_BASE_URL}{path}",
            params={"partner_id": SHOPEE_PARTNER_ID, "timestamp": ts, "sign": sign},
            json={"refresh_token": local_refresh, "partner_id": SHOPEE_PARTNER_ID, "shop_id": int(shop_id)},
            timeout=30
        )
        res = r.json()
        if "access_token" in res and res["access_token"]:
            new_refresh = res.get("refresh_token", "")
            if new_refresh and new_refresh != local_refresh:
                secret_name = env_key if os.environ.get(env_key) else "SHOPEE_REFRESH_TOKEN"
                print(f"  🔑 Refresh token baru — simpan ke {secret_name}...")
                save_secret_to_github(secret_name, new_refresh)
                save_secret_to_github("SHOPEE_ACCESS_TOKEN", res["access_token"])
                _GLOBAL_REFRESH_TOKEN = new_refresh
            print(f"  🔑 Shop token OK untuk toko {shop_id}")
            return res["access_token"]
        else:
            print(f"  ❌ Gagal get token toko {shop_id}: {res.get('error')} - {res.get('message')}")
            return None
    except Exception as e:
        print(f"  ❌ Token error toko {shop_id}: {e}")
        return None

def shopee_get(path, shop_id, access_token, extra={}):
    ts   = int(time.time())
    base = f"{SHOPEE_PARTNER_ID}{path}{ts}{access_token}{shop_id}"
    sign = hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()
    params = {
        "partner_id":   SHOPEE_PARTNER_ID,
        "timestamp":    ts,
        "access_token": access_token,
        "shop_id":      int(shop_id),
        "sign":         sign,
    }
    params.update(extra)
    try:
        r    = requests.get(f"{SHOPEE_BASE_URL}{path}", params=params, timeout=30)
        data = r.json()
        if data.get("error") and data.get("error") != "":
            print(f"  ⚠️ [{path}] {data.get('error')}: {data.get('message','')[:80]}")
            return None  # Intersepsi error root level, return None
        return data.get("response") if isinstance(data.get("response"), dict) else {}
    except Exception as e:
        print(f"  ❌ {path}: {e}")
        return None

def shopee_post(path, payload, shop_id, access_token):
    ts   = int(time.time())
    base = f"{SHOPEE_PARTNER_ID}{path}{ts}{access_token}{shop_id}"
    sign = hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()
    params = {
        "partner_id":   SHOPEE_PARTNER_ID,
        "timestamp":    ts,
        "access_token": access_token,
        "shop_id":      int(shop_id),
        "sign":         sign,
    }
    try:
        r    = requests.post(f"{SHOPEE_BASE_URL}{path}", params=params, json=payload, timeout=30)
        data = r.json()
        if data.get("error") and data.get("error") != "":
            print(f"  ⚠️ [{path}] {data.get('error')}: {data.get('message','')[:80]}")
            return None  # Intersepsi error root level, return None agar 'if not resp' bekerja
        return data.get("response") if isinstance(data.get("response"), dict) else {}
    except Exception as e:
        print(f"  ❌ {path}: {e}")
        return None

def check_cooldown(shop_id, access_token):
    """
    Cek sisa cooldown rentang waktu secara akurat dari list item aktif.
    Mendukung format hitungan mundur detik maupun format masa depan timestamp.
    """
    resp = shopee_get("/api/v2/product/get_boosted_list", shop_id, access_token)
    if not resp:
        return 0
        
    item_list = resp.get("item_list", [])
    if item_list:
        max_cooldown = max([item.get("cool_down_time", 0) for item in item_list])
        # Proteksi: Jika Shopee mengembalikan format Epoch Timestamp masa depan (> Tahun 2020)
        if max_cooldown > 1577836800:
            sisa_detik = max_cooldown - int(time.time())
            return max(0, sisa_detik)
        return max_cooldown
    return 0

# ============================================================
# LARK INTERACTION
# ============================================================
def get_lark_token():
    global _lark_token
    if _lark_token:
        return _lark_token
    r = requests.post(
        f"{LARK_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET},
        timeout=30
    )
    _lark_token = r.json().get("tenant_access_token")
    print("✅ Lark token OK")
    return _lark_token

def lark_headers():
    return {"Authorization": f"Bearer {get_lark_token()}", "Content-Type": "application/json"}

def get_boost_candidates():
    r = requests.post(
        f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_BOOST}/records/search",
        headers=lark_headers(),
        json={"filter": {"conjunction": "and", "conditions": [
            {"field_name": "Aktifkan Boost", "operator": "is", "value": ["true"]}
        ]}},
        timeout=30
    )
    data  = r.json()
    items = data.get("data", {}).get("items", [])
    print(f"📋 Total produk aktif boost: {len(items)}")
    return items

def parse_text_field(val):
    if isinstance(val, list) and val:
        return str(val[0].get("text", "")).strip()
    return str(val).strip() if val else ""

def group_by_shop(items):
    groups = {}
    for item in items:
        fields   = item.get("fields", {})
        shop_raw = fields.get("Shop ID")
        try:
            if isinstance(shop_raw, dict) and shop_raw.get("value"):
                shop_id = int(shop_raw["value"][0])
            elif isinstance(shop_raw, (int, float)) and shop_raw:
                shop_id = int(shop_raw)
            elif isinstance(shop_raw, str) and shop_raw.strip().isdigit():
                shop_id = int(shop_raw.strip())
            elif isinstance(shop_raw, list) and shop_raw:
                shop_id = int(str(shop_raw[0].get("text", "")).strip())
            else:
                shop_id = None
        except Exception:
            shop_id = None

        if not shop_id:
            print(f"  ⚠️ Skip record tanpa Shop ID: {item.get('record_id')}")
            continue
        if shop_id not in groups:
            groups[shop_id] = []
        groups[shop_id].append(item)
    return groups

def sort_candidates(items):
    def sort_key(item):
        fields    = item.get("fields", {})
        prioritas = fields.get("Prioritas") or 9999
        timestamp = fields.get("Terakhir Di-Boost") or 0
        if isinstance(timestamp, dict):
            timestamp = timestamp.get("timestamp", 0) or 0
        try:
            return (int(float(str(prioritas))), int(float(str(timestamp))))
        except:
            return (9999, 0)
    return sorted(items, key=sort_key)

def update_boost_timestamp(record_id):
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    r = requests.put(
        f"{LARK_BASE_URL}/open-apis/bitable/v1/apps/{LARK_APP_TOKEN}/tables/{TABLE_BOOST}/records/{record_id}",
        headers=lark_headers(),
        json={"fields": {"Terakhir Di-Boost": now_ms}},
        timeout=30
    )
    result = r.json()
    if result.get("code") != 0:
        print(f"  ❌ Update timestamp gagal: {result.get('code')} {result.get('msg')}")
    else:
        print(f"  ✅ Timestamp updated")

# ============================================================
# CORE TRANSACTION DISPATCHER
# ============================================================
def boost_for_shop(shop_id, items):
    print(f"\n🏪 Toko {shop_id} — {len(items)} produk aktif")

    shop_token = get_active_token_for_shop(shop_id)
    if not shop_token:
        print(f"  ❌ Skip toko {shop_id} — Token tidak valid")
        return 0

    sisa_detik = check_cooldown(shop_id, shop_token)
    sisa_menit = sisa_detik / 60

    if sisa_detik > 0:
        if sisa_menit <= 5:
            jeda_keamanan = sisa_detik + 5
            print(f"  ⏳ Slot hampir habis ({sisa_menit:.1f} menit) — tunggu {jeda_keamanan} detik...")
            time.sleep(jeda_keamanan)
            print(f"  🚀 Lanjut boost setelah tunggu!")
        else:
            print(f"  ⏩ Skip toko {shop_id} — slot masih aktif {sisa_menit/60:.1f} jam lagi")
            return 0

    sorted_items = sort_candidates(items)
    to_boost     = sorted_items[:MAX_BOOST]

    item_ids   = []
    record_map = {}

    for c in to_boost:
        fields    = c.get("fields", {})
        record_id = c.get("record_id")
        kode      = parse_text_field(fields.get("Kode Produk", ""))

        if not kode:
            print(f"  ⚠️ Skip — Kode Produk kosong")
            continue
        try:
            item_id = int(kode)
        except ValueError:
            print(f"  ⚠️ Skip — Kode '{kode}' bukan angka valid")
            continue

        prioritas  = fields.get("Prioritas", "-")
        last_boost = fields.get("Terakhir Di-Boost", "belum pernah")
        print(f"  • {kode} | Prioritas: {prioritas} | Terakhir: {last_boost}")
        item_ids.append(item_id)
        record_map[item_id] = record_id

    if not item_ids:
        print(f"  ⚠️ Tidak ada item valid untuk toko {shop_id}")
        return 0

    print(f"  📤 Boost {len(item_ids)} produk untuk toko {shop_id}...")
    resp       = shopee_post("/api/v2/product/boost_item", {"item_id_list": item_ids}, shop_id, shop_token)
    
    # Intersepsi Jika API Mengembalikan Parameter Error (Bukan False Positive Lagi)
    if resp is None:
        print(f"  ❌ Gagal total melakukan boost untuk toko {shop_id} (Ditolak oleh Shopee / Slot Penuh)")
        return 0

    failed     = safe_list(resp, "failed_list")
    failed_ids = [f.get("item_id") for f in failed]

    if failed_ids:
        print(f"  ⚠️ Gagal boost produk tertentu: {failed_ids}")

    success_ids = [i for i in item_ids if i not in failed_ids]
    if success_ids:
        print(f"  ✅ Berhasil boost ke Shopee: {success_ids}")
        for item_id in success_ids:
            record_id = record_map.get(item_id)
            if record_id:
                update_boost_timestamp(record_id)

    return len(success_ids)

# ============================================================
# MAIN APPLICATION ENTRY POINT
# ============================================================
def main():
    print("=" * 50)
    print("🚀 Naikkan Produk — START")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 50)

    if not LARK_APP_ID or not LARK_APP_SECRET:
        print("❌ LARK credentials tidak ada!")
        return

    get_lark_token()

    candidates = get_boost_candidates()
    if not candidates:
        print("⚠️ Tidak ada produk yang diaktifkan untuk boost.")
        return

    shop_groups = group_by_shop(candidates)
    print(f"\n🏪 Total toko yang akan di-boost: {len(shop_groups)}")

    total_success = 0
    for shop_id, items in shop_groups.items():
        result = boost_for_shop(shop_id, items)
        total_success += result or 0

    print(f"\n{'='*50}")
    print(f"✅ Naikkan Produk — DONE")
    print(f"    Total berhasil boost: {total_success} produk")
    print(f"    Toko diproses: {len(shop_groups)}")
    print(f"    Next run: ~4 jam lagi")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
