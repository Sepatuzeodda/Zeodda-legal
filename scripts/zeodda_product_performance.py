"""
zeodda_product_performance.py
==============================
Product Performance — pull data per produk dari Shopee & push ke Lark Base.

API yang dipakai:
  - get_item_list          ✅ → list semua item_id
  - get_item_base_info     ✅ → nama, harga, status, kategori
  - get_item_extra_info    ✅ → stok, terjual, views
  - get_boosted_list       ✅ → status boost
  - get_discount_list      ✅ → promo aktif
  - get_comment            ✅ → rating, review per bintang
  - get_order_list +
    get_order_detail       ✅ → revenue & terjual hari ini per produk
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
    TABLE_PRODUCT_PERF,
    TABLE_ALERT_LOG,
    PLATFORM,
)

PLATFORM = "Shopee"
CHUNK = 50  # max item per request Shopee


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


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


# ─────────────────────────────────────────────
# COLLECT
# ─────────────────────────────────────────────

def get_all_item_ids():
    """Ambil semua item_id aktif dari toko."""
    item_ids = []
    page = 0
    while True:
        resp = shopee_get("/api/v2/product/get_item_list", {
            "offset":      page * 100,
            "page_size":   100,
            "item_status": "NORMAL",
        })
        items = safe_list(resp, "item")
        if not items:
            break
        item_ids.extend(i["item_id"] for i in items if "item_id" in i)
        if not resp.get("has_next_page"):
            break
        page += 1
    return item_ids


def get_base_info_map(item_ids):
    """Batch: nama, harga, status, kategori."""
    result = {}
    for chunk in chunks(item_ids, CHUNK):
        resp = shopee_get("/api/v2/product/get_item_base_info", {
            "item_id_list": ",".join(str(i) for i in chunk),
        })
        for item in safe_list(resp, "item_list"):
            iid = item.get("item_id")
            if not iid:
                continue
            # Harga dari model pertama
            models = safe_list(item, "model_list") or safe_list(item, "price_info")
            harga = 0
            if models:
                pi = safe_list(models[0], "price_info")
                harga = pi[0].get("current_price", 0) if pi else models[0].get("current_price", 0)

            result[iid] = {
                "nama":      safe_str(item.get("item_name")),
                "kategori":  safe_str(item.get("category_id")),
                "harga":     harga,
                "status":    safe_str(item.get("item_status")),
            }
    return result


def get_extra_info_map(item_ids):
    """Batch: stok, total terjual kumulatif, views."""
    result = {}
    for chunk in chunks(item_ids, CHUNK):
        resp = shopee_get("/api/v2/product/get_item_extra_info", {
            "item_id_list": ",".join(str(i) for i in chunk),
        })
        for item in safe_list(resp, "item_list"):
            iid = item.get("item_id")
            if not iid:
                continue
            result[iid] = {
                "stok":           safe_int(item.get("total_reserved_stock", 0)) + safe_int(item.get("total_available_stock", 0)),
                "total_terjual":  safe_int(item.get("sold")),
                "views":          safe_int(item.get("view_count")),
            }
    return result


def get_boost_set():
    """Return set item_id yang sedang di-boost."""
    resp = shopee_get("/api/v2/product/get_boosted_list", {})
    boosted = safe_list(resp, "item_list")
    return {i["item_id"] for i in boosted if "item_id" in i}


def get_promo_set():
    """Return set item_id yang punya promo aktif."""
    resp = shopee_get("/api/v2/discount/get_discount_list", {
        "discount_status": 1,  # aktif
        "page_no":   1,
        "page_size": 100,
    })
    promo_set = set()
    for disc in safe_list(resp, "discount_list"):
        for item in safe_list(disc, "item_list"):
            iid = item.get("item_id")
            if iid:
                promo_set.add(iid)
    return promo_set


def get_review_map(item_ids, date_str):
    """Per item: rating, total review, breakdown bintang, review negatif baru."""
    result = {}
    for iid in item_ids:
        resp = shopee_get("/api/v2/item/get_comment", {
            "item_id":   iid,
            "page_size": 100,
            "page_no":   1,
        })
        comments  = safe_list(resp, "item_comment_list")
        rating    = resp.get("item_overall_star") or 0
        total_rev = safe_int(resp.get("item_comment_count"))

        star_count = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        neg_baru   = 0
        for c in comments:
            s = safe_int(c.get("rating_star"))
            if s in star_count:
                star_count[s] += 1
            # Review negatif baru (hari ini / kemarin)
            if s <= 2 and safe_str(c.get("create_time", ""))[:10] == date_str:
                neg_baru += 1

        result[iid] = {
            "rating":    rating,
            "total_rev": total_rev,
            "star5":     star_count[5],
            "star4":     star_count[4],
            "star3":     star_count[3],
            "star2":     star_count[2],
            "star1":     star_count[1],
            "neg_baru":  neg_baru,
        }
    return result


def get_sales_today_map(ts_start, ts_end):
    """
    Hitung terjual hari ini & revenue per item_id
    dari order_list + order_detail kemarin.
    """
    # Ambil order kemarin
    resp = shopee_get("/api/v2/order/get_order_list", {
        "time_range_field": "create_time",
        "time_from":        ts_start,
        "time_to":          ts_end,
        "page_size":        100,
        "order_status":     "ALL",
        "response_optional_fields": "order_status",
    })
    order_list = safe_list(resp, "order_list")
    sn_valid   = [
        o["order_sn"] for o in order_list
        if "order_sn" in o and o.get("order_status") != "CANCELLED"
    ]

    sales_map = {}  # item_id → {"qty": x, "revenue": y}

    for chunk in chunks(sn_valid, CHUNK):
        detail_resp = shopee_get("/api/v2/order/get_order_detail", {
            "order_sn_list": ",".join(chunk),
            "response_optional_fields": "item_list,total_amount",
        })
        for order in safe_list(detail_resp, "order_list"):
            for item in safe_list(order, "item_list"):
                iid = item.get("item_id")
                if not iid:
                    continue
                qty     = safe_int(item.get("model_quantity_purchased"))
                subtotal = item.get("model_discounted_price", 0) * qty
                if iid not in sales_map:
                    sales_map[iid] = {"qty": 0, "revenue": 0}
                sales_map[iid]["qty"]     += qty
                sales_map[iid]["revenue"] += subtotal

    return sales_map


# ─────────────────────────────────────────────
# PUSH TO LARK
# ─────────────────────────────────────────────

def push_to_lark(records):
    if not records:
        print("⚠️  Tidak ada record untuk di-push.")
        return
    # Batch push (max 500 per request Lark)
    for chunk in chunks(records, 100):
        lark_add_batch(TABLE_PRODUCT_PERF, chunk)
    print(f"✅ Product Performance pushed → {len(records)} produk")


# ─────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────

def check_alerts(date_str, item_ids, base_map, review_map, extra_map):
    for iid in item_ids:
        nama = base_map.get(iid, {}).get("nama", str(iid))

        # Stok habis
        stok = extra_map.get(iid, {}).get("stok", 0)
        if stok == 0:
            push_alert(date_str, "Stok Habis", f"{nama} stok = 0", 0, "> 0", "High")

        # Rating rendah
        rating = review_map.get(iid, {}).get("rating", 5)
        if rating and float(rating) < 4.0:
            push_alert(date_str, "Rating Rendah", f"{nama} rating {rating}", rating, ">= 4.0", "Medium")

        # Review negatif baru
        neg = review_map.get(iid, {}).get("neg_baru", 0)
        if neg > 0:
            push_alert(date_str, "Review Negatif Baru", f"{nama} dapat {neg} review ≤2 bintang kemarin",
                       neg, "0", "Medium")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 50)
    print("🚀 zeodda_product_performance.py — START")
    print("=" * 50)

    lark_init()

    t         = get_yesterday_range()
    date_str  = t["date_str"]
    ts_start  = t["ts_start"]
    ts_end    = t["ts_end"]
    print(f"📅 Tanggal: {date_str}")

    # Collect semua data
    print("📦 Ambil item list...")
    item_ids = get_all_item_ids()
    print(f"   → {len(item_ids)} produk ditemukan")

    if not item_ids:
        print("⚠️  Tidak ada produk aktif. Script selesai.")
        return

    print("📦 Ambil base info...")
    base_map  = get_base_info_map(item_ids)

    print("📦 Ambil extra info...")
    extra_map = get_extra_info_map(item_ids)

    print("📦 Ambil boost list...")
    boost_set = get_boost_set()

    print("📦 Ambil promo list...")
    promo_set = get_promo_set()

    print("📦 Ambil review per produk...")
    review_map = get_review_map(item_ids, date_str)

    print("📦 Hitung sales hari ini...")
    sales_map = get_sales_today_map(ts_start, ts_end)

    # Susun records
    records = []
    for iid in item_ids:
        base   = base_map.get(iid, {})
        extra  = extra_map.get(iid, {})
        review = review_map.get(iid, {})
        sales  = sales_map.get(iid, {"qty": 0, "revenue": 0})

        terjual_hari_ini = sales["qty"]
        revenue_produk   = sales["revenue"]
        views            = extra.get("views", 0)

        # CTR & CR sederhana (kalau views > 0)
        ctr = round(terjual_hari_ini / views * 100, 2) if views > 0 else 0
        cr  = round(terjual_hari_ini / views * 100, 2) if views > 0 else 0

        records.append({
            "Tanggal":                    date_str,
            "Platform":                   PLATFORM,
            "Nama Produk":                base.get("nama", ""),
            "Item ID":                    str(iid),
            "Kategori Produk":            base.get("kategori", ""),
            "Harga Jual":                 base.get("harga", 0),
            "Stok Tersisa":               extra.get("stok", 0),
            "Terjual Hari Ini":           terjual_hari_ini,
            "Total Terjual Kumulatif":    extra.get("total_terjual", 0),
            "Rating Bintang":             review.get("rating", 0),
            "Total Review":               review.get("total_rev", 0),
            "Review Bintang 5 ⭐⭐⭐⭐⭐":  review.get("star5", 0),
            "Review Bintang 4 ⭐⭐⭐⭐":   review.get("star4", 0),
            "Review Bintang 3 ⭐⭐⭐":     review.get("star3", 0),
            "Review Bintang 2 ⭐⭐":       review.get("star2", 0),
            "Review Bintang 1 ⭐":         review.get("star1", 0),
            "Review Negatif Baru":        review.get("neg_baru", 0),
            "Views Produk":               views,
            "Status Boost":               "Aktif" if iid in boost_set else "Tidak",
            "Ada Promo Aktif":            "Ya" if iid in promo_set else "Tidak",
            "Status Produk":              base.get("status", ""),
            "Revenue Produk":             revenue_produk,
            "CTR Listing":                ctr,
            "Conversion Rate":            cr,
        })

    push_to_lark(records)

    print("🔍 Check alerts...")
    check_alerts(date_str, item_ids, base_map, review_map, extra_map)

    print("\n✅ zeodda_product_performance.py — DONE")


if __name__ == "__main__":
    main()
