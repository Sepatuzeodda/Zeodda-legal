import random
import time

# Daftar 8 ID Toko Cabang Zeodda
daftar_toko = [
    "1101111522",
    "1102913663",
    "867817945",
    "899095041",
    "963980234",
    "963990340",
    "967593785",
    "981846983",
]

for id_toko in daftar_toko:
    print(f"\n================ MENGPROSES TOKO: {id_toko} ================")

    # 1. Cek status slot riil di Shopee
    info_boost = panggil_api_shopee("get_boosted_list", {"shop_id": id_toko})
    sisa_detik = info_boost.get("cool_down_time", 0)
    sisa_menit = sisa_detik / 60

    # 2. Ambil Keputusan Berdasarkan Sisa Waktu
    if sisa_detik > 0:
        if sisa_menit <= 5:
            # JIKA SISA WAKTU DI BAWAH 5 MENIT -> TUNGGU
            jeda_tunggu = sisa_detik + 5  # ditambah 5 detik buffer
            print(
                f"⏳ Slot toko {id_toko} dikit lagi habis (Sisa {sisa_menit:.1f} menit)."
            )
            print(f"   Script akan sleep selama {jeda_tunggu} detik...")
            time.sleep(jeda_tunggu)

            # Eksekusi boost setelah selesai menunggu
            print(f"🚀 Menjalankan boost untuk toko {id_toko} sekarang!")
            panggil_api_shopee("boost_item", {"shop_id": id_toko})

        else:
            # JIKA SISA WAKTU MASIH PANJANG (MISAL 3 JAM) -> LEWATKAN!
            print(
                f"⏩ SKIPPED: Toko {id_toko} masih terkunci {sisa_menit/60:.1f} jam lagi."
            )
            print(
                "   Langsung dilewati ke toko berikutnya agar tidak memblokir antrean!"
            )
            continue  # Lanjut ke perulangan toko berikutnya
    else:
        # JIKA SLOT KOSONG TOTAL -> LANGSUNG BOOST
        print(f"✅ Slot toko {id_toko} kosong. Langsung tembak boost!")
        panggil_api_shopee("boost_item", {"shop_id": id_toko})
