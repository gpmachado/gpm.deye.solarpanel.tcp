#!/usr/bin/env node
'use strict';

/**
 * Solarman Logger UDP Discovery — standalone test script
 *
 * Usage:
 *   node test-discovery.js
 *   node test-discovery.js --timeout 10000
 *   node test-discovery.js --broadcast 192.168.1.255
 */

const dgram = require('dgram');

// --- Config -----------------------------------------------------------------
const DISCOVERY_PORT    = 48899;
const DISCOVERY_PAYLOAD = 'WIFIKIT-214028-READ';

const args      = process.argv.slice(2);
const timeoutMs = parseInt(args[args.indexOf('--timeout') + 1] || '5000', 10);
const broadcast = args[args.indexOf('--broadcast') + 1] || '255.255.255.255';

// --- Helpers ----------------------------------------------------------------
const green  = s => `\x1b[32m${s}\x1b[0m`;
const yellow = s => `\x1b[33m${s}\x1b[0m`;
const red    = s => `\x1b[31m${s}\x1b[0m`;
const bold   = s => `\x1b[1m${s}\x1b[0m`;

// --- Main -------------------------------------------------------------------
console.log(bold('\n🔍 Solarman UDP Logger Discovery'));
console.log('─'.repeat(40));
console.log(`Broadcast  : ${yellow(broadcast)}`);
console.log(`Port       : ${yellow(DISCOVERY_PORT)}`);
console.log(`Payload    : ${yellow(DISCOVERY_PAYLOAD)}`);
console.log(`Timeout    : ${yellow(timeoutMs + 'ms')}`);
console.log('─'.repeat(40));
console.log('Sending broadcast...\n');

const found  = [];
const seen   = new Set();
let   closed = false;

const sock = dgram.createSocket({ type: 'udp4', reuseAddr: true });

const finish = () => {
  if (closed) return;
  closed = true;
  try { sock.close(); } catch (_) {}

  console.log('\n' + '─'.repeat(40));
  if (found.length === 0) {
    console.log(red('✗ No loggers found.'));
    console.log('\nTroubleshooting:');
    console.log('  - Make sure your computer is on the same network as the logger');
    console.log('  - Try with a specific broadcast: node test-discovery.js --broadcast 192.168.1.255');
    console.log('  - Check if port 48899 UDP is blocked by firewall');
  } else {
    console.log(green(`✓ Found ${found.length} logger(s):\n`));
    found.forEach((l, i) => {
      console.log(bold(`  Logger ${i + 1}:`));
      console.log(`    IP     : ${green(l.ip)}`);
      console.log(`    MAC    : ${l.mac}`);
      console.log(`    Serial : ${green(l.serial)}`);
      console.log();
    });
    console.log('Use these values in your Homey app pairing:');
    found.forEach(l => {
      console.log(`  IP: ${yellow(l.ip)}  Serial: ${yellow(l.serial)}`);
    });
  }
  console.log('─'.repeat(40) + '\n');
};

sock.on('error', (err) => {
  console.error(red(`Socket error: ${err.message}`));
  finish();
});

sock.on('message', (msg, rinfo) => {
  const raw = msg.toString().trim();
  console.log(`← Raw response from ${rinfo.address}: ${yellow(raw)}`);

  try {
    const parts = raw.split(',');
    if (parts.length < 3) {
      console.log(red('  ⚠ Could not parse response (unexpected format)'));
      return;
    }

    const ip     = parts[0].trim();
    const mac    = parts[1].trim();
    const serial = parseInt(parts[2].trim(), 10);

    if (!ip || !mac || !Number.isFinite(serial)) {
      console.log(red('  ⚠ Invalid IP, MAC or serial in response'));
      return;
    }

    if (seen.has(ip)) {
      console.log(`  (duplicate, skipping)`);
      return;
    }

    seen.add(ip);
    found.push({ ip, mac, serial });
    console.log(green(`  ✓ Parsed: IP=${ip}  MAC=${mac}  Serial=${serial}`));
  } catch (err) {
    console.log(red(`  ⚠ Parse error: ${err.message}`));
  }
});

sock.bind(0, '0.0.0.0', () => {
  const addr = sock.address();
  console.log(`Socket bound on 0.0.0.0:${addr.port}`);

  sock.setBroadcast(true);

  const payload = Buffer.from(DISCOVERY_PAYLOAD);
  sock.send(payload, 0, payload.length, DISCOVERY_PORT, broadcast, (err) => {
    if (err) {
      console.error(red(`✗ Failed to send broadcast: ${err.message}`));
      finish();
      return;
    }
    console.log(`→ Broadcast sent to ${broadcast}:${DISCOVERY_PORT}`);
    console.log(`  Waiting ${timeoutMs}ms for responses...\n`);
  });

  setTimeout(finish, timeoutMs);
});
