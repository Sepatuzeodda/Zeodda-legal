"""
scripts/zeodda_daily_overview.py
Daily Overview — pull data dari Shopee & push ke Lark Base.
Revisi: Perbaikan tipe data field pada alert (NumberFieldConvFail).
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from zeodda_helpers import *

PLATFORM = "Shopee"

def push_alert(date_ms, tipe, detail, nilai_saat_ini, nilai_normal, prioritas="Medium"):
    # Kolom Nilai di Lark diset sebagai tipe Number, wajib dikirim berupa angka integer murni
    payload = {
        "Tanggal":        int(date_ms), 
        "Platform":       PLATFORM,
        "Tipe Alert":     tipe,
        "Detail":         detail,
        "Nilai Saat Ini": int(nilai_saat_ini),
        "Nilai Normal":   int(nilai_normal),
        "Prioritas":      prioritas,
        "Status":         "Open",
    }
    print(f"🤖 [DEBUG ALERT] Mencoba push alert ke Lark: {payload}")
    res = lark_add(TABLE_ALERT_LOG, payload)
    print(f"🤖 [DEBUG ALERT] Respon Lark: {res}")

def collect(d):
    """Kumpulkan semua data dari Shopee API ke dict d."""
    ts_start = d["ts_start"]
    ts_end   = d["ts_end"]
    date_dmy = d["date_str_dmy"]

    # 1. Shop Performance
    perf = shopee_get("/api/v2/seller_data/get_shop_performance", {})
    d["skor_performa"]   = safe_int(perf.get("overall_rating"))
    d["rating_toko"]     = perf.get("overall_rating")

    # 2. Penalty Points
    penalty = shopee_get("/api/v2/seller_data/get_penalty_point_history", {"page_size": 100, "page_no": 1})
    d["poin_penalti"] = safe_int(penalty.get("total_penalty_points"))

    # 3. Late Orders
    late = shopee_get("/api/v2/seller_data/get_late_orders", {"page_size": 100, "page_no": 1, "create_time_from": ts_start, "create_time_to": ts_end})
    d["order_terlambat"] = safe_int(late.get("total_late_orders"))

    # 4. Listings with Issues
    issues = shopee_get("/api/v2/product/get_listings_with_issues", {"page_size": 100, "page_no": 1})
    d["produk_bermasalah"] = safe_int(issues.get("total_issues"))

    # 5. Ads Balance
    balance = shopee_get("/api/v2/ads/get_total_balance", {})
    d["saldo_iklan"] = safe_int(balance.get("total_balance"))

    # 6. Orders
    order_resp = shopee_get("/api/v2/order/get_order_list", {"time_range_field": "create_time", "time_from": ts_start, "time_to": ts_end, "page_size": 100})
    order_list = safe_list(order_resp, "order_list")
    sn_all = [o["order_sn"] for o in order_list if "order_sn" in o]
    
    total_order_masuk = 0
    total_order_dibatalkan = 0
    omzet_gross = 0

    if sn_all:
        for i in range(0, len(sn_all), 50):
            chunk = sn_all[i:i+50]
            detail = shopee_get("/api/v2/order/get_order_detail", {"order_sn_list": ",".join(chunk)})
            for order in safe_list(detail, "order_list"):
                total_order_masuk += 1
                status = order.get("order_status", "")
                total_amount = safe_int(order.get("total_amount"))
                if status == "CANCELLED":
                    total_order_dibatalkan += 1
                else:
                    omzet_gross += total_amount

    d["total_order_masuk"]      = total_order_masuk
    d["total_order_dibatalkan"] = total_order_dibatalkan
    d["omzet_gross"]            = omzet_gross

    # 7. Returns
    ret = shopee_get("/api/v2/return/get_return_list", {"page_size": 100, "page_no": 1, "create_time_from": ts_start, "create_time_to": ts_end})
    d["total_retur"] = len(safe_list(ret, "return_list"))

    # 8. Income Overview
    income = shopee_get("/api/v2/payment/get_income_overview", {"start_time": ts_start, "end_time": ts_end})
    d["omzet_harian"] = safe_int(income.get("revenue_from_products") or income.get("total_revenue"))

    # 9. CPC Ads
    cpc = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {"start_date": date_dmy, "end_date": date_dmy})
    cpc_data = safe_list(cpc, "daily_performance_list")
    d["cpc_spend"] = sum(item.get("daily_spend", 0) for item in cpc_data)

    d["follower_toko"] = 0
    return d

def push_to_lark(d):
    record = {
        "Tanggal":                int(d["yesterday_ms"]),
        "Platform":               PLATFORM,
        "Total Order Masuk":      d["total_order_masuk"],
        "Total Order Dibatalkan": d["total_order_dibatalkan"],
        "Total Retur":            d["total_retur"],
        "Omzet Harian":           d["omzet_harian"],
        "Omzet Gross":            d["omzet_gross"],
        "Follower Toko":          d["follower_toko"],
        "Skor Performa Toko":     d["skor_performa"],
        "Poin Penalti":           d["poin_penalti"],
        "Order Terlambat":        d["order_terlambat"],
        "Produk Bermasalah":      d["produk_bermasalah"],
        "Saldo Iklan":            d["saldo_iklan"],
    }
    print(f"📤 [DEBUG LARK] Mengirim data payload ke Lark Base: {record}")
    res = lark_add(TABLE_DAILY_OVERVIEW, record)
    print(f"📥 [DEBUG LARK] Respon balik dari Lark Base API: {res}")

def check_alerts(d):
    date_ms = d["yesterday_ms"]
    alerts = []
    if d["poin_penalti"] >= 5:
        alerts.append(("Penalti Tinggi", f"Poin penalti mencapai {d['poin_penalti']}", d["poin_penalti"], 0, "High"))
    if d["order_terlambat"] > 0:
        alerts.append(("Order Terlambat", f"{d['order_terlambat']} order terlambat kemarin", d["order_terlambat"], 0, "High"))
    if d["produk_bermasalah"] > 0:
        alerts.append(("Produk Bermasalah", f"{d['produk_bermasalah']} produk butuh perhatian", d["produk_bermasalah"], 0, "Medium"))
    if d["saldo_iklan"] < 100_000:
        alerts.append(("Saldo Iklan Rendah", f"Saldo iklan Rp {d['saldo_iklan']:,.0f}", d["saldo_iklan"], 100000, "High"))
    if d["total_retur"] > 3:
        alerts.append(("Retur Tinggi", f"{d['total_retur']} retur kemarin", d["total_retur"], 3, "Medium"))
    if d["omzet_gross"] == 0 and d["total_order_masuk"] > 0:
        alerts.append(("Omzet Gross 0", "Ada order tapi omzet gross = 0, cek API", 0, 1, "High"))

    for tipe, detail, nilai, normal, prioritas in alerts:
        push_alert(date_ms, tipe, detail, nilai, normal, prioritas)

def main():
    print("=" * 50)
    print("🚀 zeodda_daily_overview.py — START")
    print("=" * 50)

    lark_init()
    time_data = get_yesterday_range()
    
    d = dict(time_data)
    try:
        d = collect(d)
    except Exception as e:
        print(f"❌ ERROR saat collect data: {e}")
        traceback.print_exc()
        sys.exit(1)

    try:
        push_to_lark(d)
    except Exception as e:
        print(f"❌ ERROR saat push Lark: {e}")
        traceback.print_exc()
        sys.exit(1)

    try:
        check_alerts(d)
    except Exception as e:
        print(f"⚠️ ERROR saat check alerts: {e}")

    print("\n✅ zeodda_daily_overview.py — DONE")

if __name__ == "__main__":
    main()
