"""
scripts/zeodda_daily_overview.py
Mengambil data ringkasan harian dari Shopee API dan menyimpannya ke Lark Base TABLE_DAILY_OVERVIEW.
Revisi: Menggunakan wildcard import (from zeodda_helpers import *) untuk menghindari ImportError akibat penulisan daftar fungsi manual yang salah di line 31.
"""

# Gunakan wildcard import agar seluruh helper (shopee_get, lark_init, dll.) terbawa otomatis tanpa error
from zeodda_helpers import *

def main():
    try:
        # Inisialisasi token Lark
        lark_init() 
        
        # Ambil range waktu kemarin WIB
        date_info = get_yesterday_range()
        yesterday_str = date_info["date_str"]
        
        print(f"🚀 Memulai penarikan data Daily Overview untuk tanggal: {yesterday_str}")
        
        # 1. Ambil Data Performa Toko (get_shop_performance)
        perf_data = shopee_get("/api/v2/seller_data/get_shop_performance")
        shop_score = safe_int(perf_data.get("overall_rating"))
        
        # 2. Ambil Data Poin Penalti (get_penalty_point_history)
        penalty_data = shopee_get("/api/v2/seller_data/get_penalty_point_history")
        penalty_points = safe_int(penalty_data.get("total_penalty_points"))
        
        # 3. Ambil Data Order Terlambat (get_late_orders)
        late_data = shopee_get("/api/v2/seller_data/get_late_orders")
        late_orders = safe_int(late_data.get("total_late_orders"))
        
        # 4. Ambil Data Produk Bermasalah (get_listings_with_issues)
        issues_data = shopee_get("/api/v2/product/get_listings_with_issues")
        issue_products = safe_int(issues_data.get("total_issues"))
        
        # 5. Ambil Data Saldo Iklan (get_total_balance)
        ads_balance_data = shopee_get("/api/v2/ads/get_total_balance")
        ads_balance = safe_int(ads_balance_data.get("total_balance"))
        
        # 6. Ambil Data Order dan Omzet (get_order_list & get_order_detail)
        order_params = {
            "time_range_field": "create_time",
            "time_from": date_info["ts_start"],
            "time_to": date_info["ts_end"],
            "page_size": 100
        }
        
        total_order_masuk = 0
        total_order_batal = 0
        omzet_harian = 0 
        omzet_gross = 0  
        
        order_list_res = shopee_get("/api/v2/order/get_order_list", order_params)
        order_ids = [o.get("order_sn") for o in safe_list(order_list_res, "order_list")]
        
        if order_ids:
            for i in range(0, len(order_ids), 50):
                batch_ids = order_ids[i:i+50]
                detail_res = shopee_get("/api/v2/order/get_order_detail", {"order_sn_list": ",".join(batch_ids)})
                for order in safe_list(detail_res, "order_list"):
                    total_order_masuk += 1
                    status = order.get("order_status", "")
                    escrow_amount = safe_int(safe_dict(order, "financial_mechanism").get("escrow_amount"))
                    total_amount = safe_int(order.get("total_amount"))
                    
                    if status == "CANCELLED":
                        total_order_b
