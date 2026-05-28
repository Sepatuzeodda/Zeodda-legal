"""
scripts/zeodda_daily_overview.py
Daily Overview — pull data dari Shopee & push ke Lark Base.
Revisi: Menambahkan print log debug detail untuk melacak kenapa data tidak masuk ke Lark Base.
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(__file__))

from zeodda_helpers import *

PLATFORM = "Shopee"

def push_alert(date_str, tipe, detail, nilai_saat_ini, nilai_normal, prioritas="Medium"):
    payload = {
        "Tanggal":        date_str,
        "Platform":       PLATFORM,
        "Tipe Alert":     tipe,
        "Detail":         detail,
        "Nilai Saat Ini": str(nilai_saat_ini),
        "Nilai Normal":   str(nilai_normal),
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
    print(f"🔍 [DEBUG SHOPEE] get_shop_performance raw response: {perf}")
    d["skor_performa"]   = safe_int(perf.get("overall_rating"))
    d["rating_toko"]     = perf.get("overall_rating")

    # 2. Penalty Points
    penalty = shopee_get("/api/v2/seller_data/get_penalty_point_history", {"page_size": 100, "page_no": 1})
    print(f"🔍 [DEBUG SHOPEE] get_penalty_point_history raw response: {penalty}")
    d["poin_penalti"] = safe_int(penalty.get("total_penalty_points"))

    # 3. Late Orders
    late = shopee_get("/api/v2/seller_data/get_late_orders", {"page_size": 100, "page_no": 1, "create_time_from": ts_start, "create_time_to": ts_end})
    print(f"🔍 [DEBUG SHOPEE] get_late_orders raw response: {late}")
    d["order_terlambat"] = safe_int(late.get("total_late_orders"))

    # 4. Listings with Issues
    issues = shopee_get("/api/v2/product/get_listings_with_issues", {"page_size": 100, "page_no": 1})
    print(f"🔍 [DEBUG SHOPEE] get_listings_with_issues raw response: {issues}")
    d["produk_bermasalah"] = safe_int(issues.get("total_issues"))

    # 5. Ads Balance
    balance = shopee_get("/api/v2/ads/get_total_balance", {})
    print(f"🔍 [DEBUG SHOPEE] get_total_balance raw response: {balance}")
    d["saldo_iklan"] = safe_int(balance.get("total_balance"))

    # 6. Orders
    order_resp = shopee_get("/api/v2/order/get_order_list", {"time_range_field": "create_time", "time_from": ts_start, "time_to": ts_end, "page_size": 100})
    print(f"🔍 [DEBUG SHOPEE] get_order_list raw response: {order_resp}")
    order_list = safe_list(order_resp, "order_list")
    sn_all = [o["order_sn"] for o in order_list if "order_sn" in o]
    print(f"🔍 [DEBUG SHOPEE] Total Order ID ditemukan: {len(sn_all)} ({sn_all})")
    
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
    print(f"🔍 [DEBUG SHOPEE] get_return_list raw response: {ret}")
    d["total_retur"] = len(safe_list(ret, "return_list"))

    # 8. Income Overview
    income = shopee_get("/api/v2/payment/get_income_overview", {"start_time": ts_start, "end_time": ts_end})
    print(f"🔍 [DEBUG SHOPEE] get_income_overview raw response: {income}")
    d["omzet_harian"] = safe_int(income.get("revenue_from_products") or income.get("total_revenue"))

    # 9. CPC Ads
    cpc = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {"start_date": date_dmy, "end_date": date_dmy})
    cpc_data = safe_list(cpc, "daily_performance_list")
    d["cpc_spend"] = sum(item.get("daily_spend", 0) for item in cpc_data)

    d["follower_toko"] = 0
    return d

def push_to_lark(d):
    record = {
        "
