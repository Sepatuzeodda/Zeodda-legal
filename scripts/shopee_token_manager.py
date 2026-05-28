"""
shopee_token_manager.py
=======================
Shared token manager untuk semua script Zeodda.
- Auto-refresh Shopee access token
- Auto-save refresh token baru ke GitHub Secrets
- Support multi-toko via SHOPEE_SHOP_IDS

Import: from shopee_token_manager import refresh_and_save, get_shop_ids
"""

import hmac
import hashlib
import time
import requests
import os
import base64
import json

# ============================================================
# CONFIG
# ============================================================
SHOPEE_PARTNER_ID    = int(os.environ.get("SHOPEE_PARTNER_ID", "2035358"))
SHOPEE_PARTNER_KEY   = os.environ.get("SHOPEE_PARTNER_KEY", "").strip()
SHOPEE_BASE_URL      = "https://partner.shopeemobile.com"

GH_PAT  = os.environ.get("GH_PAT", "").strip()
GH_REPO = os.environ.get("GH_REPO", "").strip()  # format: owner/repo

# Global token state
_ACCESS_TOKEN  = os.environ.get("SHOPEE_ACCESS_TOKEN", "").strip()
_REFRESH_TOKEN = os.environ.get("SHOPEE_REFRESH_TOKEN", "").strip()

# ============================================================
# GITHUB SECRETS API
# ============================================================
def _get_repo_public_key():
    """Ambil public key repo untuk enkripsi secret."""
    if not GH_PAT or not GH_REPO:
        return None, None
    url     = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept":        "application/vnd.github+json",
    }
    try:
        r    = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        return data.get("key_id"), data.get("key")
    except Exception as e:
        print(f"  ⚠️ GitHub public key error: {e}")
        return None, None

def _encrypt_secret(public_key_b64, secret_value):
    """Enkripsi nilai secret pakai libsodium (PyNaCl)."""
    try:
        from nacl import encoding, public
        pk    = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
        box   = public.SealedBox(pk)
        encrypted = box.encrypt(secret_value.encode())
        return base64.b64encode(encrypted).decode()
    except ImportError:
        # Fallback: nacl tidak tersedia, pakai base64 biasa (tidak aman tapi fungsional untuk testing)
        print("  ⚠️ PyNaCl tidak tersedia, skip enkripsi — install: pip install PyNaCl")
        return None

def save_secret_to_github(secret_name, secret_value):
    """Simpan/update secret di GitHub Actions."""
    if not GH_PAT or not GH_REPO:
        print(f"  ⚠️ GH_PAT atau GH_REPO tidak ada, skip save secret {secret_name}")
        return False

    key_id, public_key = _get_repo_public_key()
    if not key_id or not public_key:
        print(f"  ⚠️ Gagal ambil public key GitHub, skip save {secret_name}")
        return False

    encrypted = _encrypt_secret(public_key, secret_value)
    if not encrypted:
        return False

    url     = f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{secret_name}"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept":        "application/vnd.github+json",
    }
    payload = {
        "encrypted_value": encrypted,
        "key_id":          key_id,
    }
    try:
        r = requests.put(url, headers=headers, json=payload, timeout=10)
        if r.status_code in (201, 204):
            print(f"  ✅ GitHub Secret '{secret_name}' berhasil diupdate")
            return True
        else:
            print(f"  ❌ Gagal update secret {secret_name}: {r.status_code} {r.text[:100]}")
            return False
    except Exception as e:
        print(f"  ❌ GitHub API error: {e}")
        return False

# ============================================================
# SHOPEE TOKEN REFRESH
# ============================================================
def refresh_and_save():
    """
    Refresh Shopee access token dan simpan refresh token baru ke GitHub Secrets.
    Return: access_token terbaru (string) atau None kalau gagal.
    """
    global _ACCESS_TOKEN, _REFRESH_TOKEN

    if not _REFRESH_TOKEN:
        print("⚠️ SHOPEE_REFRESH_TOKEN kosong, skip refresh.")
        return _ACCESS_TOKEN

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
            json={
                "refresh_token": _REFRESH_TOKEN,
                "partner_id":    SHOPEE_PARTNER_ID,
                # Sub-account: tidak perlu shop_id
            },
            timeout=30
        )
        res = r.json()

        if "access_token" in res and res["access_token"]:
            new_access  = res["access_token"]
            new_refresh = res.get("refresh_token", "")

            _ACCESS_TOKEN = new_access
            print(f"🔄 Access token refreshed OK")

            # Simpan refresh token baru ke GitHub Secrets
            if new_refresh and new_refresh != _REFRESH_TOKEN:
                _REFRESH_TOKEN = new_refresh
                print(f"🔑 Refresh token baru tersedia, menyimpan ke GitHub Secrets...")
                save_secret_to_github("SHOPEE_REFRESH_TOKEN", new_refresh)
                save_secret_to_github("SHOPEE_ACCESS_TOKEN", new_access)
            else:
                # Tetap simpan access token baru
                save_secret_to_github("SHOPEE_ACCESS_TOKEN", new_access)

            return new_access
        else:
            print(f"❌ Refresh gagal: {res.get('error')} - {res.get('message')}")
            return None

    except Exception as e:
        print(f"❌ Refresh error: {e}")
        return None

# ============================================================
# MULTI-TOKO
# ============================================================
def get_shop_ids():
    """
    Ambil list shop_id dari env SHOPEE_SHOP_IDS.
    Format secret: '963980234,867817945,899095041,...'
    Return: list of int
    """
    raw = os.environ.get("SHOPEE_SHOP_IDS", "").strip()
    if not raw:
        # Fallback ke SHOPEE_SHOP_ID lama (single toko)
        single = os.environ.get("SHOPEE_SHOP_ID", "").strip()
        if single:
            return [int(single)]
        return []
    try:
        return [int(s.strip()) for s in raw.split(",") if s.strip()]
    except Exception as e:
        print(f"⚠️ Error parsing SHOPEE_SHOP_IDS: {e}")
        return []

def get_access_token():
    """Return access token yang aktif."""
    return _ACCESS_TOKEN
