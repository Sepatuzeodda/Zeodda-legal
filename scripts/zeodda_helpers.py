# =========================================================================
# SYSTEM CLOUDFLARE KV: DIRECT INJECTION (MODAL INJECT)
# =========================================================================
def sync_to_cf(shop_id, token):
    """Fungsi sinkronisasi langsung dipanggil saat token didapat."""
    shop_id = str(shop_id).strip()
    token = str(token).strip()
    if not shop_id or not token or len(shop_id) < 5: return
    
    cf_id = os.environ.get("CF_ACCOUNT_ID")
    cf_ns = os.environ.get("CF_KV_NAMESPACE")
    cf_token = os.environ.get("CF_API_TOKEN")
    
    if cf_id and cf_ns and cf_token:
        try:
            url = f"https://api.cloudflare.com/client/v4/accounts/{cf_id}/storage/kv/namespaces/{cf_ns}/values/token:{shop_id}"
            headers = {"Authorization": f"Bearer {cf_token}", "Content-Type": "text/plain"}
            requests.put(url, headers=headers, data=token, timeout=10)
            print(f"✅ [CLOUDFLARE] Token toko {shop_id} diamankan ke KV!")
        except Exception as e:
            print(f"❌ [CLOUDFLARE] Gagal sync toko {shop_id}: {e}")

# --- UPDATE FUNGSI REFRESH (TAMBAHKAN sync_to_cf DI SINI) ---
# Update bagian akhir fungsi refresh_shopee_token Anda menjadi seperti ini:
def refresh_shopee_token():
    # ... (kode lama anda) ...
    try:
        r = requests.post(url, params=params, json=payload, timeout=30)
        res_data = r.json()
        if "access_token" in res_data:
            _SHOPEE_ACTIVE_TOKEN = res_data["access_token"]
            print(f"🔄 [REFRESH] Sukses memperbarui Access Token Shopee.")
            # --- TAMBAHKAN BARIS INI ---
            sync_to_cf(SHOPEE_SHOP_ID, _SHOPEE_ACTIVE_TOKEN)
        else:
            print(f"❌ [REFRESH] Gagal refresh: {res_data.get('error')}")
    except Exception as e:
        print(f"❌ [REFRESH] Request error: {e}")
