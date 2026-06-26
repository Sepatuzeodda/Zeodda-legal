# =========================================================================
# SYSTEM CLOUDFLARE KV: SINKRONISASI TOKEN (NON-BLOCKING / SHADOW)
# =========================================================================
import threading

def _async_sync(shop_id, token):
    """Menjalankan sinkronisasi di background agar tidak mengganggu script utama"""
    def task():
        try:
            cf_id = os.environ.get("CF_ACCOUNT_ID")
            cf_ns = os.environ.get("CF_KV_NAMESPACE")
            cf_token = os.environ.get("CF_API_TOKEN")
            if not (cf_id and cf_ns and cf_token): return
            
            url = f"https://api.cloudflare.com/client/v4/accounts/{cf_id}/storage/kv/namespaces/{cf_ns}/values/token:{shop_id}"
            headers = {"Authorization": f"Bearer {cf_token}", "Content-Type": "text/plain"}
            requests.put(url, headers=headers, data=str(token).strip(), timeout=10)
        except: pass
    
    threading.Thread(target=task, daemon=True).start()

# Kita simpan referensi asli agar tetap bisa dipakai Lark/Shopee
_orig_post = requests.post
_orig_get = requests.get

def _monitor_and_sync(res, **kwargs):
    """Fungsi pengintai untuk mengambil token dari respons"""
    try:
        data = res.json()
        
        # 1. Deteksi jika ini adalah respons dari /access_token/get
        if isinstance(data, dict):
            token = data.get("access_token")
            # Cek shop_id dari payload request jika ada
            payload = kwargs.get("json", {})
            shop_id = payload.get("shop_id") if isinstance(payload, dict) else None
            
            if token and shop_id:
                _async_sync(shop_id, token)
                
            # Jika respons mengandung list atau nested object
            if not shop_id and "response" in data and isinstance(data["response"], dict):
                token = data["response"].get("access_token")
                shop_id = data["response"].get("shop_id")
                if token and shop_id:
                    _async_sync(shop_id, token)
    except: pass
    return res

def patched_post(*args, **kwargs):
    res = _orig_post(*args, **kwargs)
    return _monitor_and_sync(res, **kwargs)

def patched_get(*args, **kwargs):
    res = _orig_get(*args, **kwargs)
    return _monitor_and_sync(res, **kwargs)

# Pasang pengintai tanpa merusak fungsi asli
requests.post = patched_post
requests.get = patched_get
# =========================================================================
