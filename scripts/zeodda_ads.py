"""
zeodda_ads.py
=============
Ads Data — Shop Level & Product Level → Lark Base.

API yang dipakai:
  - get_total_balance                      ✅ → saldo iklan
  - get_all_cpc_ads_daily_performance      ✅ → shop-level ads (spend, impresi, klik, order, revenue)
  - get_shop_toggle_info                   ✅ → toggle iklan aktif/tidak
  - get_product_level_campaign_id_list     ✅ DD-MM-YYYY → list campaign per produk
  - ams/get_product_performance            ❌ SKIP — permission belum aktif
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from zeodda_helpers import (
    shopee_get,
    lark_add,
    lark_add_batch,
    lark_init,
    safe_int,
    safe_str,
    safe_dict,
    safe_list,
    get_yesterday_range,
    TABLE_ADS_SHOP,
    TABLE_ADS_PRODUCT,
    TABLE_KOMPARASI,
    TABLE_ALERT_LOG,
)

PLATFORM = "Shopee"


# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────

def push_alert(date_str, tipe, detail, nilai, normal, prioritas="Medium"):
    lark_add(TABLE_ALERT_LOG, {
        "Tanggal":        date_str,
        "Platform":       PLATFORM,
        "Tipe Alert":     tipe,
        "Detail":         detail,
        "Nilai Saat Ini": str(nilai),
        "Nilai Normal":   str(normal),
        "Prioritas":      prioritas,
        "Status":         "Open",
    })


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


# ─────────────────────────────────────────────
# SHOP LEVEL ADS
# ─────────────────────────────────────────────

def collect_shop_ads(date_dmy, date_str):
    """
    Kumpulkan data ads level toko:
    saldo, spend, impresi, klik, order, revenue, toggle.
    """
    d = {}

    # Saldo iklan
    balance_resp = shopee_get("/api/v2/ads/get_total_balance", {})
    d["saldo_iklan"] = balance_resp.get("total_balance", 0)

    # CPC daily performance (pakai DD-MM-YYYY)
    cpc_resp = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {
        "start_date": date_dmy,
        "end_date":   date_dmy,
    })
    perf_list = safe_list(cpc_resp, "daily_performance_list")
    if perf_list:
        p = perf_list[0]
        d["total_spend"]        = p.get("daily_spend", 0)
        d["total_impresi"]      = safe_int(p.get("impression"))
        d["total_klik"]         = safe_int(p.get("click"))
        d["total_order_iklan"]  = safe_int(p.get("order"))
        d["revenue_iklan"]      = p.get("revenue", 0)
    else:
        d["total_spend"]        = 0
        d["total_impresi"]      = 0
        d["total_klik"]         = 0
        d["total_order_iklan"]  = 0
        d["revenue_iklan"]      = 0

    # Toggle iklan
    toggle_resp = shopee_get("/api/v2/ads/get_shop_toggle_info", {})
    d["toggle_aktif"] = "Aktif" if toggle_resp.get("shop_toggle") == 1 else "Mati"

    return d


def push_shop_ads(date_str, d):
    record = {
        "Tanggal":              date_str,
        "Platform":             PLATFORM,
        "Saldo Iklan":          d["saldo_iklan"],
        "Total Spend":          d["total_spend"],
        "Total Impresi":        d["total_impresi"],
        "Total Klik":           d["total_klik"],
        "Total Order dari Iklan": d["total_order_iklan"],
        "Revenue dari Iklan":   d["revenue_iklan"],
        "Toggle Iklan Aktif":   d["toggle_aktif"],
    }
    lark_add(TABLE_ADS_SHOP, record)
    print(f"✅ Ads Shop Level pushed → {date_str}")


# ─────────────────────────────────────────────
# PRODUCT LEVEL ADS
# ─────────────────────────────────────────────

def get_item_names(item_ids):
    """Ambil nama produk untuk label di Lark."""
    name_map = {}
    for chunk in chunks(item_ids, 50):
        resp = shopee_get("/api/v2/product/get_item_base_info", {
            "item_id_list": ",".join(str(i) for i in chunk),
        })
        for item in safe_list(resp, "item_list"):
            iid = item.get("item_id")
            if iid:
                name_map[iid] = safe_str(item.get("item_name"))
    return name_map


def collect_product_ads(date_dmy, date_str):
    """
    Ambil campaign per produk → spend, impresi, klik, order, revenue.

    NOTE: ams/get_product_performance ❌ belum aktif.
    Saat ini hanya ambil campaign_id list saja.
    Setelah permission AMS aktif → uncomment bagian ams_map di bawah.
    """
    records = []

    # Ambil item list dulu
    item_resp = shopee_get("/api/v2/product/get_item_list", {
        "offset":      0,
        "page_size":   100,
        "item_status": "NORMAL",
    })
    item_ids = [i["item_id"] for i in safe_list(item_resp, "item") if "item_id" in i]

    if not item_ids:
        print("⚠️  Tidak ada item aktif untuk product ads.")
        return records

    name_map = get_item_names(item_ids)

    # Campaign ID per produk
    camp_resp = shopee_get("/api/v2/ads/get_product_level_campaign_id_list", {
        "start_date": date_dmy,
        "end_date":   date_dmy,
    })
    camp_list = safe_list(camp_resp, "product_campaign_list")

    if not camp_list:
        print("⚠️  Tidak ada campaign produk kemarin (mungkin belum ada iklan produk).")
        return records

    for camp in camp_list:
        iid         = camp.get("item_id")
        campaign_id = camp.get("campaign_id")

        # ── AMS Product Performance (SKIP — permission belum aktif) ──────
        # Uncomment setelah AMS permission aktif di Shopee Console:
        #
        # ams = shopee_get("/api/v2/ads/ams/get_product_performance", {
        #     "campaign_id": campaign_id,
        #     "start_date":  date_dmy,
        #     "end_date":    date_dmy,
        # })
        # spend   = ams.get("spend", 0)
        # impresi = safe_int(ams.get("impression"))
        # klik    = safe_int(ams.get("click"))
        # order   = safe_int(ams.get("order"))
        # revenue = ams.get("revenue", 0)
        # status  = safe_str(ams.get("campaign_status"))
        # bid_rec = ams.get("recommended_bid", 0)

        # Placeholder sampai AMS aktif
        spend   = 0
        impresi = 0
        klik    = 0
        order   = 0
        revenue = 0
        status  = "Pending AMS Permission"
        bid_rec = 0

        records.append({
            "Tanggal":            date_str,
            "Platform":           PLATFORM,
            "Nama Produk":        name_map.get(iid, str(iid)),
            "Campaign ID":        str(campaign_id),
            "Spend":              spend,
            "Impresi":            impresi,
            "Klik":               klik,
            "Order dari Iklan":   order,
            "Revenue dari Iklan": revenue,
            "Status Campaign":    status,
            "Rekomendasi Bid":    bid_rec,
        })

    return records


def push_product_ads(records):
    if not records:
        print("⚠️  Tidak ada record product ads untuk di-push.")
        return
    for chunk in chunks(records, 100):
        lark_add_batch(TABLE_ADS_PRODUCT, chunk)
    print(f"✅ Ads Product Level pushed → {len(records)} campaign")


# ─────────────────────────────────────────────
# KOMPARASI (organik vs iklan per produk)
# ─────────────────────────────────────────────

def push_komparasi(date_str, product_ads, boost_set=None):
    """
    Komparasi organik vs iklan.
    Data organik sementara 0 sampai AMS aktif.
    """
    if not product_ads:
        return

    records = []
    for p in product_ads:
        records.append({
            "Tanggal":          date_str,
            "Nama Produk":      p["Nama Produk"],
            "Platform":         PLATFORM,
            "Rating Bintang":   0,          # diisi dari product_performance
            "Terjual Organik":  0,          # diisi setelah AMS aktif
            "Revenue Organik":  0,
            "Terjual dari Iklan":  p["Order dari Iklan"],
            "Revenue dari Iklan":  p["Revenue dari Iklan"],
            "Spend Iklan":      p["Spend"],
            "Status Boost":     "Aktif" if boost_set and p.get("item_id") in boost_set else "Tidak",
            "Rekomendasi":      "Cek AMS" if p["Spend"] == 0 else "OK",
        })

    for chunk in chunks(records, 100):
        lark_add_batch(TABLE_KOMPARASI, chunk)
    print(f"✅ Komparasi pushed → {len(records)} produk")


# ─────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────

def check_alerts(date_str, shop_d):
    # Saldo iklan rendah
    if shop_d["saldo_iklan"] < 100_000:
        push_alert(date_str, "Saldo Iklan Rendah",
                   f"Saldo Rp {shop_d['saldo_iklan']:,.0f}",
                   shop_d["saldo_iklan"], ">= 100.000", "High")

    # Toggle mati tapi ada spend
    if shop_d["toggle_aktif"] == "Mati" and shop_d["total_spend"] > 0:
        push_alert(date_str, "Toggle Mati tapi Ada Spend",
                   f"Toggle OFF tapi spend Rp {shop_d['total_spend']:,.0f}",
                   shop_d["total_spend"], "0 jika toggle mati", "Medium")

    if not any([
        shop_d["saldo_iklan"] < 100_000,
        shop_d["toggle_aktif"] == "Mati" and shop_d["total_spend"] > 0,
    ]):
        print("✅ No ads alerts triggered.")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 50)
    print("🚀 zeodda_ads.py — START")
    print("=" * 50)

    lark_init()

    t        = get_yesterday_range()
    date_str = t["date_str"]
    date_dmy = t["date_str_dmy"]
    print(f"📅 Tanggal: {date_str} ({date_dmy})")

    # Shop level
    print("\n📊 Collect shop-level ads...")
    shop_d = collect_shop_ads(date_dmy, date_str)
    print(f"   Saldo: {shop_d['saldo_iklan']} | Spend: {shop_d['total_spend']} | Toggle: {shop_d['toggle_aktif']}")
    push_shop_ads(date_str, shop_d)

    # Product level
    print("\n📦 Collect product-level ads...")
    product_records = collect_product_ads(date_dmy, date_str)
    push_product_ads(product_records)

    # Komparasi
    print("\n📋 Push komparasi...")
    push_komparasi(date_str, product_records)

    # Alerts
    print("\n🔍 Check alerts...")
    check_alerts(date_str, shop_d)

    print("\n✅ zeodda_ads.py — DONE")


if __name__ == "__main__":
    main()
