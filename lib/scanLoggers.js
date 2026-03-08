'use strict';

const dgram = require('dgram');

/**
 * @fileoverview Solarman Wi-Fi logger UDP discovery.
 *
 * Protocol (identical to ha-solarman scanner.py):
 *   Send UDP broadcast "WIFIKIT-214028-READ" -> port 48899
 *   Each logger on the LAN replies with "IP,MAC,Serial\n"
 *
 * Works without knowing the IP in advance -- the Homey Pro sends
 * the broadcast and loggers respond directly.
 */

const DISCOVERY_PORT    = 48899;
const DISCOVERY_PAYLOAD = 'WIFIKIT-214028-READ';
const DISCOVERY_TIMEOUT = 3000; // ms -- collect all replies in this window

/**
 * @typedef {object} LoggerInfo
 * @property {string} ip
 * @property {string} mac
 * @property {number} serial
 */

/**
 * Sends a UDP broadcast and collects all Solarman logger responses.
 *
 * @param {object}  [options]
 * @param {number}  [options.timeoutMs=3000]  How long to wait for replies.
 * @param {string}  [options.bindAddress='0.0.0.0']
 * @returns {Promise<LoggerInfo[]>}  Array of discovered loggers (may be empty).
 */
function scanLoggers({ timeoutMs = DISCOVERY_TIMEOUT, bindAddress = '0.0.0.0' } = {}) {
  return new Promise((resolve) => {
    const found  = [];
    const seen   = new Set();
    let   closed = false;

    const sock = dgram.createSocket({ type: 'udp4', reuseAddr: true });

    const finish = () => {
      if (closed) return;
      closed = true;
      try { sock.close(); } catch (_) {}
      resolve(found);
    };

    sock.on('error', () => finish());

    sock.on('message', (msg) => {
      try {
        // Response format: "192.168.1.x,AA:BB:CC:DD:EE:FF,1782317166\n"
        const parts = msg.toString().trim().split(',');
        if (parts.length < 3) return;

        const ip     = parts[0].trim();
        const mac    = parts[1].trim();
        const serial = parseInt(parts[2].trim(), 10);

        if (!ip || !mac || !Number.isFinite(serial)) return;
        if (seen.has(ip)) return;

        seen.add(ip);
        found.push({ ip, mac, serial });
      } catch (_) {
        // ignore malformed responses
      }
    });

    sock.bind(0, bindAddress, () => {
      sock.setBroadcast(true);

      const payload = Buffer.from(DISCOVERY_PAYLOAD);
      sock.send(payload, 0, payload.length, DISCOVERY_PORT, '255.255.255.255', (err) => {
        if (err) finish();
      });

      setTimeout(finish, timeoutMs);
    });
  });
}

module.exports = { scanLoggers };
