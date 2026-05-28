import hmac
import hashlib
import time
import requests
import os
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
SHOPEE_PARTNER_ID    = int(os.environ.get("SHOPEE_PARTNER_ID", "2035358"))
SHOPEE_PARTNER_KEY   = os.environ.get("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_BASE_URL      = "https://partner.shopeemobile.com"
LARK_APP_ID          = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET      = os.environ.get("LARK_APP_SECRET", "")
LARK_APP_TOKEN       = "ItPfb0MPNaD6KhsVc65lT6p1gTh"
LARK_BASE_URL        = "https://open.larksuite.com"
TABLE_BOOST          = "tblzcjLMZX2KZ4aW"
GH_PAT               = os.environ.get("GH_PAT", "").strip()
GH_REPO              = os.environ.get("GH_REPO", "").strip()
MAX_BOOST            = 5

_ACCESS_TOKEN  = os.environ.get("SHOPEE_ACCESS_TOKEN", "").strip()
_REFRESH_TOKEN = os.environ.get("SHOPEE_REFRESH_TOKEN", "").strip()
_lark_token    = None

# ============================================================
# GITHUB SECRET SAVE
# ============================================================
def save_secret_to_github(name, value):
    if not GH_PAT or not GH_REPO:
        return
    try:
        from nacl import encoding, public
        import base64

        # Ambil public key
        r = requests.get(
            f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key",
            headers={"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"},
            timeout=10
        )
        data    = r.json()
        key_id  = data["key_id"]
        pub_key = data["key"]

        # Enkripsi
        pk        = public.PublicKey(pub_key.encode(), encoding.Base64Encoder())
        encrypted = base64.b64encode(public.SealedBox(pk).encrypt(value.encode())).decode()

        # Simpan
        r2 = requests.put(
            f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{name}",
            headers={"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"},
            json={"encrypted_value": encrypted, "key_id": key_id},
            timeout=10
        )
        if r2.status_code in (201, 204):
            print(f"  ✅ Secret {name} tersimpan ke GitHub")
        else:
            print(f"  ❌ Gagal simpan {name}: {r2.status_code}")
    except Exception as e:
        print(f"  ⚠️ save_secret error: {e}")

# ============================================================
# SHOPEE TOKEN
# ============================================================
def refresh_token():
    global _ACCESS_TOKEN, _REFRESH_TOKEN
    if not _REFRESH_TOKEN:
        return
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
            json={"refresh_token": _REFRESH_TOKEN, "partner_id": SHOPEE_PARTNER_ID},
            timeout=30
        )
        res = r.json()
        if "access_token" in res:
            _ACCESS_TOKEN = res["access_token"]
            print("🔄 Access token refreshed OK")
            new_refresh = res.get("refresh_token", "")
            if new_refresh and new_refresh != _REFRESH_TOKEN:
                _REFRESH_TOKEN = new_refresh
                print("🔑 Refresh token baru — menyimpan ke GitHub Secrets...")
                save_secret_to_github("SHOPEE_REFRESH_TOKEN", new_refresh)
            save_secret_to_github("SHOPEE_ACCESS_TOKEN", _ACCESS_TOKEN)
        else:
            print(f"❌ Refresh gagal: {res.get('error')} {res.get('message')}")
    except Exception as e:
        print(f"❌ Refresh error: {e}")

def shopee_sign(path, ts, shop_id):
    base = f"{SHOPEE_PARTNER_ID}{path}{ts}{_ACCESS_TOKEN}{shop_id}"
    return hmac.new(SHOPEE_PARTNER_KEY.encode(), base.encode(), hashlib.sha256).hexdigest()

def shopee_post(path, payload, shop_id):
    ts = int(time.time())
    params = {
        "partner_id":   SHOPEE_PARTNER_ID,
        "timestamp":    ts,
        "access_token": _ACCESS_TOKEN,
        "shop_id":      shop_id,
        "sign":         shopee_sign(path, ts, shop_id),
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

# ============================================================
# LARK
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
    """Ambil semua record yang Aktifkan Boost = true dari Lark."""
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
    """Parse Lark Text field yang return list of dict."""
    if isinstance(val, list) and val:
        return str(val[0].get("text", "")).strip()
    return str(val).strip() if val else ""

def group_by_shop(items):
    """Group records berdasarkan Shop ID."""
    groups = {}
    for item in items:
        fields    = item.get("fields", {})
        shop_raw  = fields.get("Shop ID")
        shop_id   = int(shop_raw) if shop_raw and str(shop_raw).isdigit() else None

        if not shop_id:
            print(f"  ⚠️ Skip record tanpa Shop ID: {item.get('record_id')}")
            continue

        if shop_id not in groups:
            groups[shop_id] = []
        groups[shop_id].append(item)

    return groups

def sort_candidates(items):
    """Urutkan: Prioritas ASC, Terakhir Di-Boost ASC."""
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
    """Update Terakhir Di-Boost di Lark."""
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

# ============================================================
# BOOST PER TOKO
# ============================================================
def boost_for_shop(shop_id, items):
    print(f"\n🏪 Toko {shop_id} — {len(items)} produk aktif")

    sorted_items = sort_candidates(items)
    to_boost     = sorted_items[:MAX_BOOST]

    item_ids   = []
    record_map = {}

    for c in to_boost:
        fields    = c.get("fields", {})
        record_id = c.get("record_id")
        kode_raw  = fields.get("Kode Produk", "")
        kode      = parse_text_field(kode_raw)

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
        return

    # Boost via Shopee API
    print(f"\n  📤 Boost {len(item_ids)} produk untuk toko {shop_id}...")
    resp   = shopee_post("/api/v2/product/boost_item", {"item_id_list": item_ids}, shop_id)
    failed = resp.get("failed_list", [])
    failed_ids = [f.get("item_id") for f in failed]

    if failed:
        print(f"  ⚠️ Gagal boost: {failed}")

    success_ids = [i for i in item_ids if i not in failed_ids]
    if success_ids:
        print(f"  ✅ Berhasil boost: {success_ids}")

    # Update timestamp di Lark
    for item_id in success_ids:
        record_id = record_map.get(item_id)
        if record_id:
            update_boost_timestamp(record_id)

    return len(success_ids)

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 50)
    print("🚀 Naikkan Produk — START")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 50)

    if not LARK_APP_ID or not LARK_APP_SECRET:
        print("❌ LARK credentials tidak ada!")
        return

    # Refresh token
    refresh_token()
    get_lark_token()

    # Ambil semua kandidat boost
    candidates = get_boost_candidates()
    if not candidates:
        print("⚠️ Tidak ada produk yang diaktifkan untuk boost.")
        return

    # Group per shop_id
    shop_groups = group_by_shop(candidates)
    print(f"\n🏪 Total toko yang akan di-boost: {len(shop_groups)}")

    total_success = 0
    for shop_id, items in shop_groups.items():
        result = boost_for_shop(shop_id, items)
        if result:
            total_success += result

    print(f"\n{'='*50}")
    print(f"✅ Naikkan Produk — DONE")
    print(f"   Total berhasil boost: {total_success} produk")
    print(f"   Toko diproses: {len(shop_groups)}")
    print(f"   Next run: ~4 jam lagi")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
