// Tracking Sync — Zeodda (Shopee + TikTok) — versi cloud (GitHub Actions)
// Port dari "Tracking Logistik Auto.html" (D:\Claude). Tanpa dependency npm — cukup Node.js 18+.
import { createHmac } from 'node:crypto';
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CFG = JSON.parse(readFileSync(join(__dirname, 'tracking-config.json'), 'utf8'));
// Batas Stuck per WILAYAH (file ini WAJIB ikut di-upload bersama tracking-sync.mjs; salinan identik di Maja: assets/js/modules/tracking_wilayah.js)
let TW; // fail-safe: file belum ter-upload / rusak -> aturan lama 7/14/40 (sync harian TIDAK boleh mati gara-gara ini)
try { TW = createRequire(import.meta.url)('./tracking-wilayah.js'); }
catch (e) { console.warn(`⚠ tracking-wilayah.js tidak terbaca (${e.message.split('\n')[0]}) -- batas Stuck pakai aturan lama 7/14/40`); TW = { provDariEvent: () => '', ambang: () => null, normProv: (p) => p }; }
const SPEV = new Map(); // order_sn Shopee -> event tracking [{t,d}] (diisi shopeeForwardLatest; dipakai utk menebak provinsi tujuan)

const SHOPEE_HOST = 'https://partner.shopeemobile.com';
const TT_HOST = 'https://open-api.tiktokglobalshop.com';
const TT_AUTH = 'https://auth.tiktok-shops.com';
const LARK = 'https://open.larksuite.com';
const VER = '202309';

// ═══ SECRET (dari env / GitHub Secrets) ═══
const env = process.env;
const LARK_APP_ID = env.LARK_APP_ID;
const LARK_APP_SECRET = env.LARK_APP_SECRET;
// 15 Sep 2026: SHOPEE_PARTNER_ID/KEY + SHOPEE_REFRESH_TOKEN_<shopId> (8 secret) DIHAPUS --
// refresh_token Shopee yg disimpan statis di sini SELALU basi (Shopee mengeluarkan
// refresh_token BARU tiap dipakai, worker Cloudflare sendiri sudah merefresh tiap 3,5 jam
// & menimpa salinan yg di sini tidak pernah ikut ter-update -- laporan user 15 Sep 2026:
// hampir semua order gagal serentak dgn "Token Shopee tidak tersedia"). Sekarang panggilan
// Shopee lewat WORKER_URL (action "gh_shopee_proxy") yg SELALU pakai token segar dari KV
// Worker sendiri -- lihat shopeeGet() di bawah. Token/signing Shopee tidak lagi ditangani
// di script ini sama sekali.
const WORKER_URL = env.WORKER_URL;
const GITHUB_SYNC_SECRET = env.GITHUB_SYNC_SECRET;
// Sebut PERSIS mana yg kosong -- pesan gabungan lama ("belum lengkap" tanpa rincian) bikin
// user harus nebak sendiri secret mana yg kelupaan diisi (laporan user 15 Sep 2026, langsung
// kejadian pas WORKER_URL/GITHUB_SYNC_SECRET baru ditambahkan).
{
  const kosong = [
    !LARK_APP_ID && 'LARK_APP_ID', !LARK_APP_SECRET && 'LARK_APP_SECRET',
    !WORKER_URL && 'WORKER_URL', !GITHUB_SYNC_SECRET && 'GITHUB_SYNC_SECRET',
  ].filter(Boolean);
  if (kosong.length) {
    console.error(`❌ Secret/env kosong: ${kosong.join(', ')} -- cek Settings > Secrets and variables > Actions di repo ini.`);
    process.exit(1);
  }
}

// nama toko Shopee (kolom "Toko") → shop id -- FALLBACK statis kalau fetch daftar toko live
// (gh_shopee_shop_ids, lihat main()) gagal. 15 Sep 2026: laporan user "SM Zeodda Surabaya"
// order-nya gagal terdeteksi ("Toko tidak terdeteksi di API manapun") PADAHAL nama tokonya
// jelas ADA di baris Lark -- akar masalah: daftar ini cuma 7 toko, 4 toko HILANG (Zeodda
// Surabaya, Vamo Bandung, Vamo Surabaya, Vamo Pekanbaru) drpd 11 toko yg sebenarnya terdaftar
// di Maja Apps (PERF_CRON_SHOPS/Kelola Toko). BUKAN masalah data Lark, jangan diubah di Lark --
// daftar ini yg kurang lengkap & gampang basi lagi kalau toko baru ditambah manual di sini.
// Sekarang dilengkapi jadi 11 (SAMA dgn PERF_CRON_SHOPS), dan di main() ditimpa lagi dgn nama
// LIVE dari Worker begitu fetch-nya berhasil -- daftar statis ini cuma jaring pengaman.
const SHOPEE_MAP = {
  'SM Zeodda': 867817945, 'SM Zeodda Tangerang': 963990340, 'SM Zeodda Pekanbaru': 899095041,
  'SM Zeodda Bandung': 967593785, 'SM Zeodda Surabaya': 981831132,
  'SM Vamo Indonesia': 981846983, 'SM Vamo Tangerang': 963980234, 'SM Vamo Bandung': 1145357332,
  'SM Vamo Surabaya': 1102913663, 'SM Vamo Pekanbaru': 981842162,
  'SM Zeo Baby Kids': 1101111522,
};
const RETURN_STATUS_LABEL = { REQUESTED: 'Retur diajukan', PROCESSING: 'Retur diproses', ACCEPTED: 'Retur diterima penjual', SELLER_DISPUTE: 'Retur disengketakan', JUDGING: 'Retur ditinjau Shopee', REFUND_PAID: 'Dana dikembalikan', CANCELLED: 'Retur dibatalkan', CLOSED: 'Retur ditutup' };

const logLines = [];
function log(type, msg) {
  const t = new Date().toISOString().slice(11, 19);
  const line = `[${t}] ${type.toUpperCase()}: ${msg}`;
  logLines.push(line);
  console.log(line);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
// "Internal error. Retry later" (TikTok 36009003) ikut diulang -- sekali muncul, seluruh retur toko itu terbaca 0 (kejadian 30 Sep 2026)
const isRateLimitMsg = s => /too many request|rate limit|frequent|too_many_request|retry later/i.test(String(s || ''));
async function fetchJsonRetry(url, fetchOpts, isRateLimited, label, tries = 4) {
  let delay = 1500;
  for (let i = 0; i < tries; i++) {
    let r;
    try { r = await fetch(url, fetchOpts).then(x => x.json()); }
    catch (e) { if (i === tries - 1) throw e; await sleep(delay); delay *= 2.5; continue; }
    if (isRateLimited(r)) {
      if (i === tries - 1) return r;
      log('warn', `${label}: rate limit, coba lagi dlm ${Math.round(delay / 1000)}d (${i + 1}/${tries})`);
      await sleep(delay); delay *= 2.5; continue;
    }
    return r;
  }
}

const normName = s => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
const normShop = s => normName(s).replace(/^ttm/, 'tt');
const NAME_ALIAS = {
  'smvamoidn': 'smvamoindonesia', 'smvamoshoes': 'smvamotangerang',
  'ttvamoidn': 'ttvamoindonesia', 'ttvamoshoes': 'ttvamotangerang',
  'tpzeodda': 'ttzeodda',
};
const canonKey = s => { const k = normShop(s); return NAME_ALIAS[k] || k; };
// let (bukan const): dibangun dulu dari SHOPEE_MAP statis (fallback), lalu ditimpa main() pakai
// nama-nama toko LIVE begitu fetch gh_shopee_shop_ids berhasil -- supaya toko baru yg ditambah
// lewat Kelola Toko langsung ikut cocok by nama juga (bukan cuma ikut lolos di brute-force).
function buildShopeeNorm(map) {
  const norm = {};
  for (const k in map) norm[canonKey(k)] = map[k];
  return norm;
}
let SHOPEE_NORM = buildShopeeNorm(SHOPEE_MAP);

async function runPool(items, limit, worker) {
  let i = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (i < items.length) { const idx = i++; await worker(items[idx], idx); }
  });
  await Promise.all(runners);
}
function hmacHex(key, msg) { return createHmac('sha256', key).update(msg).digest('hex'); }

// ═══ LARK ═══
let TAT = '';
async function larkAuth() {
  const r = await fetch(`${LARK}/open-apis/auth/v3/tenant_access_token/internal`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ app_id: LARK_APP_ID, app_secret: LARK_APP_SECRET }) }).then(x => x.json());
  if (!r.tenant_access_token) throw new Error(`Auth Lark gagal: ${r.msg || 'unknown'}`);
  TAT = r.tenant_access_token;
}
function larkFetch(method, path, body) {
  return fetch(`${LARK}${path}`, { method, headers: { Authorization: `Bearer ${TAT}`, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json());
}
function larkText(v) { if (!v) return ''; if (typeof v === 'string') return v.trim(); if (Array.isArray(v)) return v.map(x => x.text ?? x.value ?? x).join('').trim(); if (typeof v === 'object') return String(v.text ?? v.value ?? v.name ?? '').trim(); return String(v).trim(); }
function pickField(fields, names) { for (const n of names) { if (fields[n] != null && fields[n] !== '') return fields[n]; } return ''; }
function deepText(v) { if (v == null) return ''; if (typeof v === 'string') return v; if (typeof v === 'number') return String(v); if (Array.isArray(v)) return v.map(deepText).join(''); if (typeof v === 'object') return deepText(v.text ?? v.value ?? v.name ?? ''); return ''; }
const isOptId = s => /^(opt|rec|fld|tbl)[A-Za-z0-9]{6,}$/.test(s);
const COL_ORDER = ['No. Pesanan Online', 'No Pesanan Online', 'No. Pesanan', 'No Pesanan', 'No.Pesanan Online', 'No.Pesanan'];
const COL_TOKO = ['Nama Toko', 'Toko', 'Nama Toko Rumus'];

let OPT_MAP = {};
async function buildOptionMap(app) {
  const map = {};
  const tr = await larkFetch('GET', `/open-apis/bitable/v1/apps/${app}/tables?page_size=100`);
  if (tr.code !== 0) { log('warn', `List tables gagal: ${tr.msg || ''}`); return map; }
  for (const t of tr.data?.items || []) {
    const fr = await larkFetch('GET', `/open-apis/bitable/v1/apps/${app}/tables/${t.table_id}/fields?page_size=200`);
    if (fr.code !== 0) continue;
    for (const f of fr.data?.items || []) for (const o of (f.property?.options || [])) if (o.id && o.name) map[o.id] = o.name;
  }
  return map;
}
function getToko(fields) {
  for (const n of COL_TOKO) {
    let v = deepText(fields[n]).trim();
    if (v && isOptId(v) && OPT_MAP[v]) v = OPT_MAP[v];
    if (v && !isOptId(v)) return v;
  }
  return '';
}
function getOrderSn(fields) { return deepText(pickField(fields, COL_ORDER)).trim(); }
async function larkAllRecords(app, table, view) {
  let items = [], pt = '';
  do {
    const qs = `${view ? `view_id=${view}&` : ''}page_size=500${pt ? `&page_token=${encodeURIComponent(pt)}` : ''}`;
    const r = await larkFetch('GET', `/open-apis/bitable/v1/apps/${app}/tables/${table}/records?${qs}`);
    if (r.code !== 0) throw new Error(`Ambil records gagal: ${r.msg}`);
    items.push(...(r.data?.items || [])); pt = r.data?.page_token || '';
  } while (pt);
  return items;
}

// ═══ SHOPEE (lewat proxy Worker -- lihat catatan "SECRET" di atas utk alasannya) ═══
// Worker yg pegang & merawat access_token/refresh_token; script ini cuma kirim shop_id+path
// dan terima hasilnya. `extra` = query param GET (persis param yg dulu dikirim langsung ke
// Shopee). Rate-limit/retry TETAP di sini (fetchJsonRetry), Worker cuma menangani auth.
async function shopeeGet(path, shopId, extra = {}) {
  const body = { action: 'gh_shopee_proxy', secret: GITHUB_SYNC_SECRET, shop_id: shopId, method: 'GET', payload: extra, path };
  const r = await fetchJsonRetry(WORKER_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    (r) => isRateLimitMsg(r?.data?.error) || isRateLimitMsg(r?.data?.message) || isRateLimitMsg(r?.error), `SP ${path}`);
  if (r?.error) return { error: r.error }; // gagal di sisi Worker sendiri (mis. token toko itu belum pernah ada)
  return r.data || {};
}
async function shopeeForwardLatest(shopId, orderSn) {
  const td = await shopeeGet('/api/v2/logistics/get_tracking_info', shopId, { order_sn: orderSn });
  if (td.error && td.error !== '') return { err: td.error };
  const ev = td.response?.tracking_list || td.response?.history || td.response?.tracking_info || [];
  if (!ev.length) return { desc: '', ts: 0 };
  const gTs = e => e.ctime || e.time || e.created_time || e.timestamp || e.update_time || e.event_time || 0;
  const gD = e => e.description || e.message || e.status || e.status_description || e.detail || '';
  SPEV.set(orderSn, ev.map(e => ({ t: gTs(e), d: gD(e) })));
  const l = [...ev].sort((a, b) => gTs(b) - gTs(a))[0]; return { desc: gD(l), ts: gTs(l) };
}
async function shopeeReverse(shopId, returnSn) {
  const r = await shopeeGet('/api/v2/returns/get_reverse_tracking_info', shopId, { return_sn: returnSn });
  if (r.error && r.error !== '') return { err: r.error };
  const resp = r.response || {}; const ev = resp.tracking_info || resp.post_return_logistics_tracking_info || [];
  if (ev.length) { const l = [...ev].sort((a, b) => (b.update_time || 0) - (a.update_time || 0))[0]; return { desc: l.tracking_description || '', ts: l.update_time || 0 }; }
  return { desc: '', ts: resp.reverse_logistics_update_time || 0, logiStatus: resp.reverse_logistics_status || '' };
}
let rawReturnDebugPrinted = false; // cetak 1x per run -- verifikasi nama field ASLI dari Shopee, jangan tebak lagi
// JANGAN pakai create_time_from/to di get_return_list -- parameter itu RUSAK (dibuktikan 19 Sep 2026
// dgn 30+ variasi query): hasilnya bergeser ~13 hari dari window yg diminta, window <13 hari selalu
// balik kosong, >15 hari error_param, dan ada periode yg tidak pernah muncul sama sekali (1-11 Sep
// hilang total, 10 dari 11 toko balik 0 record). Retur yg JELAS ADA (terbukti via get_return_detail)
// tidak pernah terjaring. TANPA filter waktu, endpoint yg sama mengembalikan riwayat LENGKAP urut
// lama→baru; jadi: cari halaman terakhir (binary search), lalu mundur sampai lewat daysBack.
// Semua ini panggilan BACA lewat Worker -- nol tulis KV.
async function shopeeReturnPage(shopId, pageNo) {
  const r = await shopeeGet('/api/v2/returns/get_return_list', shopId, { page_no: pageNo, page_size: 100 });
  if (r.error && r.error !== '') return null;
  return r.response?.return || [];
}
async function shopeeReturnMap(shopId, daysBack) {
  const map = {}, dmap = {}; // dmap: retur yg DIBANDING (punya dispute_reason) -- bisa beda dgn retur terbaru order itu
  const cutoff = Math.floor(Date.now() / 1000) - daysBack * 86400;

  // 1) halaman terakhir: gandakan sampai kosong, lalu binary search
  let lo = 1, hi = 1;
  for (let i = 0; i < 16; i++) {
    const list = await shopeeReturnPage(shopId, hi);
    await sleep(120);
    if (!list || !list.length) break;
    lo = hi; hi *= 2;
  }
  while (lo + 1 < hi) {
    const mid = Math.floor((lo + hi) / 2);
    const list = await shopeeReturnPage(shopId, mid);
    await sleep(120);
    if (list && list.length) lo = mid; else hi = mid;
  }

  // 2) mundur dari halaman terakhir sampai isinya sudah lebih tua dari cutoff
  for (let pg = lo; pg >= 1; pg--) {
    const list = await shopeeReturnPage(shopId, pg);
    if (!list) break;
    if (!rawReturnDebugPrinted && list.length) { rawReturnDebugPrinted = true; log('info', `🔍 DEBUG return_list MENTAH (1 contoh, shop ${shopId}): ${JSON.stringify(list[0])}`); }
    for (const ret of list) {
      if (!ret.order_sn) continue;
      const pd = dmap[ret.order_sn];
      if ((ret.dispute_reason || []).length && (!pd || (pd.update_time || 0) < (ret.update_time || 0))) dmap[ret.order_sn] = { status: ret.status || '', update_time: ret.update_time || 0 };
      const prev = map[ret.order_sn];
      // 1 order bisa punya >1 pengajuan retur -- simpan yg paling baru
      if (prev && (prev.update_time || 0) >= (ret.update_time || 0)) continue;
      map[ret.order_sn] = { return_sn: ret.return_sn, status: ret.status || '', update_time: ret.update_time || 0, reason: ret.reason || '', text_reason: ret.text_reason || '' };
    }
    const times = list.map(x => x.create_time).filter(Boolean);
    if (times.length && Math.max(...times) < cutoff) break;
    await sleep(160);
  }
  for (const sn in dmap) if (map[sn]) map[sn].dispute = dmap[sn];
  return map;
}
// kode `reason` dari Shopee -- yg di bawah SUDAH DIVERIFIKASI ke data asli toko Zeodda (19 Sep
// 2026, lihat DEBUG return_list mentah) + terjemahan sesuai kemauan user persis. Kode yg belum
// pernah muncul jatuh ke fallback format apa adanya (lihat log "Kode reason retur Shopee
// ditemukan" tiap run utk kode baru yg belum ada di sini). `text_reason` (teks bebas dari buyer)
// selalu ditempel kalau ada.
const RETURN_REASON_LABEL = {
  NOT_RECEIPT: 'Produk tidak diterima',
  CHANGE_OF_MIND: 'Berubah Pikiran',
  CHANGE_MIND: 'Berubah Pikiran',
  FUNCTIONAL_DMG: 'Produk yang diterima tidak dapat berfungsi',
  WRONG_ITEM: 'Saya menerima produk yang salah',
  ITEM_MISSING: 'Barang yang diterima tidak lengkap',
  DIFFERENT_DESCRIPTION: 'Produk berbeda dari deskripsi',
  SLIGHT_SCRATCH_DENTS: 'Produk yang diterima tergores/penyok',
  SUSPICIOUS_PARCEL: 'Paket mencurigakan (isi tidak sesuai)',
  PRODUCT_UNSATISFACTORY: 'Barang tidak sesuai', MISSING_PARTS: 'Bagian barang kurang/hilang',
  PRODUCT_DAMAGED: 'Barang rusak', PHYSICAL_DMG: 'Rusak fisik',
  SPILLAGE: 'Barang tumpah/bocor', COUNTERFEIT: 'Barang palsu', EXPIRED: 'Barang kadaluarsa',
  INCOMPLETE: 'Barang tidak lengkap', OTHERS: 'Lainnya',
};
function formatReturnReason(code, textReason) {
  const label = RETURN_REASON_LABEL[code] || (code ? code.replace(/_/g, ' ').toLowerCase().replace(/^./, c => c.toUpperCase()) : '');
  if (textReason) return label ? `${label} - ${textReason}` : textReason;
  return label;
}
// ═══ BANDING (30 Sep 2026) ═══ -- isi kolom Status Banding / Status Aju / Tgl Ajuin / Tgl Close
// (sumber yg dikonfigur "banding": true, mis. HJB R.R by Admin). Keterangan MP TIDAK ditulis lagi.
// Penanda "pernah dibanding" yg BENAR (dulu salah: semua retur CANCELLED dianggap banding disetujui,
// padahal dari 788 banding 120 hari tak satu pun berakhir CANCELLED):
//  - Shopee: field dispute_reason terisi (ikut di get_return_list, 0 panggilan tambahan).
//    Status akhirnya DIVERIFIKASI user di Seller Center 30 Sep 2026: CLOSED = Disetujui, ACCEPTED = Ditolak
//    (dicocokkan jg ke isian manual staf: 21/21 CLOSED = Disetujui, ACCEPTED 8 Ditolak vs 2 Disetujui).
//  - TikTok: arbitration_status di returns/search. CLOSED dianggap Ditolak (keputusan user).
// API tidak memberi tanggal pengajuan banding: Tgl Ajuin = update_time saat sync pertama kali melihat
// banding masih On Proses (≤1 hari meleset krn sync harian). Tgl Close = update_time status final.
const SHOPEE_BANDING = { SELLER_DISPUTE: 'On Proses', JUDGING: 'On Proses', CLOSED: 'Disetujui', ACCEPTED: 'Ditolak' };
const TT_BANDING = { IN_PROGRESS: 'On Proses', SUPPORT_SELLER: 'Disetujui', SUPPORT_BUYER: 'Ditolak', CLOSED: 'Ditolak' };
const BANDING_FINAL = new Set(['Disetujui', 'Ditolak']);
const BANDING_BOLEH_TIMPA = new Set(['', 'On Proses', 'Belum Banding']); // isian manual lain (Dibiayakan, Tidak Banding, dst) tak disentuh
const seenBandingUnknown = new Set();
function bandingOf(shopRet, ttRet) {
  if (shopRet?.dispute) {
    const hasil = SHOPEE_BANDING[shopRet.dispute.status];
    if (!hasil) { seenBandingUnknown.add(`Shopee ${shopRet.dispute.status}`); return null; }
    return { hasil, ts: shopRet.dispute.update_time };
  }
  if (ttRet?.arb) {
    const hasil = TT_BANDING[ttRet.arb.status];
    if (!hasil) { seenBandingUnknown.add(`TikTok ${ttRet.arb.status}`); return null; }
    return { hasil, ts: ttRet.arb.ts };
  }
  return null;
}
function bandingFields(row, b) {
  const cur = row.banding;
  if (!b || !cur || !row.cols || !BANDING_BOLEH_TIMPA.has(cur.status)) return {};
  const f = {}, has = (c) => row.cols.has(c);
  if (has('Status Banding') && cur.status !== b.hasil) f['Status Banding'] = b.hasil;
  if (b.hasil === 'On Proses') {
    if (has('Status Aju') && cur.aju !== 'On Proses') f['Status Aju'] = 'On Proses';
    if (has('Tgl Ajuin') && !cur.tglAjuin && b.ts) f['Tgl Ajuin'] = noonWib(b.ts);
  } else {
    if (has('Status Aju') && cur.aju !== 'Close') f['Status Aju'] = 'Close';
    if (has('Tgl Close') && !cur.tglClose && b.ts) f['Tgl Close'] = noonWib(b.ts);
  }
  return f;
}

// ═══ TIKTOK ═══
function ttSign(path, query, bodyStr, appSecret) {
  const keys = Object.keys(query).filter(k => !['sign', 'access_token', 'x-tts-access-token'].includes(k)).sort();
  let s = ''; for (const k of keys) { if (typeof query[k] !== 'object') s += `${k}${query[k]}`; }
  s = path + s; if (bodyStr) s += bodyStr; s = appSecret + s + appSecret; return hmacHex(appSecret, s);
}
async function ttCall(ctx, opts) {
  const method = opts.method || 'GET'; const path = `/${opts.path}`.replace('//', '/');
  const query = Object.assign({ app_key: ctx.appKey, timestamp: Math.floor(Date.now() / 1000) }, opts.query || {});
  if (opts.shopCipher) query.shop_cipher = opts.shopCipher;
  const bodyStr = (method !== 'GET' && opts.body) ? JSON.stringify(opts.body) : '';
  query.sign = ttSign(path, query, bodyStr, ctx.appSecret);
  const qs = Object.entries(query).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
  const r = await fetchJsonRetry(`${TT_HOST}${path}?${qs}`, { method, headers: { 'content-type': 'application/json', 'x-tts-access-token': ctx.accessToken }, body: bodyStr || undefined }, r => isRateLimitMsg(r.message), `TT ${method} ${path}`);
  if (r.code !== 0) log('warn', `TT ${method} ${path} → ${r.code} ${r.message || ''}`);
  return r;
}
async function ttRefresh(appKey, appSecret, rt) {
  const u = `${TT_AUTH}/api/v2/token/refresh?app_key=${encodeURIComponent(appKey)}&app_secret=${encodeURIComponent(appSecret)}&refresh_token=${encodeURIComponent(rt)}&grant_type=refresh_token`;
  const r = await fetch(u).then(x => x.json());
  if (r.code !== 0 || !r.data?.access_token) throw new Error(`refresh TT gagal: ${r.code} ${r.message || ''}`);
  return { access_token: r.data.access_token, refresh_token: r.data.refresh_token || rt, expire: r.data.access_token_expire_in || 0 };
}
function ttTs(e) { return e.update_time_millis ? Math.floor(e.update_time_millis / 1000) : (e.update_time || e.ctime || e.time || 0); }
async function ttTracking(ctx, cipher, orderId) {
  const tr = await ttCall(ctx, { method: 'GET', path: `fulfillment/${VER}/orders/${encodeURIComponent(orderId)}/tracking`, shopCipher: cipher });
  if (tr.code !== 0) return { desc: '', ts: 0, err: tr.message };
  const ev = tr.data?.tracking || tr.data?.tracking_list || [];
  if (!ev.length) return { desc: '', ts: 0 };
  const l = [...ev].sort((a, b) => ttTs(b) - ttTs(a))[0];
  return { desc: l.description || l.tracking_description || '', ts: ttTs(l) };
}
async function ttOwnsOrder(ctx, cipher, orderId) {
  const r = await ttCall(ctx, { method: 'GET', path: `order/${VER}/orders`, query: { ids: String(orderId) }, shopCipher: cipher });
  return (r.data?.orders || []).some(o => String(o.id) === String(orderId));
}

// ── TikTok RETUR (return_refund API) — jalur ke-2 sama seperti Shopee, biar retur SETELAH "Diterima" ikut kedeteksi ──
const TT_RETURN_LABEL = {
  RETURN_OR_REFUND_REQUEST_PENDING: 'Retur diajukan',
  REFUND_OR_RETURN_REQUEST_REJECT: 'Retur ditolak seller',
  AWAITING_BUYER_SHIP: 'Menunggu pembeli kirim retur',
  BUYER_SHIPPED_ITEM: 'Pembeli sudah kirim retur',
  REJECT_RECEIVE_PACKAGE: 'Seller tolak terima paket retur',
  RETURN_OR_REFUND_REQUEST_SUCCESS: 'Dana dikembalikan',
  RETURN_OR_REFUND_REQUEST_CANCEL: 'Retur dibatalkan',
  RETURN_OR_REFUND_REQUEST_COMPLETE: 'Retur/refund selesai',
  AWAITING_BUYER_RESPONSE: 'Menunggu respon pembeli',
  REPLACEMENT_REQUEST_PENDING: 'Penggantian diajukan',
  REPLACEMENT_REQUEST_REJECT: 'Penggantian ditolak',
  REPLACEMENT_REQUEST_REFUND_SUCCESS: 'Penggantian jadi refund',
  REPLACEMENT_REQUEST_CANCEL: 'Penggantian dibatalkan',
  REPLACEMENT_REQUEST_COMPLETE: 'Penggantian selesai',
};
const TT_RETURN_FINAL = new Set(['RETURN_OR_REFUND_REQUEST_SUCCESS', 'RETURN_OR_REFUND_REQUEST_COMPLETE']);
let rawTtReturnDebugPrinted = false; // env TT_DUMP=1 -> cetak 1 record retur TikTok mentah (lihat nama field asli)
// Alasan retur TikTok: dipatok ke `return_reason_text` (teks Inggris dari TikTok) -- bukan ke
// `return_reason` yg berupa kunci i18n panjang & beda-beda per skenario. Teks yg belum ada di sini
// ditulis apa adanya & dilaporkan di akhir run ("Alasan retur TikTok ditemukan") utk ditambahkan.
// Wording disamakan dgn padanan Shopee-nya biar 1 kolom Lark tidak campur 2 gaya bahasa.
const TT_REASON_LABEL = {
  'change of mind': 'Berubah Pikiran',                                           // = CHANGE_MIND
  'product doesn\'t match description': 'Produk berbeda dari deskripsi',         // = DIFFERENT_DESCRIPTION
  'wrong product sent': 'Saya menerima produk yang salah',                       // = WRONG_ITEM
  'received parcel, but some items were missing': 'Barang yang diterima tidak lengkap', // = ITEM_MISSING
  'package or product is damaged': 'Produk yang diterima rusak',
  'congrats on meeting your refundable sample criteria!': 'Sampel gratis (refundable sample), bukan komplain pembeli',
};
function formatTtReason(reasonText) {
  const t = String(reasonText || '').trim();
  if (!t) return '';
  return TT_REASON_LABEL[t.toLowerCase()] || t;
}
function findReturnList(data) {
  if (!data) return [];
  for (const k of ['return_order_list', 'returns', 'return_list', 'order_return_list']) if (Array.isArray(data[k])) return data[k];
  for (const k in data) if (Array.isArray(data[k]) && data[k][0] && data[k][0].return_status) return data[k];
  return [];
}
async function ttReturnMap(ctx, cipher, daysBack, shopLabel) {
  const map = {}, amap = {}; const now = Math.floor(Date.now() / 1000); const from0 = now - daysBack * 86400; // amap: retur yg masuk arbitrase (banding)
  let pageToken = '', more = true, guard = 0, dbgDone = false;
  while (more && guard < 40) {
    guard++;
    const query = { page_size: 50, sort_field: 'update_time', sort_order: 'DESC' }; if (pageToken) query.page_token = pageToken;
    const r = await ttCall(ctx, { method: 'POST', path: `return_refund/${VER}/returns/search`, shopCipher: cipher, query, body: { create_time_ge: from0 } });
    if (r.code !== 0) { log('warn', `Retur TikTok "${shopLabel}": API gagal (${r.code} ${r.message || ''}) — cek scope "seller.return_refund.basic"`); break; }
    const list = findReturnList(r.data);
    if (!dbgDone) { dbgDone = true; log('info', `DEBUG retur "${shopLabel}": keys respons data = [${Object.keys(r.data || {}).join(', ')}], array retur ditemukan = ${list.length} item`); }
    if (env.TT_DUMP && !rawTtReturnDebugPrinted && list.length) { rawTtReturnDebugPrinted = true; log('info', `🔍 DEBUG retur TikTok MENTAH (1 contoh, "${shopLabel}"): ${JSON.stringify(list[0])}`); }
    for (const item of list) {
      const oids = item.order_ids || (item.order_id ? [item.order_id] : []);
      const ts = item.update_time || item.create_time || 0;
      for (const oid of oids) {
        if (item.arbitration_status && (!amap[oid] || ts > amap[oid].ts)) amap[oid] = { status: item.arbitration_status, ts };
        const prev = map[oid];
        // return_reason = kunci i18n (mis. "ecom_..._reason_damaged_toko"), return_reason_text =
        // teks Inggris terbaca ("Package or product is damaged"). Terjemahan dipatok ke teksnya.
        if (!prev || ts > prev.ts) map[oid] = { status: item.return_status, ts, trackingNumber: item.return_tracking_number || '', reasonText: item.return_reason_text || '', reasonKey: item.return_reason || '' };
      }
    }
    pageToken = r.data?.next_page_token || r.data?.page_token || '';
    more = !!pageToken && list.length > 0;
  }
  for (const oid in amap) if (map[oid]) map[oid].arb = amap[oid];
  log('info', `Retur TikTok "${shopLabel}": ${Object.keys(map).length} order ada data retur, ${Object.keys(amap).length} masuk banding/arbitrase (${daysBack} hari terakhir)`);
  return map;
}

// ═══ KOMPENSASI PESANAN HILANG (30 Sep 2026) ═══
// Pesanan yg dinyatakan hilang: cek apakah marketplace SUDAH mengirim kompensasinya, lalu isi kolom
// Status Pesanan="Dana Cair", Tanggal Selesai=tanggal dana cair, Progress="Done", Jumlah Dana Cair=nominal.
// Sumber (terverifikasi ke data asli 30 Sep 2026, 63 dari 64 pesanan hilang cocok):
//  - Shopee : wallet transaksi bertipe FULFILMENT_COMPENSATE_ADD ("Kompensasi atas pesanan hilang"),
//             ada order_sn + create_time + amount. Jendela query maks ~10 hari -> disisir per 9 hari.
//  - TikTok : statement transaksi bertipe LOGISTICS_REIMBURSEMENT (kunci: adjustment_order_id),
//             tanggal cair = payment_time statement. Statement tanpa adjustment dilewati (hemat panggilan).
// Semua panggilan BACA. Penulisan ke Lark dipisah dari update Status Terakhir supaya kegagalan di sini
// (mis. kolom/opsi belum ada) tidak menggagalkan sync utama.
const COMP_STATUS_PESANAN = 'Dana Cair', COMP_PROGRESS = 'Done';
const COMP_STATUS_KANDIDAT = ['Pengiriman Gagal', 'Proses Pencairan Dana']; // status manual yg biasanya menunggu kompensasi
const isLostCand = (statusTerakhir, statusPesanan) => /^Hilang/.test(statusTerakhir || '') || COMP_STATUS_KANDIDAT.includes(statusPesanan || '');
async function shopeeCompMap(shopId, fromTs) {
  const map = {}; const now = Math.floor(Date.now() / 1000); const seen = new Set(); // transaksi tepat di batas 2 jendela jangan terhitung dobel
  for (let w = 0; now - w * 9 * 86400 > fromTs; w++) {
    const to = now - w * 9 * 86400, from = Math.max(fromTs, to - 9 * 86400);
    for (let page = 0; page < 40; page++) {
      const r = await shopeeGet('/api/v2/payment/get_wallet_transaction_list', shopId, { page_no: page, page_size: 100, create_time_from: from, create_time_to: to, transaction_type: 'FULFILMENT_COMPENSATE_ADD' });
      if (r.error && r.error !== '') { log('warn', `Kompensasi Shopee ${shopId}: ${r.error} ${r.message || ''}`); break; }
      const l = r.response?.transaction_list || [];
      for (const x of l) {
        if (x.status && x.status !== 'COMPLETED') continue;
        const tid = String(x.transaction_id || `${x.order_sn}|${x.create_time}|${x.amount}`); if (seen.has(tid)) continue; seen.add(tid);
        const e = map[x.order_sn] || (map[x.order_sn] = { jumlah: 0, ts: 0 });
        e.jumlah += Number(x.amount) || 0; e.ts = Math.max(e.ts, x.create_time || 0);
      }
      if (!r.response?.more) break;
    }
  }
  return map;
}
async function ttCompMap(ctx, cipher, fromTs, shopLabel) {
  const map = {}; const now = Math.floor(Date.now() / 1000);
  const stm = []; let pt = '';
  for (let g = 0; g < 20; g++) {
    const q = { page_size: 100, sort_field: 'statement_time', statement_time_ge: fromTs, statement_time_lt: now }; if (pt) q.page_token = pt;
    const r = await ttCall(ctx, { method: 'GET', path: `finance/${VER}/statements`, shopCipher: cipher, query: q });
    if (r.code !== 0) { log('warn', `Kompensasi TikTok "${shopLabel}": statement gagal (${r.code} ${r.message || ''})`); return map; }
    stm.push(...(r.data?.statements || [])); pt = r.data?.next_page_token || ''; if (!pt) break;
  }
  const cand = stm.filter(s => Number(s.adjustment_amount) !== 0); // reimbursement selalu masuk adjustment_amount statement
  await runPool(cand, 4, async (st) => {
    let tok = '';
    for (let g = 0; g < 80; g++) {
      const q = { page_size: 100, sort_field: 'order_create_time' }; if (tok) q.page_token = tok;
      const r = await ttCall(ctx, { method: 'GET', path: `finance/202501/statements/${st.id}/statement_transactions`, shopCipher: cipher, query: q });
      if (r.code !== 0) { log('warn', `Kompensasi TikTok "${shopLabel}" statement ${st.id}: ${r.code} ${r.message || ''}`); break; }
      for (const x of r.data?.transactions || []) {
        if (x.type !== 'LOGISTICS_REIMBURSEMENT') continue;
        const ts = Number(st.payment_time) || 0; if (!ts) continue; // belum dibayarkan -> belum "cair"
        const id = String(x.adjustment_order_id || x.order_id);
        const e = map[id] || (map[id] = { jumlah: 0, ts: 0 });
        e.jumlah += Number(x.adjustment_amount || x.settlement_amount) || 0; e.ts = Math.max(e.ts, ts);
      }
      tok = r.data?.next_page_token || ''; if (!tok) break;
    }
  });
  log('info', `Kompensasi TikTok "${shopLabel}": ${stm.length} statement (${cand.length} berisi adjustment), ${Object.keys(map).length} order`);
  return map;
}
// 12:00 WIB pada tanggal cair -> tampil tanggal yg sama di zona waktu apa pun (kolom Tanggal Selesai hanya tanggal)
function noonWib(ts) { const d = new Date((ts + 7 * 3600) * 1000); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 5, 0, 0); }
// Isian kolom utk 1 baris. Baris yg SUDAH "Dana Cair" hanya ditambal bagian yg kosong (jangan timpa isian staf).
const kompLengkap = (row) => row.stPesanan === COMP_STATUS_PESANAN && row.progress === COMP_PROGRESS && !!row.tglSelesai
  && (!row.cols.has('Jumlah Dana Cair') || !(row.jumlahCair == null || row.jumlahCair === ''));
function compFields(row, hit) {
  const f = {}; const has = (c) => row.cols.has(c); // row.cols selalu ada di sini (baris tanpa daftar kolom tidak jadi kandidat)
  const sudah = row.stPesanan === COMP_STATUS_PESANAN;
  if (has('Status Pesanan') && !sudah) f['Status Pesanan'] = COMP_STATUS_PESANAN;
  if (has('Tanggal Selesai') && (!sudah || !row.tglSelesai)) f['Tanggal Selesai'] = noonWib(hit.ts);
  if (has('Progress') && row.progress !== COMP_PROGRESS) f['Progress'] = COMP_PROGRESS;
  if (has('Jumlah Dana Cair') && (!sudah || row.jumlahCair == null || row.jumlahCair === '')) f['Jumlah Dana Cair'] = hit.jumlah;
  return f;
}

// ═══ DANA CAIR / DITARIK (15 Okt 2026) -- salinan aturan tool Maja "Cek Banding & Dana Cair" (cek_dana_cair.js) ═══
// Utk sumber "banding": true (R.R by Admin). Tak ada banding di marketplace (itu sudah diurus bagian BANDING) ->
//  - dana pesanan/kompensasi cair            -> Status Banding "Tidak Banding", Ket Adm "Dana Cair", Penyelesaian "Dana … sudah cair …"
//  - sempat cair lalu DITARIK utk refund     -> Status Barang Sesuai: tak diisi; Tidak Sesuai: ≤30 hari "Belum Banding — perlu banding",
//    (total bersih <= 0)                        >30 hari "Tidak Banding — lewat masa banding"; Status Barang kosong: tunggu ops.
// Isian staf tidak ditimpa. HARIAN & INKREMENTAL: baris final dilewati sebelum panggil API (lihat danaKandidat).
// UBAH ATURAN DI SINI = UBAH JUGA cek_dana_cair.js (dan sebaliknya).
const DANA_MASA_BANDING_HARI = 30;   // sesudah ditarik
const DANA_CAIR_CEK_ULANG_HARI = 60; // isian "Dana pesanan sudah cair" dicek ulang (bisa ditarik) sampai 60 hari sesudah cair
const DANA_PESANAN_MAKS_HARI = 90;   // pesanan dibuat > 90 hari lalu = final. JANGAN > returnDays (90): data banding (cache retur) cuma selebar itu
const DANA_KETADM_BOLEH = new Set(['', 'Komplainan']);
const danaTgl = (ts) => { const d = new Date((ts + 7 * 3600) * 1000); return `${String(d.getUTCDate()).padStart(2, '0')}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${d.getUTCFullYear()}`; };
const danaRp = (n) => 'Rp ' + Number(n || 0).toLocaleString('id-ID');
const danaIsianTool = (r) => r.sb === 'Tidak Banding' && r.ketAdm === 'Dana Cair' && /^Dana pesanan sudah cair/.test(r.peny || '');
// Masih mungkin diisi/dikoreksi? (sama dgn filter tool + batas umur isian Dana Cair & yg sudah "lewat masa banding")
function danaKandidat(r, nowS) {
  if (r.sb === 'Tidak Banding' && /lewat masa banding$/.test(r.peny || '')) return false;
  if (danaIsianTool(r)) {
    const m = /(\d{2})-(\d{2})-(\d{4})/.exec(r.peny);
    return !m || (nowS * 1000 - Date.UTC(+m[3], +m[2] - 1, +m[1])) / 86400000 <= DANA_CAIR_CEK_ULANG_HARI;
  }
  return BANDING_BOLEH_TIMPA.has(r.sb) || DANA_KETADM_BOLEH.has(r.ketAdm) || !r.peny;
}
// d = { ditarik, cair } hasil API (tanpa banding). Kembalikan { kat, f } -- persis cabang di cek_dana_cair.js.
function danaRencana(r, d, nowS) {
  const f = {}, has = (c) => r.cols.has(c);
  if (d.ditarik && d.cair?.jenis !== 'kompensasi') {
    const x = d.ditarik, teks = `${x.cair ? `Dana sempat cair ${danaTgl(x.cair.pay || x.cair.ts)} (${danaRp(x.cair.amount)}), lalu ` : 'Dana '}ditarik kembali ${danaTgl(x.ts)} (-${danaRp(x.amount)}) utk refund pembeli`;
    const lama = danaIsianTool(r), perluTeks = / — perlu banding$/.test(r.peny || ''); // teks "perlu banding" buatan tool boleh diganti
    const lewat = (nowS - x.ts) / 86400 > DANA_MASA_BANDING_HARI;
    if (r.barang === 'Sesuai') return { kat: 'ditarik — barang sesuai', f };
    if (!lama && !['', 'Belum Banding'].includes(r.sb)) return { kat: 'ditarik — sudah ditangani staf', f };
    if (!r.barang && !lama && !(lewat && perluTeks)) return { kat: 'ditarik — Status Barang belum diisi ops', f };
    // isian Dana Cair lama + barang kosong: > 30 hari cuma luruskan teks; <= 30 hari -> PERLU BANDING (Tidak Banding/Dana Cair dicabut, user 15 Okt)
    if (!r.barang && lama && lewat) {
      if (has('Ket Adm')) f['Ket Adm'] = 'Komplainan';
      if (has('Penyelesaian Komplaian')) f['Penyelesaian Komplaian'] = teks;
      return { kat: 'ditarik — koreksi isian Dana Cair', f };
    }
    if (lewat) {
      if (has('Status Banding') && ['', 'Belum Banding'].includes(r.sb)) f['Status Banding'] = 'Tidak Banding';
      if (has('Ket Adm') && lama) f['Ket Adm'] = 'Komplainan';
      if (has('Penyelesaian Komplaian') && (lama || !r.peny || perluTeks)) f['Penyelesaian Komplaian'] = teks + ' — lewat masa banding';
      return { kat: 'ditarik — lewat masa banding', f };
    }
    if (has('Status Banding') && (lama || r.sb === '')) f['Status Banding'] = 'Belum Banding';
    if (has('Ket Adm') && lama) f['Ket Adm'] = 'Komplainan';
    if (has('Penyelesaian Komplaian') && (lama || !r.peny)) f['Penyelesaian Komplaian'] = teks + ' — perlu banding';
    return { kat: 'ditarik — PERLU BANDING', f };
  }
  if (d.cair) {
    const kat = d.cair.jenis === 'kompensasi' ? 'dana kompensasi cair' : 'dana pesanan cair';
    if (danaIsianTool(r)) return { kat, f }; // sudah benar
    if (has('Status Banding') && ['', 'Belum Banding'].includes(r.sb)) f['Status Banding'] = 'Tidak Banding';
    if (has('Ket Adm') && DANA_KETADM_BOLEH.has(r.ketAdm)) f['Ket Adm'] = 'Dana Cair';
    if (has('Penyelesaian Komplaian') && !r.peny) f['Penyelesaian Komplaian'] = d.cair.jenis === 'kompensasi'
      ? `Dana kompensasi (${d.cair.alasan}) sudah cair di tanggal ${danaTgl(d.cair.ts)} (${danaRp(d.cair.amount)})`
      : `Dana pesanan sudah cair di tanggal ${danaTgl(d.cair.ts)} (${danaRp(d.cair.amount)})`;
    return { kat, f };
  }
  return { kat: 'belum cair', f };
}
// Shopee: wallet ESCROW_VERIFIED_ADD / MINUS / FULFILMENT_COMPENSATE_ADD di jendela 9 hari sekitar update_time pesanan.
async function danaShopee(sid, sns, nowS) {
  const od = {}, data = {};
  for (let i = 0; i < sns.length; i += 50) {
    const r = await shopeeGet('/api/v2/order/get_order_detail', sid, { order_sn_list: sns.slice(i, i + 50).join(',') });
    for (const o of r.response?.order_list || []) if (nowS - (o.create_time || nowS) <= DANA_PESANAN_MAKS_HARI * 86400) od[o.order_sn] = o;
  }
  const want = new Set(Object.keys(od)), wins = new Set();
  for (const o of Object.values(od)) { const w = Math.floor(((o.update_time || nowS) - 3 * 86400) / (9 * 86400)); wins.add(w); wins.add(w + 1); wins.add(w + 2); }
  const wallet = {};
  for (const w of [...wins].sort((a, b) => a - b)) {
    const from = w * 9 * 86400, to = Math.min(nowS, from + 9 * 86400); if (from > nowS) continue;
    for (const type of ['ESCROW_VERIFIED_ADD', 'FULFILMENT_COMPENSATE_ADD', 'ESCROW_VERIFIED_MINUS']) for (let page = 0; page < 150; page++) {
      const r = await shopeeGet('/api/v2/payment/get_wallet_transaction_list', sid, { page_no: page, page_size: 100, create_time_from: from, create_time_to: to, transaction_type: type });
      if (r.error && r.error !== '') { log('warn', `Dana cair Shopee ${sid}: ${r.error} ${r.message || ''}`); break; }
      for (const x of r.response?.transaction_list || []) if (want.has(x.order_sn) && (x.status || 'COMPLETED') === 'COMPLETED' && Number(x.amount)) (wallet[x.order_sn] || (wallet[x.order_sn] = [])).push({ type: x.transaction_type, amount: Math.abs(Number(x.amount)), ts: x.create_time });
      if (!r.response?.more) break;
    }
  }
  for (const sn of want) {
    const w = wallet[sn] || [], urut = (t) => w.filter(x => x.type === t).sort((a, b) => a.ts - b.ts);
    const komp = urut('FULFILMENT_COMPENSATE_ADD')[0], add = urut('ESCROW_VERIFIED_ADD'), esc = add[0], minus = urut('ESCROW_VERIFIED_MINUS');
    const tarik = minus.reduce((a, x) => a + x.amount, 0), masuk = add.reduce((a, x) => a + x.amount, 0);
    data[sn] = {
      ditarik: esc && minus.length && tarik >= masuk ? { ts: minus[minus.length - 1].ts, amount: tarik, cair: esc } : null,
      cair: komp ? { jenis: 'kompensasi', alasan: 'pesanan hilang', ts: komp.ts, amount: komp.amount } : esc ? { jenis: 'pesanan', ts: esc.ts, amount: esc.amount } : null,
    };
  }
  return data;
}
// TikTok: keuangan per pesanan (SEMUA baris; minus = ditarik), tanggal cair = payment_time statement, kompensasi = LOGISTICS_REIMBURSEMENT.
async function danaTiktok(e, ids, nowS, label) {
  const od = {}, tx = {}, data = {};
  for (let i = 0; i < ids.length; i += 50) {
    const r = await ttCall(e.ctx, { method: 'GET', path: `order/${VER}/orders`, query: { ids: ids.slice(i, i + 50).join(',') }, shopCipher: e.cipher });
    for (const o of r.data?.orders || []) if (nowS - (o.create_time || nowS) <= DANA_PESANAN_MAKS_HARI * 86400) od[o.id] = o;
  }
  const ada = Object.keys(od); if (!ada.length) return data;
  await runPool(ada, 4, async (id) => {
    const r = await ttCall(e.ctx, { method: 'GET', path: `finance/202309/orders/${id}/statement_transactions`, shopCipher: e.cipher });
    tx[id] = (r.data?.statement_transactions || []).filter(x => Number(x.settlement_amount)).map(x => ({ st: x.statement_id, amount: Number(x.settlement_amount), stTime: x.statement_time }));
  });
  const tertua = Math.min(...Object.values(od).map(o => o.create_time || nowS)), stm = {}; let pt = '';
  for (let g = 0; g < 30; g++) {
    const q = { page_size: 100, sort_field: 'statement_time', statement_time_ge: tertua - 86400, statement_time_lt: nowS }; if (pt) q.page_token = pt;
    const r = await ttCall(e.ctx, { method: 'GET', path: `finance/${VER}/statements`, shopCipher: e.cipher, query: q });
    for (const x of r.data?.statements || []) stm[x.id] = Number(x.payment_time) || 0;
    pt = r.data?.next_page_token || ''; if (!pt) break;
  }
  const perluKomp = ada.filter(id => /hilang|rusak|gagal|lost|damag/i.test(od[id]?.cancel_reason || ''));
  const reimb = perluKomp.length ? await ttCompMap(e.ctx, e.cipher, Math.min(...perluKomp.map(id => od[id]?.update_time || nowS)) - 3 * 86400, label) : {};
  for (const id of ada) {
    const semua = (tx[id] || []).map(x => ({ ...x, pay: stm[x.st] || 0 }));
    const rb = reimb[id], st = semua.filter(x => x.pay && x.amount > 0).sort((a, b) => a.pay - b.pay)[0];
    const neg = semua.filter(x => x.amount < 0).sort((a, b) => (a.pay || a.stTime) - (b.pay || b.stTime));
    const bersih = semua.reduce((a, x) => a + x.amount, 0), akhir = neg[neg.length - 1];
    data[id] = {
      ditarik: st && neg.length && bersih <= 0 ? { ts: akhir.pay || akhir.stTime, amount: -neg.reduce((a, x) => a + x.amount, 0), cair: st } : null,
      cair: rb ? { jenis: 'kompensasi', alasan: String(od[id]?.cancel_reason || 'kompensasi logistik').toLowerCase(), ts: rb.ts, amount: rb.jumlah } : st ? { jenis: 'pesanan', ts: st.pay, amount: st.amount } : null,
    };
  }
  return data;
}
// Tulis isian ke Lark per tabel (batch 100, gagal -> satu-satu supaya baris bermasalah kelihatan). Kembalikan jumlah tertulis.
async function tulisLarkTerpisah(list, label) {
  let n = 0; const byTbl = {};
  for (const u of list) { const k = u.app + '|' + u.table; (byTbl[k] || (byTbl[k] = [])).push(u); }
  for (const k in byTbl) {
    const [app, table] = k.split('|'); const rows = byTbl[k];
    for (let i = 0; i < rows.length; i += 100) {
      const chunk = rows.slice(i, i + 100);
      const res = await larkFetch('POST', `/open-apis/bitable/v1/apps/${app}/tables/${table}/records/batch_update`, { records: chunk.map(u => ({ record_id: u.record_id, fields: u.fields })) });
      if (res.code === 0) { n += chunk.length; log('ok', `${label} ${table}: ${chunk.length} record diisi ✓`); continue; }
      log('warn', `${label} batch ${table} gagal (${res.msg}) — coba satu-satu`);
      for (const u of chunk) {
        const r1 = await larkFetch('PUT', `/open-apis/bitable/v1/apps/${app}/tables/${table}/records/${u.record_id}`, { fields: u.fields });
        if (r1.code === 0) n++; else log('err', `${label} ${u.orderSn}: ${r1.msg} (fields: ${Object.keys(u.fields).join(', ')})`);
      }
    }
  }
  return n;
}

// ═══ STATUS ═══
function mapStatus(desc) {
  if (!desc) return desc;
  const isRet = /↩/.test(desc);
  if (/has been returned to the seller/i.test(desc)) {
    const m = desc.match(/returned to the seller in (.+?)\.?\s*$/i);
    const reg = m ? m[1].trim() : '';
    return reg ? `Kembali ke Seller ${reg}` : 'Kembali ke Seller';
  }
  if (/dikembalikan ke agen\s*\/\s*penjual/i.test(desc)) return 'Kembali ke Seller';
  if (isRet && /tiba di alamat tujuan/i.test(desc) && /diterima/i.test(desc)) return 'Kembali ke Seller';
  if (!isRet) {
    if (/has been delivered/i.test(desc)) return 'Sudah Diterima Pembeli';
    if (/tiba di alamat tujuan/i.test(desc)) return 'Sudah Diterima Pembeli';
  }
  if (/was lost/i.test(desc) || /dinyatakan hilang/i.test(desc)) return `Hilang - ${desc}`;
  return desc;
}
// amb = {s1,s2,s3} batas wilayah (TW.ambang) atau null -> pakai stuckDays/2/3. LABEL tetap "Stuck <stuckDays>+" dst (rumus Lark user), cuma pemicunya yg beda.
function formatStatus(desc, ts, stuckDays, stuckDays2, stuckDays3, lostDays2, returDays2, amb) {
  if (!desc) return desc;
  const hadReturn = /↩/.test(desc);
  let mapped = mapStatus(desc).replace(/↩\s*/g, '').trim();
  const isLost = /^Hilang/.test(mapped);
  const isKembaliSeller = /^Kembali ke Seller/.test(mapped);
  const isFinal = mapped === 'Sudah Diterima Pembeli' || isKembaliSeller || isLost;
  const isReturn = !isLost && (hadReturn || isKembaliSeller);
  if (isReturn) mapped = 'Retur - ' + mapped;
  // eskalasi: retur yang SUDAH sampai/final di seller tapi diam ≥N hari (belum diproses lanjut)
  if (isKembaliSeller && ts && returDays2) {
    const idleDays = (Date.now() - ts * 1000) / 86400000;
    if (idleDays >= returDays2) mapped = mapped.replace(/^Retur/, `Retur ${returDays2}+`);
  }
  if (isLost && ts && lostDays2) {
    const idleDays = (Date.now() - ts * 1000) / 86400000;
    if (idleDays >= lostDays2) mapped = mapped.replace(/^Hilang/, `Hilang ${lostDays2}+`);
  }
  if (ts && !isFinal) {
    const idleDays = (Date.now() - ts * 1000) / 86400000;
    const a1 = amb ? amb.s1 : stuckDays, a2 = amb ? amb.s2 : stuckDays2, a3 = amb ? amb.s3 : stuckDays3;
    if (stuckDays3 && idleDays >= a3) mapped = `Stuck ${stuckDays3}+ - ` + mapped;
    else if (stuckDays2 && idleDays >= a2) mapped = `Stuck ${stuckDays2}+ - ` + mapped;
    else if (idleDays >= a1) mapped = `Stuck ${stuckDays}+ - ` + mapped;
  }
  return mapped;
}
function categorize(finalDesc) {
  if (!finalDesc) return 'Lainnya/Proses';
  if (finalDesc === 'Sudah Diterima Pembeli') return 'Diterima Pembeli';
  const mRetur = finalDesc.match(/^Retur (\d+)\+/);
  if (mRetur) return `Retur ${mRetur[1]}+`;
  if (/Kembali ke Seller/.test(finalDesc)) return 'Kembali ke Seller';
  const mLost = finalDesc.match(/^Hilang (\d+)\+/);
  if (mLost) return `Hilang ${mLost[1]}+`;
  if (/^Hilang/.test(finalDesc)) return 'Hilang';
  const m = finalDesc.match(/^Stuck (\d+)\+/);
  if (m) return `Stuck ${m[1]}+`;
  return 'Lainnya/Proses';
}
function isFinalCategory(cat) { return cat === 'Diterima Pembeli' || cat === 'Kembali ke Seller' || cat === 'Hilang' || /^Hilang \d+\+$/.test(cat) || /^Retur \d+\+$/.test(cat); }

// ═══ MAIN ═══
const failedRows = [];
function addFail(t, alasan) { failedRows.push({ orderSn: t.orderSn || '?', srcName: t.srcName || t.table || '', alasan }); }
function failGroup(t, alasan) { (t._dupGroup || [t]).forEach(row => addFail(row, alasan)); }

async function main() {
  const daysBack = Math.max(15, CFG.returnDays || 90);
  log('info', '⏳ Auth Lark...'); await larkAuth();

  // Baca tabel "Tabel Token Shopee/TikTok" SEKALI -- dipakai utk DUA hal: token TikTok (ttByName,
  // spt sebelumnya) DAN daftar toko Shopee (shopeeFromLark, baru 15 Sep 2026). Permintaan user
  // langsung nunjuk tabel ini ("untuk pencocokan toko kan bisa disini") -- tabel ini SUDAH
  // dibaca script & SUDAH jadi tempat user menambah toko sehari-hari (kolom Shop ID + Nama Toko
  // Rumus), jadi tidak perlu round-trip terpisah ke Worker lagi utk hal yg sama.
  const ttByName = {};
  const shopeeFromLark = {}; // nama (persis "Nama Toko Rumus") -> shop id, dari SEMUA baris
  if (CFG.ttTokApp && CFG.ttTokTable) {
    const rows = await larkAllRecords(CFG.ttTokApp, CFG.ttTokTable, '');
    for (const r of rows) {
      const f = r.fields;
      const nm = larkText(f[CFG.ttNameCol]);
      const appKey = larkText(f['App Key']), appSecret = larkText(f['App Secret']), rt = larkText(f['Refresh Token']), cipher = larkText(f['Shop Cipher']), shopId = larkText(f['Shop ID']);
      // Baris Shopee TIDAK PUNYA App Key/Secret/Refresh Token (itu kolom khusus TikTok) --
      // makanya dulu baris begini dilewati BEGITU SAJA (`continue` di bawah), Shop ID-nya tidak
      // pernah diambil sama sekali. Diambil di SINI, SEBELUM continue, spt tokonya SM Zeodda
      // Surabaya di screenshot user (Shop ID + Nama Toko Rumus terisi, App Key dkk kosong).
      // Syarat "!appKey && !appSecret" sengaja dipasang -- tanpa itu, baris TikTok yg App
      // Key-nya kebetulan juga py Shop ID numerik akan ikut kepakai sbg id toko SHOPEE.
      if (nm && /^\d+$/.test(shopId) && !appKey && !appSecret) shopeeFromLark[nm] = parseInt(shopId);
      if (!appKey || !appSecret || !rt) continue;
      const key = nm ? canonKey(nm) : canonKey(shopId);
      if (key) ttByName[key] = { appKey, appSecret, rt, cipher, recordId: r.record_id, name: nm || shopId };
    }
    log('info', `${Object.keys(ttByName).length} toko TikTok punya kredensial lengkap, ${Object.keys(shopeeFromLark).length} toko Shopee ketemu di tabel ini`);
  }

  // Daftar & pencocokan toko Shopee -- 3 lapis, dari yg paling disukai user ke jaring pengaman
  // terakhir. Toko baru cukup ditambahkan SEKALI di tabel Lark di atas (tempat yg SAMA sudah
  // dipakai utk kredensial TikTok) -- tidak perlu diulang di tempat lain.
  //   1) shopeeFromLark  -- dari pembacaan tabel barusan (SUMBER UTAMA, permintaan user).
  //   2) Worker gh_shopee_shop_ids -- kalau tabel Lark di atas kosong/gagal dibaca (mis. base
  //      token belum diisi/berubah); tetap dijaga sinkron dgn panel "Kelola Toko" Maja Apps.
  //   3) SHOPEE_MAP/CFG.shopeeShopIds statis -- jaring pengaman terakhir kalau dua2nya gagal.
  let shopIds = CFG.shopeeShopIds || [];
  if (Object.keys(shopeeFromLark).length) {
    shopIds = Object.values(shopeeFromLark);
    SHOPEE_NORM = buildShopeeNorm(shopeeFromLark);
    log('info', `${shopIds.length} toko Shopee (dari tabel Token Shopee/TikTok di Lark)`);
  } else {
    try {
      const r = await fetch(WORKER_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'gh_shopee_shop_ids', secret: GITHUB_SYNC_SECRET }) }).then(x => x.json());
      if (r.error) throw new Error(r.error);
      if (Array.isArray(r.shops) && r.shops.length) {
        shopIds = r.shops.map(s => s.id);
        const mapLive = {}; for (const s of r.shops) if (s.name) mapLive[s.name] = s.id;
        SHOPEE_NORM = buildShopeeNorm(mapLive);
      }
      log('info', `${shopIds.length} toko Shopee (tabel Lark kosong, fallback ke Worker/Kelola Toko)`);
    } catch (e) {
      log('warn', `Tabel Lark & Worker dua2nya gagal (${e.message}) -- pakai daftar statis cadangan (${shopIds.length} toko)`);
    }
  }

  const shReturnCache = {}, ttCtx = {}, ttReturnCache = {}, backfillUpdates = [];

  // Testing lokal: batasi ke sumber tertentu via env ONLY_SOURCES (nama label, pisah koma,
  // cocok substring case-insensitive) -- TIDAK dibaca di GitHub Actions (env var itu tidak
  // pernah di-set di workflow, jadi produksi tetap proses SEMUA sumber spt biasa). Sekalian
  // menghindari base yg app Lark-nya belum diinvite (Forbidden) kalau base itu tidak sedang ditest.
  let sources = (CFG.orderSources || []).filter(s => s.active !== false);
  if (env.ONLY_SOURCES) {
    const want = env.ONLY_SOURCES.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
    sources = sources.filter(s => want.some(w => (s.label || s.table || '').toLowerCase().includes(w)));
    log('info', `🎯 ONLY_SOURCES aktif: ${sources.map(s => s.label || s.table).join(', ') || '(tidak ada yg cocok!)'}`);
  }
  const optBaseList = (CFG.optBase || '').split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);
  const optBases = [...new Set([...sources.map(s => s.app), CFG.shTokApp, CFG.ttTokApp, ...optBaseList].filter(Boolean))];
  for (const b of optBases) { try { const m = await buildOptionMap(b); log('info', `  • base ${b.slice(0, 12)}… → ${Object.keys(m).length} opsi`); Object.assign(OPT_MAP, m); } catch (e) { log('warn', `Opsi base ${b}: ${e.message}`); } }
  log('info', `Peta opsi gabungan: ${Object.keys(OPT_MAP).length} opsi dari ${optBases.length} base`);

  // klasifikasi target dari semua sumber
  const targets = []; let skipped = 0, skippedFinal = 0;
  const skipFinalDays = Math.max(0, CFG.skipFinalDays || 0);
  // Record final & lama (di-skip dari update Status Terakhir demi hemat API) TAPI kolom
  // returReasonCol & kolom banding-nya (kalau dikonfigur) tetap dicek belakangan, SESUDAH
  // shReturnCache Shopee ke-isi -- 0 API tambahan krn shReturnCache sudah nyakup 90 hari
  // penuh terlepas dari target mana yg diproses. Diminta user (19 Sep 2026): retur LAMA yg
  // justru paling butuh backfill alasan/status banding, jangan ikut ke-skip total.
  const backfillCandidates = [], danaRows = [];
  for (const src of sources) {
    let recs;
    try { recs = await larkAllRecords(src.app, src.table, src.view); }
    catch (e) { log('err', `${src.label || src.table}: ${e.message}`); continue; }
    log('ok', `${src.label || src.table}: ${recs.length} record`);
    // Kolom yg ADA di tabel ini -- menulis ke kolom yg tidak ada menggagalkan SELURUH batch Lark,
    // jadi isian kompensasi hanya memakai kolom yg terbukti ada (mis. "Jumlah Dana Cair" belum ada di MIP).
    let cols = null;
    try {
      const fr = await larkFetch('GET', `/open-apis/bitable/v1/apps/${src.app}/tables/${src.table}/fields?page_size=200`);
      if (fr.code === 0) cols = new Set((fr.data?.items || []).map(f => f.field_name));
    } catch (e) { /* tanpa daftar kolom -> isian kompensasi dilewati utk tabel ini */ }
    if (cols) { const hilang = ['Status Pesanan', 'Tanggal Selesai', 'Progress', 'Jumlah Dana Cair'].filter(c => !cols.has(c)); if (hilang.length) log('warn', `${src.label || src.table}: kolom kompensasi tidak ada → ${hilang.join(', ')} (dilewati)`); }
    for (const rec of recs) {
      const orderSn = getOrderSn(rec.fields);
      if (!orderSn) { skipped++; continue; }
      const prevStatus = larkText(rec.fields['Status Terakhir'] || '');
      const prevTsRaw = rec.fields['Waktu Update Terakhir'];
      const prevTs = prevTsRaw ? (typeof prevTsRaw === 'number' ? prevTsRaw : parseInt(larkText(prevTsRaw)) || 0) : 0;
      const stPesanan = larkText(rec.fields['Status Pesanan'] || ''), progress = larkText(rec.fields['Progress'] || '');
      const tglSelesai = rec.fields['Tanggal Selesai'] || 0, jumlahCair = rec.fields['Jumlah Dana Cair'];
      // pesanan hilang yg kompensasinya belum tercatat lengkap JANGAN di-skip walau sudah "final & lama":
      // kompensasi justru datang belakangan (hari-minggu sesudah dinyatakan hilang).
      const perluKomp = !!cols && isLostCand(prevStatus, stPesanan)
        && (stPesanan !== COMP_STATUS_PESANAN || progress !== COMP_PROGRESS || !tglSelesai || (cols.has('Jumlah Dana Cair') && (jumlahCair == null || jumlahCair === '')));
      // kolom banding (hanya sumber "banding": true). Status Banding sudah Disetujui/Ditolak -> bagian banding dilewati.
      const banding = src.banding ? { status: larkText(rec.fields['Status Banding'] || ''), aju: larkText(rec.fields['Status Aju'] || ''), tglAjuin: rec.fields['Tgl Ajuin'] || 0, tglClose: rec.fields['Tgl Close'] || 0 } : null;
      const perluBanding = !!banding && !BANDING_FINAL.has(banding.status);
      if (src.banding && cols) { // kandidat cek dana cair/ditarik (lihat DANA CAIR)
        const dr = { app: src.app, table: src.table, recordId: rec.record_id, orderSn, toko: getToko(rec.fields), cols, sb: banding.status, ketAdm: larkText(rec.fields['Ket Adm'] || ''),
          peny: larkText(rec.fields['Penyelesaian Komplaian'] || ''), barang: larkText(rec.fields['Status Barang'] || '') };
        if (danaKandidat(dr, Math.floor(Date.now() / 1000))) danaRows.push(dr);
      }
      if (skipFinalDays > 0 && prevStatus && isFinalCategory(categorize(prevStatus)) && prevTs && !perluKomp) {
        const ageDays = (Date.now() - prevTs) / 86400000;
        if (ageDays >= skipFinalDays) {
          skippedFinal++;
          const returReasonCol = src.returReasonCol || '', existingReason = returReasonCol ? larkText(rec.fields[returReasonCol]) : '';
          if ((returReasonCol && !existingReason) || perluBanding) {
            backfillCandidates.push({ app: src.app, table: src.table, recordId: rec.record_id, orderSn, toko: getToko(rec.fields), returReasonCol, existingReason, banding: perluBanding ? banding : null, cols });
          }
          continue;
        }
      }
      const toko = getToko(rec.fields);
      const returReasonCol = src.returReasonCol || '';
      const existingReason = returReasonCol ? larkText(rec.fields[returReasonCol]) : '';
      const base = { app: src.app, table: src.table, srcName: (src.label || src.table), recordId: rec.record_id, orderSn, toko, prevStatus, returReasonCol, existingReason, banding: perluBanding ? banding : null, cols, stPesanan, progress, tglSelesai, jumlahCair };
      if (!toko || toko.trim() === '') {
        targets.push(Object.assign(base, { platform: 'unknown' }));
      } else {
        const ck = canonKey(toko);
        const shopId = SHOPEE_NORM[ck];
        if (shopId) targets.push(Object.assign(base, { platform: 'shopee', shopId }));
        else if (ttByName[ck] || ck.startsWith('tt')) targets.push(Object.assign(base, { platform: 'tiktok' }));
        else targets.push(Object.assign(base, { platform: 'unknown' }));
      }
    }
  }
  log('info', `Target: ${targets.length} order, ${skipped} dilewati${skippedFinal ? `, ${skippedFinal} skip (final & > ${skipFinalDays} hari)` : ''}`);

  // Cache retur per toko -- tokennya sendiri sudah beres di Worker (gh_shopee_proxy), tidak
  // ada lagi "setup token" di sini.
  await Promise.all(shopIds.map(async sid => {
    try { shReturnCache[sid] = await shopeeReturnMap(sid, daysBack); }
    catch (e) { log('err', `Setup Shopee ${sid}: ${e.message}`); }
  }));

  const ttKeys = Object.keys(ttByName);
  await Promise.all(ttKeys.map(async key => {
    const entry = ttByName[key]; if (!entry) return;
    try {
      const tk = await ttRefresh(entry.appKey, entry.appSecret, entry.rt);
      const ctx = { appKey: entry.appKey, appSecret: entry.appSecret, accessToken: tk.access_token };
      let cipher = entry.cipher;
      if (!cipher) {
        const sh = await ttCall(ctx, { method: 'GET', path: `authorization/${VER}/shops` });
        if (sh.code !== 0) log('err', `⚠ Toko "${entry.name}": token/App Key tidak cocok (${sh.code} ${sh.message || ''}) — perlu otorisasi ulang`);
        const arr = sh.data?.shops || []; if (arr[0]) cipher = arr[0].cipher;
      }
      ttCtx[key] = { ctx, cipher };
      const upF = { 'Access Token': tk.access_token, 'Refresh Token': tk.refresh_token }; if (cipher) upF['Shop Cipher'] = cipher;
      larkFetch('PUT', `/open-apis/bitable/v1/apps/${CFG.ttTokApp}/tables/${CFG.ttTokTable}/records/${entry.recordId}`, { fields: upF }).catch(() => {});
      if (cipher) {
        try { ttReturnCache[key] = await ttReturnMap(ctx, cipher, daysBack, entry.name); }
        catch (e) { log('warn', `Retur TikTok "${entry.name}": ${e.message}`); }
      }
    } catch (e) { log('err', `Setup TikTok "${entry.name}": ${e.message}`); }
  }));
  log('ok', `Setup selesai: ${shopIds.length} toko Shopee, ${ttKeys.length} toko TikTok`);

  // Backfill Ket Komplainan + kolom banding utk record final&lama yg tadi di-skip dari update Status
  // Terakhir -- pakai cache retur Shopee & TikTok yg SUDAH ke-isi, 0 API tambahan.
  for (const c of backfillCandidates) {
    const ck = canonKey(c.toko), shopId = SHOPEE_NORM[ck];
    const sInfo = shopId ? (shReturnCache[shopId] || {})[c.orderSn] : null;
    const tInfo = !shopId ? (ttReturnCache[ck] || {})[c.orderSn] : null;
    if (!sInfo && !tInfo) continue;
    const fields = {};
    if (c.returReasonCol && !c.existingReason) {
      const alasan = sInfo ? ((sInfo.reason || sInfo.text_reason) ? formatReturnReason(sInfo.reason, sInfo.text_reason) : '') : formatTtReason(tInfo.reasonText);
      if (alasan) fields[c.returReasonCol] = alasan;
    }
    Object.assign(fields, bandingFields(c, bandingOf(sInfo, tInfo)));
    if (Object.keys(fields).length) backfillUpdates.push({ app: c.app, table: c.table, record_id: c.recordId, fields });
  }
  if (backfillUpdates.length) log('info', `🗄 Backfill: ${backfillUpdates.length} record lama (final & >${skipFinalDays} hari) dapat Ket Komplainan/banding tanpa update Status Terakhir`);

  // dedup No. Pesanan lintas tabel
  const orderGroups = {};
  for (const t of targets) { const key = String(t.orderSn).trim().toUpperCase(); (orderGroups[key] || (orderGroups[key] = [])).push(t); }
  const groupKeys = Object.keys(orderGroups);
  let dupRowsSaved = 0, dupGroupCount = 0;
  for (const k of groupKeys) if (orderGroups[k].length > 1) { dupGroupCount++; dupRowsSaved += orderGroups[k].length - 1; }
  if (dupRowsSaved) log('info', `🔗 ${dupGroupCount} No. Pesanan duplikat — ${dupRowsSaved} baris dihemat`);
  const uniqueTargets = groupKeys.map(k => { const g = orderGroups[k]; const rep = g.find(x => x.platform !== 'unknown') || g[0]; rep._dupGroup = g; return rep; });

  const CONC = Math.max(1, Math.min(30, CFG.concurrency || 6));
  const STUCK = Math.max(1, CFG.stuckDays || 7), STUCK2 = Math.max(1, CFG.stuckDays2 || 14), STUCK3 = Math.max(1, CFG.stuckDays3 || 40);
  const LOST2 = Math.max(1, CFG.lostDays2 || 3);
  const RETUR2 = Math.max(1, CFG.returDays2 || 7);
  const updates = [], compRows = []; let done = 0, gotOk = 0, retOk = 0;
  const catCounts = {}, changedRows = []; let wilayahPakai = 0, wilayahBawaan = 0;
  const seenReasons = new Map(); // kode reason MENTAH dari API -> contoh text_reason (utk verifikasi kamus RETURN_REASON_LABEL pakai data asli, bukan tebakan)
  const seenTtReasons = new Map(); // return_reason_text TikTok -> hasil terjemahannya (idem, utk TT_REASON_LABEL)

  // Data utk batas Stuck per wilayah: provinsi TikTok (detail pesanan, 1 panggilan per 50 pesanan). Layanan/ekspedisi sengaja TIDAK dibedakan (keputusan user 3 Okt 2026).
  // Provinsi Shopee TIDAK diambil dari sini (alamat disamarkan API) -- ditebak dari event tracking (SPEV). Gagal di sini -> batas lama 7/14/40.
  const ttProv = {}; const sparedRows = [];
  try {
    const byTt = {};
    for (const t of uniqueTargets) {
      if (t.platform === 'tiktok') (byTt[canonKey(t.toko)] || (byTt[canonKey(t.toko)] = [])).push(t.orderSn);
    }
    await runPool(Object.entries(byTt), 2, async ([key, ids]) => {
      const e = ttCtx[key]; if (!e || !e.cipher) return;
      for (let i = 0; i < ids.length; i += 50) {
        const r = await ttCall(e.ctx, { method: 'GET', path: `order/${VER}/orders`, query: { ids: ids.slice(i, i + 50).join(',') }, shopCipher: e.cipher });
        for (const o of r.data?.orders || []) { const p = (o.recipient_address?.district_info || []).find(x => x.address_level === 'L1')?.address_name; if (p) ttProv[o.id] = TW.normProv(p); }
      }
    });
    log('info', `🧭 Batas wilayah: provinsi ${Object.keys(ttProv).length} pesanan TikTok`);
  } catch (e) { log('warn', `Data provinsi TikTok gagal (${e.message}) -- semua pesanan pakai batas bawaan ${CFG.stuckDays || 7}/${CFG.stuckDays2 || 14}/${CFG.stuckDays3 || 40}`); }

  await runPool(uniqueTargets, CONC, async (t) => {
    done++;
    let desc = '', ts = 0, shopReturnInfo = null, ttReturnInfo = null;
    try {
      if (t.platform === 'unknown') {
        let found = false;
        const isNumOnly = /^\d{12,}$/.test(t.orderSn);
        if (!isNumOnly) {
          for (const sid of shopIds) { const ft = await shopeeForwardLatest(sid, t.orderSn); if (!ft.err && ft.desc) { found = true; t.platform = 'shopee'; t.shopId = sid; break; } }
        }
        if (!found && isNumOnly) {
          for (const key of ttKeys) { const e = ttCtx[key]; if (!e || !e.cipher) continue; if (await ttOwnsOrder(e.ctx, e.cipher, t.orderSn)) { found = true; t.platform = 'tiktok'; t.toko = key; break; } }
        }
        if (!found && isNumOnly) {
          for (const sid of shopIds) { const ft = await shopeeForwardLatest(sid, t.orderSn); if (!ft.err && ft.desc) { found = true; t.platform = 'shopee'; t.shopId = sid; break; } }
        }
        if (!found) { log('warn', `${t.orderSn} · toko tidak terdeteksi`); failGroup(t, 'Toko tidak terdeteksi di API manapun'); return; }
      }

      if (t.platform === 'shopee') {
        const retInfo = (shReturnCache[t.shopId] || {})[t.orderSn];
        shopReturnInfo = retInfo || null;
        if (retInfo) {
          let revLbl = '';
          if (retInfo.return_sn) { const rt = await shopeeReverse(t.shopId, retInfo.return_sn); if (!rt.err && rt.desc && rt.ts >= ts) { desc = `↩ ${rt.desc}`; ts = rt.ts; } else if (!rt.err && !rt.desc) { revLbl = RETURN_STATUS_LABEL[rt.logiStatus] || ''; } }
          const ft = await shopeeForwardLatest(t.shopId, t.orderSn);
          if (!ft.err && ft.desc && ft.ts >= ts) { desc = `↩ ${ft.desc}`; ts = ft.ts; }
          if (!desc) { desc = `↩ ${revLbl || RETURN_STATUS_LABEL[retInfo.status] || retInfo.status || 'Pengembalian'}`; ts = ts || retInfo.update_time; }
          retOk++;
        } else {
          const ft = await shopeeForwardLatest(t.shopId, t.orderSn);
          if (ft.err) { log('warn', `${t.orderSn} · ${ft.err}`); failGroup(t, `Shopee: ${ft.err}`); return; }
          if (!ft.desc) { failGroup(t, 'Tidak ada event tracking Shopee'); return; }
          desc = ft.desc; ts = ft.ts;
        }
      } else {
        const ttKey = canonKey(t.toko);
        const e = ttCtx[ttKey];
        if (!e) { failGroup(t, `TikTok "${t.toko}" tidak siap/token tidak ada`); return; }
        if (!e.cipher) { failGroup(t, `${t.toko}: shop_cipher tidak ada`); return; }
        // jalur 1: retur (return_refund API) — dicek dulu, kadang lebih baru dari jalur maju
        const retInfo = (ttReturnCache[ttKey] || {})[t.orderSn];
        ttReturnInfo = retInfo || null;
        if (retInfo) {
          if (TT_RETURN_FINAL.has(retInfo.status)) { desc = 'Pesanan dikembalikan ke Agen / Penjual'; ts = retInfo.ts; }
          else { desc = `↩ ${TT_RETURN_LABEL[retInfo.status] || retInfo.status}`; ts = retInfo.ts; }
        }
        // jalur 2: tracking maju — menang kalau timestamp-nya sama/lebih baru dari retur
        const r = await ttTracking(e.ctx, e.cipher, t.orderSn);
        if (!r.err && r.desc && r.ts >= ts) { desc = r.desc; ts = r.ts; }
        if (!desc) {
          if (r.err) { log('warn', `${t.orderSn} · TT ${r.err}`); failGroup(t, `TikTok: ${r.err}`); return; }
          failGroup(t, 'Tidak ada event tracking TikTok'); return;
        }
      }
      if (desc) {
        // batas Stuck per wilayah; provinsi tak ketemu -> amb null -> batas bawaan
        const prov = t.platform === 'shopee' ? TW.provDariEvent(SPEV.get(t.orderSn)) : (ttProv[t.orderSn] || '');
        const amb = prov ? TW.ambang(prov) : null;
        const finalDesc = formatStatus(desc, ts, STUCK, STUCK2, STUCK3, LOST2, RETUR2, amb);
        if (amb) wilayahPakai++; else wilayahBawaan++;
        { const idle = ts ? (Date.now() - ts * 1000) / 86400000 : 0; // idle >= batas lama tapi BELUM Stuck karena wilayahnya lebih jauh
          if (amb && idle >= STUCK && !/^Stuck/.test(finalDesc) && !isFinalCategory(categorize(finalDesc))) sparedRows.push({ orderSn: t.orderSn, toko: t.toko, prov, idle: Math.floor(idle), batas: amb.s1 }); }
        const baseFields = { 'Status Terakhir': finalDesc }; if (ts) baseFields['Waktu Update Terakhir'] = ts * 1000;
        const grp = t._dupGroup || [t];
        for (const row of grp) {
          // Ket Komplainan (alasan retur Shopee) -- hanya utk kolom yg dikonfigur per-sumber
          // (returReasonCol, lihat tracking-config.json), & hanya kalau kolomnya masih kosong
          // (jgn timpa yg sudah diisi manual/sebelumnya). fields per-row (bukan shared) krn
          // sumber lain di grup dedup yg sama biasanya TIDAK punya kolom ini.
          const fields = Object.assign({}, baseFields);
          if (shopReturnInfo && shopReturnInfo.reason && !seenReasons.has(shopReturnInfo.reason)) seenReasons.set(shopReturnInfo.reason, shopReturnInfo.text_reason || '');
          if (ttReturnInfo && ttReturnInfo.reasonText && !seenTtReasons.has(ttReturnInfo.reasonText)) seenTtReasons.set(ttReturnInfo.reasonText, formatTtReason(ttReturnInfo.reasonText));
          if (row.returReasonCol && !row.existingReason) {
            // Shopee & TikTok dua-duanya mengisi kolom yg sama; sumbernya beda field.
            const alasan = shopReturnInfo ? formatReturnReason(shopReturnInfo.reason, shopReturnInfo.text_reason)
              : ttReturnInfo ? formatTtReason(ttReturnInfo.reasonText) : '';
            if (alasan) fields[row.returReasonCol] = alasan;
          }
          // Status Banding / Status Aju / Tgl Ajuin / Tgl Close (lihat komentar BANDING di atas)
          Object.assign(fields, bandingFields(row, bandingOf(shopReturnInfo, ttReturnInfo)));
          updates.push({ app: row.app, table: row.table, record_id: row.recordId, fields });
          if (row.cols && isLostCand(finalDesc, row.stPesanan) && !kompLengkap(row)) compRows.push({ row, platform: t.platform, shopId: t.shopId, ttKey: t.platform === 'tiktok' ? canonKey(t.toko) : '', ts: ts || 0 });
          const cat = categorize(finalDesc); catCounts[cat] = (catCounts[cat] || 0) + 1;
          if (row.prevStatus && row.prevStatus !== finalDesc) changedRows.push({ orderSn: row.orderSn, from: row.prevStatus, to: finalDesc });
        }
        gotOk += grp.length;
      }
    } catch (e) { log('err', `${t.orderSn}: ${e.message}`); failGroup(t, e.message); }
  });

  // ── Kompensasi pesanan hilang: cek wallet Shopee / statement TikTok, siapkan isian kolom ──
  const compUpdates = []; let compBelum = 0;
  if (compRows.length) {
    const nowS = Math.floor(Date.now() / 1000), MAXD = Math.max(7, CFG.compDays || 100) * 86400;
    const fromFor = (rs) => rs.some(r => !r.ts) ? nowS - MAXD : Math.max(nowS - MAXD, Math.min(...rs.map(r => r.ts)) - 2 * 86400);
    const byShop = {}, byTt = {};
    for (const c of compRows) {
      if (c.platform === 'shopee' && c.shopId) (byShop[c.shopId] || (byShop[c.shopId] = [])).push(c);
      else if (c.platform === 'tiktok' && c.ttKey) (byTt[c.ttKey] || (byTt[c.ttKey] = [])).push(c);
    }
    log('info', `💰 Cek kompensasi: ${compRows.length} baris kandidat (${Object.keys(byShop).length} toko Shopee, ${Object.keys(byTt).length} toko TikTok)`);
    const hasil = new Map();
    await runPool(Object.entries(byShop), 3, async ([sid, rs]) => {
      try { const m = await shopeeCompMap(sid, fromFor(rs)); for (const c of rs) { const h = m[c.row.orderSn]; if (h && h.ts) hasil.set(c, h); } }
      catch (e) { log('warn', `Kompensasi Shopee ${sid}: ${e.message}`); }
    });
    await runPool(Object.entries(byTt), 2, async ([key, rs]) => {
      const e = ttCtx[key]; if (!e || !e.cipher) return;
      try { const m = await ttCompMap(e.ctx, e.cipher, fromFor(rs), key); for (const c of rs) { const h = m[c.row.orderSn]; if (h && h.ts) hasil.set(c, h); } }
      catch (er) { log('warn', `Kompensasi TikTok "${key}": ${er.message}`); }
    });
    for (const [c, h] of hasil) {
      const f = compFields(c.row, h);
      if (Object.keys(f).length) compUpdates.push({ app: c.row.app, table: c.row.table, record_id: c.row.recordId, fields: f, orderSn: c.row.orderSn, sumber: c.row.srcName, antes: c.row.stPesanan || '(kosong)' });
    }
    const rinci = {};
    for (const u of compUpdates) { const k = `${u.sumber} · Status Pesanan sebelumnya "${u.antes}"`; rinci[k] = (rinci[k] || 0) + 1; }
    for (const [k, v] of Object.entries(rinci)) log('info', `   💰 ${v}× ${k}`);
    compBelum = compRows.length - hasil.size;
    log('ok', `💰 Kompensasi cair terdeteksi: ${hasil.size} baris (${compUpdates.length} perlu diisi), ${compBelum} belum ada kompensasi`);
  }

  // ── Dana cair / ditarik (R.R by Admin): hanya baris belum final & tanpa banding di marketplace ──
  const danaUpdates = [];
  if (danaRows.length) {
    const nowS = Math.floor(Date.now() / 1000), byShop = {}, byTt = {}; let tanpaToko = 0, adaBanding = 0;
    for (const r of danaRows) {
      const ck = canonKey(r.toko), sid = SHOPEE_NORM[ck];
      const sInfo = sid ? (shReturnCache[sid] || {})[r.orderSn] : null, tInfo = !sid ? (ttReturnCache[ck] || {})[r.orderSn] : null;
      if (bandingOf(sInfo, tInfo)) { adaBanding++; continue; } // diurus bagian BANDING
      if (sid) (byShop[sid] || (byShop[sid] = [])).push(r);
      else if (ttCtx[ck]?.cipher) (byTt[ck] || (byTt[ck] = [])).push(r);
      else tanpaToko++;
    }
    log('info', `💸 Cek dana cair/ditarik: ${danaRows.length} baris belum final (${adaBanding} ada banding → dilewati, ${tanpaToko} toko tak dikenali), ${Object.keys(byShop).length} toko Shopee, ${Object.keys(byTt).length} toko TikTok`);
    const data = new Map(); // row -> {ditarik, cair}
    await runPool(Object.entries(byShop), 3, async ([sid, rs]) => {
      try { const m = await danaShopee(sid, [...new Set(rs.map(r => r.orderSn))], nowS); for (const r of rs) if (m[r.orderSn]) data.set(r, m[r.orderSn]); }
      catch (e) { log('warn', `Dana cair Shopee ${sid}: ${e.message}`); }
    });
    await runPool(Object.entries(byTt), 2, async ([key, rs]) => {
      try { const m = await danaTiktok(ttCtx[key], [...new Set(rs.map(r => r.orderSn))], nowS, key); for (const r of rs) if (m[r.orderSn]) data.set(r, m[r.orderSn]); }
      catch (e) { log('warn', `Dana cair TikTok "${key}": ${e.message}`); }
    });
    const kat = {};
    for (const [r, d] of data) {
      const p = danaRencana(r, d, nowS); kat[p.kat] = (kat[p.kat] || 0) + 1;
      if (Object.keys(p.f).length) danaUpdates.push({ app: r.app, table: r.table, record_id: r.recordId, fields: p.f, orderSn: r.orderSn, kat: p.kat });
    }
    log('ok', `💸 Dana: ${data.size} pesanan dicek (${danaRows.length - adaBanding - tanpaToko - data.size} final/tidak ketemu) · ${Object.entries(kat).map(([k, v]) => `${v}× ${k}`).join(' · ')} → ${danaUpdates.length} baris perlu diisi`);
  }

  // batch update ke Lark (gabung update biasa + backfill Ket Komplainan/banding)
  const allUpdates = updates.concat(backfillUpdates);
  { const b = {}; for (const u of allUpdates) if (u.fields['Status Banding'] || u.fields['Tgl Close'] || u.fields['Tgl Ajuin']) { const k = `${u.fields['Status Banding'] || '(status sama)'} / Aju ${u.fields['Status Aju'] || '-'}`; b[k] = (b[k] || 0) + 1; }
    if (Object.keys(b).length) log('info', `⚖️ Isian banding: ${Object.entries(b).map(([k, v]) => `${v}× ${k}`).join(' · ')}`); }
  if (env.DRY_RUN) {
    log('warn', `🧪 DRY_RUN: ${allUpdates.length} record TIDAK ditulis ke Lark. Contoh 3 yg akan ditulis:`);
    for (const u of allUpdates.slice(0, 3)) log('info', `   ${u.record_id}: ${JSON.stringify(u.fields)}`);
  } else if (allUpdates.length) {
    const byTbl = {};
    for (const u of allUpdates) { const k = u.app + '|' + u.table; (byTbl[k] || (byTbl[k] = [])).push({ record_id: u.record_id, fields: u.fields }); }
    for (const k in byTbl) {
      const [app, table] = k.split('|'); const list = byTbl[k];
      for (let i = 0; i < list.length; i += 500) {
        const chunk = list.slice(i, i + 500);
        const res = await larkFetch('POST', `/open-apis/bitable/v1/apps/${app}/tables/${table}/records/batch_update`, { records: chunk });
        if (res.code !== 0) log('err', `Batch ${table} gagal: ${res.msg}`);
        else log('ok', `Batch ${table}: ${chunk.length} record diupdate ✓`);
      }
    }
  }

  // Isian kompensasi ditulis TERPISAH dari update Status Terakhir di atas: kalau ada yg gagal (mis. opsi
  // "Dana Cair" belum ada di kolom Status Pesanan), sync utama tidak ikut gagal & baris bermasalah kelihatan di log.
  let compTulis = 0;
  if (compUpdates.length) {
    if (env.DRY_RUN) {
      log('warn', `🧪 DRY_RUN kompensasi: ${compUpdates.length} record TIDAK ditulis. Contoh:`);
      for (const u of compUpdates.slice(0, 5)) log('info', `   ${u.orderSn} → ${JSON.stringify(u.fields)}`);
    } else compTulis = await tulisLarkTerpisah(compUpdates, '💰 Kompensasi');
  }
  // Isian dana cair/ditarik juga terpisah (sesudah update banding di atas)
  let danaTulis = 0;
  if (danaUpdates.length) {
    if (env.DRY_RUN) {
      log('warn', `🧪 DRY_RUN dana cair: ${danaUpdates.length} record TIDAK ditulis. Contoh:`);
      for (const u of danaUpdates.slice(0, 8)) log('info', `   ${u.orderSn} [${u.kat}] → ${JSON.stringify(u.fields)}`);
    } else danaTulis = await tulisLarkTerpisah(danaUpdates, '💸 Dana');
  }

  const summary = `Selesai: ${gotOk} diupdate (${retOk} retur Shopee)${backfillUpdates.length ? ` + ${backfillUpdates.length} backfill record lama` : ''}${compUpdates.length ? `, ${env.DRY_RUN ? compUpdates.length : compTulis} kompensasi cair diisi` : ''}${danaUpdates.length ? `, ${env.DRY_RUN ? danaUpdates.length : danaTulis} isian dana cair/ditarik` : ''}, ${skipped} dilewati, ${failedRows.length} error`;
  log('ok', summary);
  const catOrder = ['Diterima Pembeli', 'Kembali ke Seller', `Retur ${RETUR2}+`, `Stuck ${STUCK}+`, `Stuck ${STUCK2}+`, `Stuck ${STUCK3}+`, 'Hilang', `Hilang ${LOST2}+`, 'Lainnya/Proses'];
  const catLine = catOrder.filter(k => catCounts[k]).map(k => `${k}: ${catCounts[k]}`).join(' · ');
  if (catLine) log('info', `📊 Breakdown status: ${catLine}`);
  log('info', `🧭 Batas Stuck: ${wilayahPakai} pesanan pakai batas wilayah, ${wilayahBawaan} pakai batas bawaan ${STUCK}/${STUCK2}/${STUCK3} (provinsi tak diketahui). ${sparedRows.length} pesanan idle ≥${STUCK} hari TIDAK ditandai Stuck karena wilayahnya memang lebih lama.`);
  if (changedRows.length) log('info', `🔄 ${changedRows.length} order berubah status dibanding sebelumnya`);
  if (failedRows.length) log('warn', `⚠ ${failedRows.length} order gagal/error — lihat detail di step summary`);
  if (seenReasons.size) {
    log('info', `🏷 Kode reason retur Shopee ditemukan (${seenReasons.size}):`);
    for (const [code, sample] of seenReasons) log('info', `   ${code}${sample ? ` (text_reason: "${sample}")` : ''} → ditulis: "${formatReturnReason(code, sample)}"`);
  } else if (retOk) {
    log('warn', `⚠ Ada ${retOk} retur Shopee tapi field "reason" kosong semua -- nama field tebakan (ret.reason) kemungkinan SALAH, cek baris DEBUG return_list MENTAH di atas utk nama field asli.`);
  }
  if (seenTtReasons.size) {
    log('info', `🏷 Alasan retur TikTok ditemukan (${seenTtReasons.size}):`);
    for (const [teks, hasil] of seenTtReasons) log('info', `   "${teks}" → ditulis: "${hasil}"${teks === hasil ? '   ⚠ belum diterjemahkan' : ''}`);
  }
  if (seenBandingUnknown.size) log('warn', `⚠ Status banding BARU yg belum dipetakan (tidak ditulis): ${[...seenBandingUnknown].join(', ')} — tambahkan ke SHOPEE_BANDING/TT_BANDING`);

  // GitHub Actions step summary (markdown, muncul di tab Actions)
  const ghStep = env.GITHUB_STEP_SUMMARY;
  if (ghStep) {
    let md = `## 📦 Tracking Sync Summary\n\n${summary}\n\n`;
    if (catLine) md += `**Breakdown:** ${catLine}\n\n`;
    if (sparedRows.length) {
      md += `### 🧭 ${sparedRows.length} pesanan idle ≥${STUCK} hari, belum Stuck (batas wilayah lebih panjang)\n\n| No. Pesanan | Toko | Provinsi | Idle (hari) | Stuck mulai (hari) |\n|---|---|---|---|---|\n`;
      md += sparedRows.sort((a, b) => b.idle - a.idle).slice(0, 100).map(r => `| ${r.orderSn} | ${r.toko} | ${r.prov} | ${r.idle} | ${r.batas} |`).join('\n') + '\n\n';
    }
    if (changedRows.length) {
      md += `### 🔄 ${changedRows.length} Perubahan Status\n\n| No. Pesanan | Dari | Ke |\n|---|---|---|\n`;
      md += changedRows.slice(0, 100).map(r => `| ${r.orderSn} | ${r.from} | ${r.to} |`).join('\n') + '\n\n';
    }
    if (failedRows.length) {
      md += `### ⚠ ${failedRows.length} Gagal/Error\n\n| No. Pesanan | Tabel | Alasan |\n|---|---|---|\n`;
      md += failedRows.slice(0, 200).map(r => `| ${r.orderSn} | ${r.srcName} | ${r.alasan} |`).join('\n') + '\n';
    }
    if (seenReasons.size) {
      md += `\n### 🏷 Kode \`reason\` Retur Shopee (data ASLI dari API run ini)\n\n| Kode Mentah | Contoh text_reason | Ket Komplainan yg ditulis |\n|---|---|---|\n`;
      md += [...seenReasons].map(([code, sample]) => `| ${code} | ${sample || '-'} | ${formatReturnReason(code, sample)} |`).join('\n') + '\n';
      md += `\n_Kamus terjemahan di RETURN_REASON_LABEL (tracking-sync.mjs) masih tebakan — cocokkan kode di atas dgn tabel ini, lalu kabari kode mana yg salah terjemah._\n`;
    }
    appendFileSync(ghStep, md);
  }
}

main().catch(e => { console.error('❌ FATAL:', e); process.exit(1); });
