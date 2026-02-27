'use strict';

/**
 * @fileoverview Solarman logger Wi-Fi status reader (status.html).
 */

/**
 * @param {string} url
 * @param {{user:string, pass:string, timeoutMs?:number}} opts
 * @returns {Promise<string>}
 */
async function fetchText(url, { user, pass, timeoutMs = 8000 }) {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), timeoutMs);

  const auth = Buffer.from(`${user}:${pass}`).toString('base64');
  const res = await fetch(url, {
    headers: { Authorization: `Basic ${auth}` },
    signal: controller.signal,
  }).finally(() => clearTimeout(t));

  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} on ${url}`);
    err.status = res.status;
    throw err;
  }
  return await res.text();
}

/**
 * @param {string} html
 * @param {string} name
 * @returns {string|null}
 */
function getJsVar(html, name) {
  const re = new RegExp(`var\\s+${name}\\s*=\\s*"([^"]*)";`, 'i');
  return html.match(re)?.[1] ?? null;
}

/**
 * @param {string|null} s
 * @returns {number|null}
 */
function parsePercent(s) {
  if (!s) return null;
  const m = s.match(/(\d{1,3})\s*%/);
  if (!m) return null;
  const n = Number(m[1]);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, n));
}

/**
 * Read logger Wi-Fi info.
 * @param {{host:string, user:string, pass:string, timeoutMs?:number}} params
 * @returns {Promise<{
 *   mode:string|null,
 *   ap:{ssid:string|null, ip:string|null, mac:string|null},
 *   sta:{ssid:string|null, ip:string|null, mac:string|null, signalQuality:number|null}
 * }>}
 */
async function getLoggerWifiStatus({ host, user, pass, timeoutMs = 8000 }) {
  const html = await fetchText(`http://${host}/status.html`, { user, pass, timeoutMs });

  const mode = getJsVar(html, 'cover_wmode');

  const ap = {
    ssid: getJsVar(html, 'cover_ap_ssid'),
    ip: getJsVar(html, 'cover_ap_ip'),
    mac: getJsVar(html, 'cover_ap_mac'),
  };

  const staRssiRaw = getJsVar(html, 'cover_sta_rssi');

  const sta = {
    ssid: getJsVar(html, 'cover_sta_ssid'),
    ip: getJsVar(html, 'cover_sta_ip'),
    mac: getJsVar(html, 'cover_sta_mac'),
    signalQuality: parsePercent(staRssiRaw),
  };

  return { mode, ap, sta };
}

module.exports = { getLoggerWifiStatus };