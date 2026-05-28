"""
zeodda_financial.py
===================
Financial Summary → Lark Base.

API yang dipakai:
  - get_income_overview    ✅ → gross revenue
  - get_return_list        ✅ → total retur
  - get_all_cpc_ads_daily_performance ✅ → spend iklan
  - get_order_detail       ✅ → biaya platform (dari fee fields)
  - get_order_list         ✅ → list order kemarin

  - get_payout_info        ❌ SKIP — butuh fix params (cursor)
  - get_billing_transaction_info ❌ SKIP — butuh billing_transaction_info_type
  - get_escrow_list        ❓ SKIP — belum konfirmasi

  Setelah fix → uncomment bagian PAYOUT & BILLING di bawah.
"""

import sys
import os
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
    TABLE_FINANCIAL,
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
# COLLECT
# ─────────────────────────────────────────────

def collect(t):
    d          = {}
    date_str   = t["date_str"]
    date_dmy   = t["date_str_dmy"]
    ts_start   = t["ts_start"]
    ts_end     = t["ts_end"]

    # ── 1. Gross Revenue (income overview) ────────────────────
    income = shopee_get("/api/v2/payment/get_income_overview", {
        "start_time": ts_start,
        "end_time":   ts_end,
    })
    d["gross_revenue"] = (
        income.get("revenue_from_products")
        or income.get("total_revenue")
        or income.get("net_income")
        or 0
    )

    # ── 2. Biaya Platform (dari order detail fee fields) ───────
    order_resp = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from":        ts_start,
        "time_to":          ts_end,
        "page_size":        100,
        "order_status":     "ALL",
        "response_optional_fields": "order_status",
    })
    order_list = safe_list(order_resp, "order_list")
    sn_valid   = [
        o["order_sn"] for o in order_list
        if "order_sn" in o and o.get("order_status") != "CANCELLED"
    ]

    biaya_platform = 0
    for chunk in chunks(sn_valid, 50):
        detail_resp = shopee_get("/api/v2/order/get_order_detail", {
            "order_sn_list": ",".join(chunk),
            "response_optional_fields": "income_details",
        })
        for order in safe_list(detail_resp, "order_list"):
            income_d = safe_dict(order, "income_details") or safe_dict(order, "escrow_detail")
            # Field nama bisa berbeda per region
            biaya_platform += (
                income_d.get("shopee_commission_fee", 0)
                + income_d.get("service_fee", 0)
                + income_d.get("transaction_fee", 0)
            )

    d["biaya_platform"] = biaya_platform

    # ── 3. Spend Iklan ─────────────────────────────────────────
    cpc_resp  = shopee_get("/api/v2/ads/get_all_cpc_ads_daily_performance", {
        "start_date": date_dmy,
        "end_date":   date_dmy,
    })
    perf_list = safe_list(cpc_resp, "daily_performance_list")
    d["spend_iklan"] = perf_list[0].get("daily_spend", 0) if perf_list else 0

    # ── 4. Total Retur ─────────────────────────────────────────
    ret_resp = shopee_get("/api/v2/returns/get_return_list", {
        "page_size":        100,
        "page_no":          1,
        "create_time_from": ts_start,
        "create_time_to":   ts_end,
    })
    d["total_retur"] = len(safe_list(ret_resp, "return_list"))

    # ── 5. Pencairan (SKIP — fix params pending) ───────────────
    # Uncomment setelah fix cursor param:
    #
    # payout = shopee_get("/api/v2/payment/get_payout_info", {
    #     "page_size": 20,
    #     "page_no":   1,
    #     "cursor":    "",
    # })
    # payout_list = safe_list(payout, "payout_list")
    # d["pencairan"] = sum(p.get("amount", 0) for p in payout_list
    #                      if p.get("payout_time", 0) >= ts_start
    #                      and p.get("payout_time", 0) <= ts_end)
    d["pencairan"] = 0  # placeholder

    # ── 6. Escrow Pending (SKIP — belum konfirmasi) ────────────
    # Uncomment setelah konfirmasi field names:
    #
    # escrow = shopee_get("/api/v2/payment/get_escrow_list", {
    #     "release_time_from": ts_start,
    #     "release_time_to":   ts_end,
    #     "page_size": 100,
    #     "page_no":   1,
    # })
    # escrow_list = safe_list(escrow, "escrow_list")
    # d["escrow_pending"] = sum(e.get("escrow_amount", 0) for e in escrow_list)
    d["escrow_pending"] = 0  # placeholder

    return d


# ─────────────────────────────────────────────
# PUSH TO LARK
# ─────────────────────────────────────────────

def push_to_lark(date_str, d):
    record = {
        "Tanggal":              date_str,
        "Platform":             PLATFORM,
        "Gross Revenue":        d["gross_revenue"],
        "Biaya Platform":       d["biaya_platform"],
        "Spend Iklan":          d["spend_iklan"],
        "Dana Escrow Pending":  d["escrow_pending"],
        "Pencairan Hari Ini":   d["pencairan"],
        "Total Retur":          d["total_retur"],
    }
    lark_add(TABLE_FINANCIAL, record)
    print(f"✅ Financial pushed → {date_str}")


# ─────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────

def check_alerts(date_str, d):
    triggered = False

    # Gross revenue 0 padahal ada order
    if d["gross_revenue"] == 0:
        push_alert(date_str, "Gross Revenue 0",
                   "Gross revenue = 0, kemungkinan issue API income_overview",
                   0, "> 0", "High")
        triggered = True

    # Biaya platform sangat tinggi (> 20% gross)
    if d["gross_revenue"] > 0:
        ratio = d["biaya_platform"] / d["gross_revenue"]
        if ratio > 0.20:
            push_alert(date_str, "Biaya Platform Tinggi",
                       f"Biaya platform {ratio*100:.1f}% dari gross revenue",
                       f"{ratio*100:.1f}%", "< 20%", "Medium")
            triggered = True

    # Spend iklan tinggi vs revenue iklan (kalau ada data)
    if d["spend_iklan"] > 0 and d["gross_revenue"] > 0:
        spend_ratio = d["spend_iklan"] / d["gross_revenue"]
        if spend_ratio > 0.30:
            push_alert(date_str, "Spend Iklan Tinggi",
                       f"Spend iklan {spend_ratio*100:.1f}% dari gross revenue",
                       f"{spend_ratio*100:.1f}%", "< 30%", "Medium")
            triggered = True

    if not triggered:
        print("✅ No financial alerts triggered.")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 50)
    print("🚀 zeodda_financial.py — START")
    print("=" * 50)

    lark_init()

    t        = get_yesterday_range()
    date_str = t["date_str"]
    print(f"📅 Tanggal: {date_str}")

    print("\n📊 Collect financial data...")
    d = collect(t)

    print(f"   Gross Revenue : Rp {d['gross_revenue']:,.0f}")
    print(f"   Biaya Platform: Rp {d['biaya_platform']:,.0f}")
    print(f"   Spend Iklan   : Rp {d['spend_iklan']:,.0f}")
    print(f"   Pencairan     : Rp {d['pencairan']:,.0f}  (pending fix)")
    print(f"   Escrow Pending: Rp {d['escrow_pending']:,.0f}  (pending konfirmasi)")
    print(f"   Total Retur   : {d['total_retur']}")

    push_to_lark(date_str, d)

    print("\n🔍 Check alerts...")
    check_alerts(date_str, d)

    print("\n✅ zeodda_financial.py — DONE")


if __name__ == "__main__":
    main()
