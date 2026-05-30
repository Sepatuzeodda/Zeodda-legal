# GANTI 'panggil_api_shopee' DENGAN NAMA FUNGSI ASLI DI SCRIPT ANDA
# Contoh jika nama fungsi aslinya adalah: make_shopee_request

for id_toko in daftar_toko:
    print(f"\n================ MENGPROSES TOKO: {id_toko} ================")

    # 1. Gunakan fungsi asli Anda di sini
    info_boost = make_shopee_request("get_boosted_list", {"shop_id": id_toko})
    sisa_detik = info_boost.get("cool_down_time", 0)
    sisa_menit = sisa_detik / 60

    if sisa_detik > 0:
        if sisa_menit <= 5:
            jeda_tunggu = sisa_detik + 5
            print(
                f"⏳ Slot toko {id_toko} dikit lagi habis (Sisa {sisa_menit:.1f} menit)."
            )
            print(f"   Script akan sleep selama {jeda_tunggu} detik...")
            time.sleep(jeda_tunggu)

            print(f"🚀 Menjalankan boost untuk toko {id_toko} sekarang!")
            # 2. Gunakan fungsi asli Anda di sini juga untuk menjalankan boost
            make_shopee_request("boost_item", {"shop_id": id_toko})

        else:
            print(
                f"⏩ SKIPPED: Toko {id_toko} masih terkunci {sisa_menit/60:.1f} jam lagi."
            )
            continue
    else:
        print(f"✅ Slot toko {id_toko} kosong. Langsung tembak boost!")
        # 3. Gunakan fungsi asli Anda di sini juga
        make_shopee_request("boost_item", {"shop_id": id_toko})
