// Tracking Sync — Zeodda (Shopee + TikTok) — versi cloud (GitHub Actions)
// Port dari "Tracking Logistik Auto.html" (D:\Claude). Tanpa dependency npm — cukup Node.js 18+.
import { createHmac } from 'node:crypto';
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CFG = JSON.parse(readFileSync(join(__dirname, 'tracking-config.json'), 'utf8'));

const SHOPEE_HOST = 'https://partner.shopeemobile.com';
const TT_HOST = 'https://open-api.tiktokglobalshop.com';
const TT_AUTH = 'https://auth.tiktok-shops.com';
const LARK = 'https://open.larksuite.com';
const VER = '202309';

// ═══ SECRET (dari env / GitHub Secrets) ═══
const env = process.env;
const LARK_APP_ID = env.LARK_APP_ID;
const LARK_APP_SECRET = env.LARK_APP_SECRET;
const SHOPEE_PARTNER_ID = env.SHOPEE_PARTNER_ID;
const SHOPEE_PARTNER_KEY = env.SHOPEE_PARTNER_KEY;
if (!LARK_APP_ID || !LARK_APP_SECRET || !SHOPEE_PARTNER_ID || !SHOPEE_PARTNER_KEY) {
  console.error('❌ Secret wajib belum lengkap (LARK_APP_ID/SECRET, SHOPEE_PARTNER_ID/KEY)');
  process.exit(1);
}

// nama toko Shopee (kolom "Toko") → shop id — SAMAKAN dgn Tracking Logistik Auto.html kalau ada perubahan
const SHOPEE_MAP = {
  'SM Zeodda': 867817945, 'SM Zeodda Tangerang': 963990340, 'SM Zeodda Pekanbaru': 899095041,
  'SM Zeodda Bandung': 967593785, 'SM Vamo Indonesia': 981846983, 'SM Vamo Tangerang': 963980234,
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
const isRateLimitMsg = s => /too many request|rate limit|frequent|too_many_request/i.test(String(s || ''));
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
const SHOPEE_NORM = {}; for (const k in SHOPEE_MAP) SHOPEE_NORM[canonKey(k)] = SHOPEE_MAP[k];

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

// ═══ SHOPEE ═══
function shopeeSign(path, shopId, at) { const ts = Math.floor(Date.now() / 1000); const base = (shopId && at) ? `${SHOPEE_PARTNER_ID}${path}${ts}${at}${shopId}` : `${SHOPEE_PARTNER_ID}${path}${ts}`; return { ts, sign: hmacHex(SHOPEE_PARTNER_KEY, base) }; }
async function shopeeGet(path, shopId, at, extra = {}) {
  const { ts, sign } = shopeeSign(path, shopId, at);
  const p = new URLSearchParams({ partner_id: SHOPEE_PARTNER_ID, timestamp: ts, sign, ...(shopId ? { shop_id: shopId } : {}), ...(at ? { access_token: at } : {}), ...extra });
  return fetchJsonRetry(`${SHOPEE_HOST}${path}?${p}`, {}, r => isRateLimitMsg(r.error) || isRateLimitMsg(r.message), `SP ${path}`);
}
async function shopeeRefresh(shopId, rt) {
  const pid = parseInt(SHOPEE_PARTNER_ID) || 0;
  const path = '/api/v2/auth/access_token/get'; const { ts, sign } = shopeeSign(path, null, null);
  const d = await fetch(`${SHOPEE_HOST}${path}?partner_id=${pid}&timestamp=${ts}&sign=${sign}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: rt, shop_id: parseInt(shopId) || shopId, partner_id: pid }) }).then(r => r.json());
  if (d.error && d.error !== '') throw new Error(d.message || d.error);
  if (!d.access_token) throw new Error('tidak ada access_token');
  return d.access_token;
}
async function shopeeForwardLatest(shopId, at, orderSn) {
  const td = await shopeeGet('/api/v2/logistics/get_tracking_info', shopId, at, { order_sn: orderSn });
  if (td.error && td.error !== '') return { err: td.error };
  const ev = td.response?.tracking_list || td.response?.history || td.response?.tracking_info || [];
  if (!ev.length) return { desc: '', ts: 0 };
  const gTs = e => e.ctime || e.time || e.created_time || e.timestamp || e.update_time || e.event_time || 0;
  const gD = e => e.description || e.message || e.status || e.status_description || e.detail || '';
  const l = [...ev].sort((a, b) => gTs(b) - gTs(a))[0]; return { desc: gD(l), ts: gTs(l) };
}
async function shopeeReverse(shopId, at, returnSn) {
  const r = await shopeeGet('/api/v2/returns/get_reverse_tracking_info', shopId, at, { return_sn: returnSn });
  if (r.error && r.error !== '') return { err: r.error };
  const resp = r.response || {}; const ev = resp.tracking_info || resp.post_return_logistics_tracking_info || [];
  if (ev.length) { const l = [...ev].sort((a, b) => (b.update_time || 0) - (a.update_time || 0))[0]; return { desc: l.tracking_description || '', ts: l.update_time || 0 }; }
  return { desc: '', ts: resp.reverse_logistics_update_time || 0, logiStatus: resp.reverse_logistics_status || '' };
}
async function shopeeReturnMap(shopId, at, daysBack) {
  const map = {}; const now = Math.floor(Date.now() / 1000); const CHUNK = 15 * 86400; const from0 = now - daysBack * 86400;
  for (let wf = from0; wf < now; wf += CHUNK) {
    const wt = Math.min(wf + CHUNK - 1, now); let pg = 1, more = true;
    while (more) {
      const r = await shopeeGet('/api/v2/returns/get_return_list', shopId, at, { page_no: pg, page_size: 100, create_time_from: wf, create_time_to: wt });
      if (r.error && r.error !== '') break;
      const list = r.response?.return || [];
      for (const ret of list) { if (ret.order_sn) map[ret.order_sn] = { return_sn: ret.return_sn, status: ret.status || '', update_time: ret.update_time || 0 }; }
      more = !!r.response?.more && list.length > 0; pg++; await sleep(160);
    }
  }
  return map;
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
function formatStatus(desc, ts, stuckDays, stuckDays2, stuckDays3, lostDays2, returDays2) {
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
    if (stuckDays3 && idleDays >= stuckDays3) mapped = `Stuck ${stuckDays3}+ - ` + mapped;
    else if (stuckDays2 && idleDays >= stuckDays2) mapped = `Stuck ${stuckDays2}+ - ` + mapped;
    else if (idleDays >= stuckDays) mapped = `Stuck ${stuckDays}+ - ` + mapped;
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

  // token Shopee dari GitHub Secrets (SHOPEE_REFRESH_TOKEN_<shop_id>), sudah di-maintain workflow lain
  const shopIds = CFG.shopeeShopIds || [];
  const shRt = {};
  for (const sid of shopIds) { const v = env[`SHOPEE_REFRESH_TOKEN_${sid}`]; if (v) shRt[sid] = v; }
  log('info', `${Object.keys(shRt).length}/${shopIds.length} refresh token Shopee ditemukan di secrets`);

  // token TikTok dari tabel Lark (multi-app per toko)
  const ttByName = {};
  if (CFG.ttTokApp && CFG.ttTokTable) {
    const rows = await larkAllRecords(CFG.ttTokApp, CFG.ttTokTable, '');
    for (const r of rows) {
      const f = r.fields;
      const nm = larkText(f[CFG.ttNameCol]);
      const appKey = larkText(f['App Key']), appSecret = larkText(f['App Secret']), rt = larkText(f['Refresh Token']), cipher = larkText(f['Shop Cipher']), shopId = larkText(f['Shop ID']);
      if (!appKey || !appSecret || !rt) continue;
      const key = nm ? canonKey(nm) : canonKey(shopId);
      if (key) ttByName[key] = { appKey, appSecret, rt, cipher, recordId: r.record_id, name: nm || shopId };
    }
    log('info', `${Object.keys(ttByName).length} toko TikTok punya kredensial lengkap`);
  }

  const shAT = {}, shReturnCache = {}, ttCtx = {};

  // peta opsi nama toko: scan semua base terkait
  const sources = (CFG.orderSources || []).filter(s => s.active !== false);
  const optBaseList = (CFG.optBase || '').split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);
  const optBases = [...new Set([...sources.map(s => s.app), CFG.shTokApp, CFG.ttTokApp, ...optBaseList].filter(Boolean))];
  for (const b of optBases) { try { const m = await buildOptionMap(b); log('info', `  • base ${b.slice(0, 12)}… → ${Object.keys(m).length} opsi`); Object.assign(OPT_MAP, m); } catch (e) { log('warn', `Opsi base ${b}: ${e.message}`); } }
  log('info', `Peta opsi gabungan: ${Object.keys(OPT_MAP).length} opsi dari ${optBases.length} base`);

  // klasifikasi target dari semua sumber
  const targets = []; let skipped = 0, skippedFinal = 0;
  const skipFinalDays = Math.max(0, CFG.skipFinalDays || 0);
  for (const src of sources) {
    let recs;
    try { recs = await larkAllRecords(src.app, src.table, src.view); }
    catch (e) { log('err', `${src.label || src.table}: ${e.message}`); continue; }
    log('ok', `${src.label || src.table}: ${recs.length} record`);
    for (const rec of recs) {
      const orderSn = getOrderSn(rec.fields);
      if (!orderSn) { skipped++; continue; }
      const prevStatus = larkText(rec.fields['Status Terakhir'] || '');
      const prevTsRaw = rec.fields['Waktu Update Terakhir'];
      const prevTs = prevTsRaw ? (typeof prevTsRaw === 'number' ? prevTsRaw : parseInt(larkText(prevTsRaw)) || 0) : 0;
      if (skipFinalDays > 0 && prevStatus && isFinalCategory(categorize(prevStatus)) && prevTs) {
        const ageDays = (Date.now() - prevTs) / 86400000;
        if (ageDays >= skipFinalDays) { skippedFinal++; continue; }
      }
      const toko = getToko(rec.fields);
      const base = { app: src.app, table: src.table, srcName: (src.label || src.table), recordId: rec.record_id, orderSn, toko, prevStatus };
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

  // setup token — paralel per toko
  await Promise.all(shopIds.map(async sid => {
    const rt = shRt[sid]; if (!rt) { log('warn', `Shop ${sid}: tidak ada refresh token di secrets`); return; }
    try { shAT[sid] = await shopeeRefresh(sid, rt); shReturnCache[sid] = await shopeeReturnMap(sid, shAT[sid], daysBack); }
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
    } catch (e) { log('err', `Setup TikTok "${entry.name}": ${e.message}`); }
  }));
  log('ok', `Setup selesai: ${shopIds.length} toko Shopee, ${ttKeys.length} toko TikTok`);

  // dedup No. Pesanan lintas tabel
  const orderGroups = {};
  for (const t of targets) { const key = String(t.orderSn).trim().toUpperCase(); (orderGroups[key] || (orderGroups[key] = [])).push(t); }
  const groupKeys = Object.keys(orderGroups);
  let dupRowsSaved = 0, dupGroupCount = 0;
  for (const k of groupKeys) if (orderGroups[k].length > 1) { dupGroupCount++; dupRowsSaved += orderGroups[k].length - 1; }
  if (dupRowsSaved) log('info', `🔗 ${dupGroupCount} No. Pesanan duplikat — ${dupRowsSaved} baris dihemat`);
  const uniqueTargets = groupKeys.map(k => { const g = orderGroups[k]; const rep = g.find(x => x.platform !== 'unknown') || g[0]; rep._dupGroup = g; return rep; });

  const CONC = Math.max(1, Math.min(12, CFG.concurrency || 6));
  const STUCK = Math.max(1, CFG.stuckDays || 7), STUCK2 = Math.max(1, CFG.stuckDays2 || 14), STUCK3 = Math.max(1, CFG.stuckDays3 || 40);
  const LOST2 = Math.max(1, CFG.lostDays2 || 3);
  const RETUR2 = Math.max(1, CFG.returDays2 || 7);
  const updates = []; let done = 0, gotOk = 0, retOk = 0;
  const catCounts = {}, changedRows = [];

  await runPool(uniqueTargets, CONC, async (t) => {
    done++;
    let desc = '', ts = 0;
    try {
      if (t.platform === 'unknown') {
        let found = false;
        const isNumOnly = /^\d{12,}$/.test(t.orderSn);
        if (!isNumOnly) {
          for (const sid of shopIds) { const at = shAT[sid]; if (!at) continue; const ft = await shopeeForwardLatest(sid, at, t.orderSn); if (!ft.err && ft.desc) { found = true; t.platform = 'shopee'; t.shopId = sid; break; } }
        }
        if (!found && isNumOnly) {
          for (const key of ttKeys) { const e = ttCtx[key]; if (!e || !e.cipher) continue; if (await ttOwnsOrder(e.ctx, e.cipher, t.orderSn)) { found = true; t.platform = 'tiktok'; t.toko = key; break; } }
        }
        if (!found && isNumOnly) {
          for (const sid of shopIds) { const at = shAT[sid]; if (!at) continue; const ft = await shopeeForwardLatest(sid, at, t.orderSn); if (!ft.err && ft.desc) { found = true; t.platform = 'shopee'; t.shopId = sid; break; } }
        }
        if (!found) { log('warn', `${t.orderSn} · toko tidak terdeteksi`); failGroup(t, 'Toko tidak terdeteksi di API manapun'); return; }
      }

      if (t.platform === 'shopee') {
        const at = shAT[t.shopId];
        if (!at) { failGroup(t, 'Token Shopee tidak tersedia'); return; }
        const retInfo = (shReturnCache[t.shopId] || {})[t.orderSn];
        if (retInfo) {
          let revLbl = '';
          if (retInfo.return_sn) { const rt = await shopeeReverse(t.shopId, at, retInfo.return_sn); if (!rt.err && rt.desc && rt.ts >= ts) { desc = `↩ ${rt.desc}`; ts = rt.ts; } else if (!rt.err && !rt.desc) { revLbl = RETURN_STATUS_LABEL[rt.logiStatus] || ''; } }
          const ft = await shopeeForwardLatest(t.shopId, at, t.orderSn);
          if (!ft.err && ft.desc && ft.ts >= ts) { desc = `↩ ${ft.desc}`; ts = ft.ts; }
          if (!desc) { desc = `↩ ${revLbl || RETURN_STATUS_LABEL[retInfo.status] || retInfo.status || 'Pengembalian'}`; ts = ts || retInfo.update_time; }
          retOk++;
        } else {
          const ft = await shopeeForwardLatest(t.shopId, at, t.orderSn);
          if (ft.err) { log('warn', `${t.orderSn} · ${ft.err}`); failGroup(t, `Shopee: ${ft.err}`); return; }
          if (!ft.desc) { failGroup(t, 'Tidak ada event tracking Shopee'); return; }
          desc = ft.desc; ts = ft.ts;
        }
      } else {
        const e = ttCtx[canonKey(t.toko)];
        if (!e) { failGroup(t, `TikTok "${t.toko}" tidak siap/token tidak ada`); return; }
        if (!e.cipher) { failGroup(t, `${t.toko}: shop_cipher tidak ada`); return; }
        const r = await ttTracking(e.ctx, e.cipher, t.orderSn);
        if (r.err) { log('warn', `${t.orderSn} · TT ${r.err}`); failGroup(t, `TikTok: ${r.err}`); return; }
        if (!r.desc) { failGroup(t, 'Tidak ada event tracking TikTok'); return; }
        desc = r.desc; ts = r.ts;
      }
      if (desc) {
        const finalDesc = formatStatus(desc, ts, STUCK, STUCK2, STUCK3, LOST2, RETUR2);
        const fields = { 'Status Terakhir': finalDesc }; if (ts) fields['Waktu Update Terakhir'] = ts * 1000;
        const grp = t._dupGroup || [t];
        for (const row of grp) {
          updates.push({ app: row.app, table: row.table, record_id: row.recordId, fields });
          const cat = categorize(finalDesc); catCounts[cat] = (catCounts[cat] || 0) + 1;
          if (row.prevStatus && row.prevStatus !== finalDesc) changedRows.push({ orderSn: row.orderSn, from: row.prevStatus, to: finalDesc });
        }
        gotOk += grp.length;
      }
    } catch (e) { log('err', `${t.orderSn}: ${e.message}`); failGroup(t, e.message); }
  });

  // batch update ke Lark
  if (updates.length) {
    const byTbl = {};
    for (const u of updates) { const k = u.app + '|' + u.table; (byTbl[k] || (byTbl[k] = [])).push({ record_id: u.record_id, fields: u.fields }); }
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

  const summary = `Selesai: ${gotOk} diupdate (${retOk} retur Shopee), ${skipped} dilewati, ${failedRows.length} error`;
  log('ok', summary);
  const catOrder = ['Diterima Pembeli', 'Kembali ke Seller', `Retur ${RETUR2}+`, `Stuck ${STUCK}+`, `Stuck ${STUCK2}+`, `Stuck ${STUCK3}+`, 'Hilang', `Hilang ${LOST2}+`, 'Lainnya/Proses'];
  const catLine = catOrder.filter(k => catCounts[k]).map(k => `${k}: ${catCounts[k]}`).join(' · ');
  if (catLine) log('info', `📊 Breakdown status: ${catLine}`);
  if (changedRows.length) log('info', `🔄 ${changedRows.length} order berubah status dibanding sebelumnya`);
  if (failedRows.length) log('warn', `⚠ ${failedRows.length} order gagal/error — lihat detail di step summary`);

  // GitHub Actions step summary (markdown, muncul di tab Actions)
  const ghStep = env.GITHUB_STEP_SUMMARY;
  if (ghStep) {
    let md = `## 📦 Tracking Sync Summary\n\n${summary}\n\n`;
    if (catLine) md += `**Breakdown:** ${catLine}\n\n`;
    if (changedRows.length) {
      md += `### 🔄 ${changedRows.length} Perubahan Status\n\n| No. Pesanan | Dari | Ke |\n|---|---|---|\n`;
      md += changedRows.slice(0, 100).map(r => `| ${r.orderSn} | ${r.from} | ${r.to} |`).join('\n') + '\n\n';
    }
    if (failedRows.length) {
      md += `### ⚠ ${failedRows.length} Gagal/Error\n\n| No. Pesanan | Tabel | Alasan |\n|---|---|---|\n`;
      md += failedRows.slice(0, 200).map(r => `| ${r.orderSn} | ${r.srcName} | ${r.alasan} |`).join('\n') + '\n';
    }
    appendFileSync(ghStep, md);
  }
}

main().catch(e => { console.error('❌ FATAL:', e); process.exit(1); });
