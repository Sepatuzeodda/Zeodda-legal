"""
zeodda_daily_overview.py
========================
Daily Overview — pull data dari Shopee & push ke Lark Base.
Run via GitHub Actions setiap hari jam 00:00 WIB (17:00 UTC).

API yang dipakai (semua ✅):
  - get_shop_performance       → Skor Performa Toko
  - get_penalty_point_history  → Poin Penalti
  - get_late_orders            → Order Terlambat
  - get_listings_with_issues   → Produk Bermasalah
  - get_total_balance          → Saldo Iklan
  - get_order_list             → Total Order Masuk
  - get_order_detail           → Omzet Gross (incl ongkir)
  - get_return_list            → Total Retur
  - get_income_overview        → Omzet Harian (excl ongkir)
  - get_all_cpc_ads_daily_performance → (cross-check saldo iklan)
  - get_shop_toggle_info       → (info saja)

  - get_shop_info              → ❌ SKIP (follower_count) — permission belum aktif
                                 Setelah aktif: uncomment bagian FOLLOWER di bawah
"""

import sys
import os
import traceback

# Pastikan folder scripts ada di path (jika run dari root repo)
sys.path.insert(0, os.path.dirname(__file__))

from zeodda_helpers import (
    shopee_get,
    lark_add,
    lark_init,
    safe_int,
    safe_str,
    safe_dict,
    safe_list,
    get_yesterday_range,
    TABLE_DAILY_OVERVIEW,
    TABLE_ALERT_LOG,
)

PLATFORM = "Shopee"


# ─────────────────────────────────────────────
# HELPER: simpan alert ke Lark
# ─────────────────────────────────────────────
def push_alert(token, app_token, date_str, tipe, detail, nilai_saat_ini, nilai_normal, prioritas="Medium"):
    lark_add(token, app_token, TABLE_ALERT_LOG, {
        "Tanggal":        date_str,
        "Platform":       PLATFORM,
        "Tipe Alert":     tipe,
        "Detail":         detail,
        "Nilai Saat Ini": str(nilai_saat_ini),
        "Nilai Normal":   str(nilai_normal),
        "Prioritas":      prioritas,
        "Status":         "Open",
    })


# ─────────────────────────────────────────────
# COLLECT DATA
# ─────────────────────────────────────────────
def collect(d):
    """Kumpulkan semua data dari Shopee API ke dict d."""

    ts_start = d["ts_start"]
    ts_end   = d["ts_end"]
    date_dmy = d["date_str_dmy"]   # DD-MM-YYYY (untuk CPC)

    # ── 1. Shop Performance ────────────────────────────────────
    perf = shopee_get("/api/v2/shop/get_shop_performance", {})
    perf_data = safe_dict(perf, "response")
    d["skor_performa"]   = safe_int(perf_data, "overall_performance")       # 1–5
    d["rating_toko"]     = perf_data.get("shop_star")                       # bintang, kalau ada

    # ── 2. Penalty Points ──────────────────────────────────────
    penalty = shopee_get("/api/v2/shop/get_penalty_point_history", {
        "page_size": 100,
        "page_no": 1,
    })
    penalty_list = safe_list(safe_dict(penalty, "response"), "penalty_point_list")
    # Jumlah poin aktif (belum expired) dari kemarin
    total_penalty = sum(
        safe_int(p, "penalty_point")
        for p in penalty_list
        if safe_int(p, "status") == 1          # status 1 = aktif
    )
    d["poin_penalti"] = total_penalty

    # ── 3. Late Orders ─────────────────────────────────────────
    late = shopee_get("/api/v2/logistics/get_late_orders", {
        "page_size": 100,
        "page_no": 1,
        "create_time_from": ts_start,
        "create_time_to":   ts_end,
    })
    d["order_terlambat"] = len(safe_list(safe_dict(late, "response"), "order_list"))

    # ── 4. Listings with Issues ────────────────────────────────
    issues = shopee_get("/api/v2/product/get_listings_with_issues", {
        "page_size": 100,
        "page_no": 1,
    })
    d["produk_bermasalah"] = len(safe_list(safe_dict(issues, "response"), "item_list"))

    # ── 5. Ads Balance ─────────────────────────────────────────
    balance = shopee_get("/api/v2/ads/get_total_balance", {})
    d["saldo_iklan"] = safe_dict(balance, "response").get("total_balance", 0)

    # ── 6. Orders (masuk + cancelled + omzet gross) ────────────
    order_resp = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from":        ts_start,
        "time_to":          ts_end,
        "page_size":        100,
        "order_status":     "ALL",
        "response_optional_fields": "order_status",
    })
    order_data = safe_dict(order_resp, "response")
    order_list = safe_list(order_data, "order_list")

    sn_all       = [o["order_sn"] for o in order_list if "order_sn" in o]
    sn_cancelled = [o["order_sn"] for o in order_list if o.get("order_status") == "CANCELLED"]

    d["total_order_masuk"]      = len(sn_all)
    d["total_order_dibatalkan"] = len(sn_cancelled)

    # Omzet gross: sum dari order detail (semua status kecuali CANCELLED)
    sn_valid = [sn for sn in sn_all if sn not in sn_cancelled]
    omzet_gross = 0
    if sn_valid:
        # Shopee max 50 per request detail
        for i in range(0, len(sn_valid), 50):
            chunk = sn_valid[i:i+50]
            detail = shopee_get("/api/v2/order/get_order_detail", {
                "order_sn_list": ",".join(chunk),
                "response_optional_fields": "total_amount",
            })
            for order in safe_list(safe_dict(detail, "response"), "order_list"):
                omzet_gross += order.get("total_amount", 0)
    d["omzet_gross"] = omzet_gross

    # ── 7. Returns ─────────────────────────────────────────────
    ret = shopee_get("/api/v2/returns/get_return_list", {
        "page_size": 100,
        "page_no":   1,
        "create_time_from": ts_start,
        "create_time_to":   ts_end,
    })
    d["total_retur"] = len(safe_list(safe_dict(ret, "response"), "return_list"))

    # ── 8. Income Overview (omzet harian excl ongkir) ──────────
    income = shopee_get("/api/v2/payment/get_income_overview", {
        "start_time": ts_start,
        "end_time":   ts_end,
    })
    income_data = safe_dict(income, "response")
    # Field bisa berbeda per region; coba beberapa kemungkinan nama field
    d["omzet_harian"] = (
        income_data.get("revenue_from_products")
        or income_data.get("total_revenue")
        or income_data.get("net_income")
        or 0
    )

    # ── 9. CPC Ads Performance (cross-check) ───────────────────
    cpc = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {
        "start_date": date_dmy,
        "end_date":   date_dmy,
    })
    cpc_data = safe_list(safe_dict(cpc, "response"), "daily_performance_list")
    # Hanya untuk cross-check / transparansi — data utama saldo dari get_total_balance
    d["cpc_spend"] = sum(item.get("daily_spend", 0) for item in cpc_data)

    # ── 10. FOLLOWER (SKIP — permission belum aktif) ────────────
    # Uncomment setelah permission Shop di Console aktif:
    #
    # shop_info = shopee_get("/api/v2/shop/get_shop_info", {})
    # d["follower_toko"] = safe_dict(shop_info, "response").get("follower_count", 0)
    d["follower_toko"] = 0   # placeholder

    return d


# ─────────────────────────────────────────────
# PUSH TO LARK
# ─────────────────────────────────────────────
def push_to_lark(token, app_token, d):
    record = {
        "Tanggal":                d["date_str"],          # YYYY-MM-DD
        "Platform":               PLATFORM,
        "Total Order Masuk":      d["total_order_masuk"],
        "Total Order Dibatalkan": d["total_order_dibatalkan"],
        "Total Retur":            d["total_retur"],
        "Omzet Harian":           d["omzet_harian"],       # excl ongkir
        "Omzet Gross":            d["omzet_gross"],         # incl ongkir ≈ Seller Center
        "Follower Toko":          d["follower_toko"],
        "Skor Performa Toko":     d["skor_performa"],
        "Poin Penalti":           d["poin_penalti"],
        "Order Terlambat":        d["order_terlambat"],
        "Produk Bermasalah":      d["produk_bermasalah"],
        "Saldo Iklan":            d["saldo_iklan"],
    }
    lark_add(token, app_token, TABLE_DAILY_OVERVIEW, record)
    print(f"✅ Daily Overview pushed → {d['date_str']}")


# ─────────────────────────────────────────────
# ALERTS CHECK
# ─────────────────────────────────────────────
def check_alerts(token, app_token, d):
    """Cek kondisi abnormal & kirim alert ke Lark."""
    date_str = d["date_str"]

    alerts = []

    # Penalty tinggi (>= 5 poin)
    if d["poin_penalti"] >= 5:
        alerts.append(("Penalti Tinggi", f"Poin penalti mencapai {d['poin_penalti']}",
                        d["poin_penalti"], "< 5", "High"))

    # Order terlambat
    if d["order_terlambat"] > 0:
        alerts.append(("Order Terlambat", f"{d['order_terlambat']} order terlambat kemarin",
                        d["order_terlambat"], "0", "High"))

    # Produk bermasalah
    if d["produk_bermasalah"] > 0:
        alerts.append(("Produk Bermasalah", f"{d['produk_bermasalah']} produk butuh perhatian",
                        d["produk_bermasalah"], "0", "Medium"))

    # Saldo iklan rendah (< 100.000)
    if d["saldo_iklan"] < 100_000:
        alerts.append(("Saldo Iklan Rendah", f"Saldo iklan Rp {d['saldo_iklan']:,.0f}",
                        d["saldo_iklan"], ">= 100.000", "High"))

    # Retur tinggi (> 3)
    if d["total_retur"] > 3:
        alerts.append(("Retur Tinggi", f"{d['total_retur']} retur kemarin",
                        d["total_retur"], "<= 3", "Medium"))

    # Omzet 0 (mungkin ada issue API)
    if d["omzet_gross"] == 0 and d["total_order_masuk"] > 0:
        alerts.append(("Omzet Gross 0", "Ada order tapi omzet gross = 0, cek API",
                        0, "> 0", "High"))

    for tipe, detail, nilai, normal, prioritas in alerts:
        push_alert(token, app_token, date_str, tipe, detail, nilai, normal, prioritas)
        print(f"⚠️  Alert [{prioritas}]: {tipe} — {detail}")

    if not alerts:
        print("✅ No alerts triggered.")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 50)
    print("🚀 zeodda_daily_overview.py — START")
    print("=" * 50)

    # Init Lark
    token, app_token = lark_init()

    # Ambil range waktu kemarin
    time_data = get_yesterday_range()
    print(f"📅 Tanggal: {time_data['date_str']} ({time_data['date_str_dmy']})")
    print(f"⏱️  Range: {time_data['ts_start']} → {time_data['ts_end']}")

    # Collect
    d = dict(time_data)
    try:
        d = collect(d)
    except Exception as e:
        print(f"❌ ERROR saat collect data: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Debug print
    print("\n📊 Hasil Collect:")
    for k, v in d.items():
        if k not in ("ts_start", "ts_end", "yesterday_ms"):
            print(f"   {k}: {v}")

    # Push ke Lark
    try:
        push_to_lark(token, app_token, d)
    except Exception as e:
        print(f"❌ ERROR saat push Lark: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Alerts
    try:
        check_alerts(token, app_token, d)
    except Exception as e:
        print(f"⚠️  ERROR saat check alerts (non-fatal): {e}")
        traceback.print_exc()

    print("\n✅ zeodda_daily_overview.py — DONE")


if __name__ == "__main__":
    main()
