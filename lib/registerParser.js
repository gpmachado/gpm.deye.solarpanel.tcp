'use strict';

/**
 * @fileoverview Register value parser aligned with ha-solarman parser.py rule numbering.
 *
 * Rule mapping (identical to ha-solarman):
 *   1 | 3 = unsigned, N registers accumulated lo-first
 *   2 | 4 = signed,   N registers accumulated lo-first, then sign-extended
 *   5     = ASCII string: N registers, 2 chars per register (hi byte, lo byte)
 *   6     = bits (hex array string) — not used for numeric capabilities
 *   7     = version string (nibble-formatted) — not used for numeric capabilities
 *
 * offset/scale formula (matches ha-solarman parser.py):
 *   decoded = (raw - offset) * scale
 */

/**
 * @typedef {object} RegisterDefinition
 * @property {string}   name                 - Human-readable sensor name
 * @property {number}   rule                 - Parsing rule (1–7, matches ha-solarman)
 * @property {number[]} registers            - Modbus register addresses
 * @property {number}   [scale=1]            - Multiplier: decoded = (raw - offset) * scale
 * @property {number}   [offset=0]           - Subtracted before scale
 * @property {string}   [uom]                - Unit of measure (e.g. "W", "V", "kWh")
 * @property {string|null} [homeyCapability] - Homey capability ID, or null to skip
 * @property {number}   [fc=3]               - Modbus function code (3=holding, 4=input)
 * @property {Array<{key: number|number[], value: string}>} [lookup] - Enum map for rules 1/3
 */

/**
 * Decodes raw register values according to the definition rule.
 *
 * @param {RegisterDefinition} def
 * @param {Map<number, number>} registerMap - address → raw uint16
 * @returns {number|string|null}
 */
function decodeRegister(def, registerMap) {
  const regs = def.registers;
  for (const addr of regs) {
    if (!registerMap.has(addr)) return null;
  }

  const scale  = def.scale  ?? 1;
  const offset = def.offset ?? 0;

  switch (def.rule) {

    // ── Rules 1 & 3: unsigned, N registers lo-first ──────────────────────────
    case 1:
    case 3: {
      let raw = 0;
      for (let i = 0; i < regs.length; i++) {
        raw += (registerMap.get(regs[i]) & 0xffff) * Math.pow(2, 16 * i);
      }
      raw = raw >>> 0;

      if (def.lookup) {
        for (const entry of def.lookup) {
          const keys = Array.isArray(entry.key) ? entry.key : [entry.key];
          if (keys.includes(raw)) return entry.value;
        }
        return `Unknown(${raw})`;
      }

      return (raw - offset) * scale;
    }

    // ── Rules 2 & 4: signed, N registers lo-first ────────────────────────────
    case 2:
    case 4: {
      // Accumulate unsigned first (same as rules 1/3)
      let raw = 0;
      for (let i = 0; i < regs.length; i++) {
        raw += (registerMap.get(regs[i]) & 0xffff) * Math.pow(2, 16 * i);
      }
      // Sign-extend: threshold = 2^(16*n - 1), wrap = 2^(16*n)
      const bits = 16 * regs.length;
      const wrap = Math.pow(2, bits);
      const threshold = wrap / 2;
      if (raw >= threshold) raw -= wrap;
      return (raw - offset) * scale;
    }

    // ── Rule 5: ASCII string (chr(hi) + chr(lo) per register) ────────────────
    case 5: {
      let str = '';
      for (const addr of regs) {
        const r  = registerMap.get(addr);
        const hi = (r >> 8) & 0xff;
        const lo = r & 0xff;
        if (hi) str += String.fromCharCode(hi);
        if (lo) str += String.fromCharCode(lo);
      }
      return str.trim();
    }

    // ── Rule 6: bits → hex array string ──────────────────────────────────────
    case 6: {
      return regs.map(a => '0x' + registerMap.get(a).toString(16).padStart(4, '0')).join(',');
    }

    // ── Rule 7: version string (nibble-formatted) ─────────────────────────────
    case 7: {
      return regs.map(a => {
        const r = registerMap.get(a);
        return `${(r >> 12) & 0xf}.${(r >> 8) & 0xf}.${(r >> 4) & 0xf}.${r & 0xf}`;
      }).join('-');
    }

    default:
      return null;
  }
}

/**
 * Builds minimum contiguous Modbus read requests to cover all definitions,
 * grouped by function code, merged into ranges <= maxCount registers.
 *
 * @param {RegisterDefinition[]} definitions
 * @param {number} [maxCount=100]
 * @returns {Array<{fc: number, start: number, count: number}>}
 */
function buildReadRequests(definitions, maxCount = 100) {
  /** @type {Map<number, Set<number>>} */
  const byFc = new Map();

  for (const def of definitions) {
    const fc = def.fc ?? 3;
    if (!byFc.has(fc)) byFc.set(fc, new Set());
    for (const addr of def.registers) byFc.get(fc).add(addr);
  }

  /** @type {Array<{fc: number, start: number, count: number}>} */
  const requests = [];

  for (const [fc, addrSet] of byFc) {
    const sorted = [...addrSet].sort((a, b) => a - b);
    let start = sorted[0];
    let end   = sorted[0];

    for (let i = 1; i < sorted.length; i++) {
      const addr = sorted[i];
      if (addr - start < maxCount) {
        end = addr;
      } else {
        requests.push({ fc, start, count: end - start + 1 });
        start = addr;
        end   = addr;
      }
    }
    requests.push({ fc, start, count: end - start + 1 });
  }

  return requests;
}

/**
 * Executes read requests and returns a populated register map.
 *
 * @param {import('./solarmanV5').SolarmanV5Client} client
 * @param {Array<{fc: number, start: number, count: number}>} requests
 * @returns {Promise<Map<number, number>>}
 */
async function fetchRegisters(client, requests) {
  /** @type {Map<number, number>} */
  const map = new Map();

  for (const req of requests) {
    const values = req.fc === 4
      ? await client.readInputRegisters(req.start, req.count)
      : await client.readHoldingRegisters(req.start, req.count);

    for (let i = 0; i < values.length; i++) {
      map.set(req.start + i, values[i]);
    }
  }

  return map;
}

/**
 * Reads all defined registers from the inverter and returns decoded sensor values.
 *
 * @param {import('./solarmanV5').SolarmanV5Client} client
 * @param {RegisterDefinition[]} definitions
 * @returns {Promise<Object.<string, number|string|null>>}
 */
async function readAll(client, definitions) {
  const requests    = buildReadRequests(definitions);
  const registerMap = await fetchRegisters(client, requests);

  /** @type {Object.<string, number|string|null>} */
  const result = {};
  for (const def of definitions) {
    result[def.name] = decodeRegister(def, registerMap);
  }
  return result;
}

module.exports = { decodeRegister, buildReadRequests, fetchRegisters, readAll };
