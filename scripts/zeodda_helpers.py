"""
scripts/zeodda_daily_overview.py
Mengambil data ringkasan harian dari Shopee API dan menyimpannya ke Lark Base TABLE_DAILY_OVERVIEW.
Revisi: Memperbaiki pemanggilan lark_init() yang tidak mengembalikan nilai (None) agar tidak memicu TypeError.
"""

from zeodda_helpers import *

def main():
    try:
        # Perbaikan: lark_init() di zeodda_helpers.py tidak me-return apapun (None).
        # Jangan melakukan unpacking variable seperti `token, app_token = lark_init()` karena memicu TypeError.
        lark_init() 
        
        # Ambil range waktu kemarin WIB
        date_info = get_yesterday_range()
        yesterday_str = date_info["date_str"] # Format YYYY-MM-DD
        
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
                        total_order_batal += 1
                    elif status in ["COMPLETED", "PROCESSED", "SHIPPED"]:
                        omzet_harian += escrow_amount
                        omzet_gross += total_amount
                    else:
                        omzet_gross += total_amount

        # 7. Ambil Data Retur (get_return_list)
        return_params = {
            "create_time_from": date_info["ts_start"],
            "create_time_to": date_info["ts_end"],
            "page_size": 100
        }
        return_res = shopee_get("/api/v2/return/get_return_list", return_params)
        total_retur = len(safe_list(return_res, "return_list"))

        # 8. Mapping fields ke Lark Base
        lark_fields = {
            "Tanggal": yesterday_str,
            "Platform": "Shopee",
            "Total Order Masuk": total_order_masuk,
            "Total Order Dibatalkan": total_order_batal,
            "Total Retur": total_retur,
            "Omzet Harian": omzet_harian,
            "Omzet Gross": omzet_gross,
            "Follower Toko": 0, 
            "Skor Performa Toko": shop_score,
            "Poin Penalti": penalty_points,
            "Order Terlambat": late_orders,
            "Produk Bermasalah": issue_products,
            "Saldo Iklan": ads_balance
        }
        
        # 9. Push data ke Lark Base
        print(f"📤 Mengirim data ke Lark Base...")
        res = lark_add(TABLE_DAILY_OVERVIEW, lark_fields)
        
        if res.get("code") == 0:
            print("✅ Sukses sinkronisasi Daily Overview ke Lark Base.")
        else:
            print(f"❌ Gagal sinkronisasi. Response: {res}")
            
    except Exception as e:
        print(f"💥 Terjadi fatal error pada script: {e}")
        raise e # Re-raise error agar GitHub Actions menandakan step ini gagal

if __name__ == "__main__":
    main()
