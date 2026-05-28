"""
scripts/zeodda_daily_overview.py
Daily Overview — pull data dari Shopee & push ke Lark Base.
Run via GitHub Actions setiap hari jam 03:00 WIB (20:00 UTC).

Revisi:
- Menggunakan wildcard import (from zeodda_helpers import *)
- Memperbaiki pemanggilan lark_init() yang tidak mengembalikan nilai
- Memperbaiki signature lark_add() agar hanya menerima 2 argumen (table_id, fields) sesuai spesifikasi zeodda_helpers.py
"""

import sys
import os
import traceback

# Pastikan folder scripts ada di path (jika run dari root repo)
sys.path.insert(0, os.path.dirname(__file__))

# Menggunakan wildcard import untuk menjamin kecocokan seluruh helper fungsi
from zeodda_helpers import *

PLATFORM = "Shopee"


# ─────────────────────────────────────────────
# HELPER: simpan alert ke Lark
# ─────────────────────────────────────────────
def push_alert(date_str, tipe, detail, nilai_saat_ini, nilai_normal, prioritas="Medium"):
    # Perbaikan: lark_add hanya butuh 2 argumen: table_id dan fields
    lark_add(TABLE_ALERT_LOG, {
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
    perf = shopee_get("/api/v2/seller_data/get_shop_performance", {}) # Perbaikan: endpoint sesuai spesifikasi di helpers
    d["skor_performa"]   = safe_int(perf.get("overall_rating"))       # Perbaikan: field sesuai spesifikasi get_shop_performance
    d["rating_toko"]     = perf.get("overall_rating")

    # ── 2. Penalty Points ──────────────────────────────────────
    penalty = shopee_get("/api/v2/seller_data/get_penalty_point_history", { # Perbaikan: endpoint sesuai spesifikasi di helpers
        "page_size": 100,
        "page_no": 1,
    })
