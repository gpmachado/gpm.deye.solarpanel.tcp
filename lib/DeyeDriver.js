'use strict';

const { Driver } = require('homey');
const { SolarmanV5Client } = require('./solarmanV5');
const { readAll } = require('./registerParser');
const { DEYE_STRING_2MPPT } = require('./deyeRegisters');
const { getLoggerWifiStatus } = require('./getLoggerWifiStatus');

/**
 * Shared Deye driver with pairing logic.
 * Both string drivers extend this class.
 *
 * Pairing flow:
 *  1. pair.html shown — user enters IP, clicks Continue
 *  2. pair.html emits 'list_devices' with { host, port, slaveId, loggerSerial? }
 *  3. session handler fetches logger serial via status.html (auto) or uses provided value
 *  4. Connects TCP 8899, reads inverter serial for device name
 *  5. Returns device to list_devices template
 */
class DeyeDriver extends Driver {

  async onInit() {
    this.log('DeyeDriver init:', this.id);
  }

  /**
   * Attempts to auto-discover the logger serial from status.html.
   * Returns null on any failure.
   *
   * @param {string} host
   * @returns {Promise<number|null>}
   */
  async _fetchLoggerSerial(host) {
    try {
      const status = await getLoggerWifiStatus({ host, user: 'admin', pass: 'admin', timeoutMs: 6000 });
      const match  = status.ap?.ssid?.match(/^AP_(\d+)$/);
      if (!match) return null;
      const serial = parseInt(match[1], 10);
      return Number.isFinite(serial) ? serial : null;
    } catch (_) {
      return null;
    }
  }

  /**
   * Pairing session handler.
   * Registers 'list_devices' handler called by pair.html via Homey.emit().
   *
   * @param {object} session - Homey PairSession
   */
  async onPair(session) {
    session.setHandler('list_devices', async (data) => {
      const host    = (data.host ?? '').trim();
      const port    = parseInt(data.port    ?? '8899', 10);
      const slaveId = parseInt(data.slaveId ?? '1',    10);

      if (!host) throw new Error(this.homey.__('pair.error.host_required'));

      // ── 1. Resolve logger serial ───────────────────────────────────────────
      let loggerSerial;

      if (data.loggerSerial && String(data.loggerSerial).trim() !== '') {
        loggerSerial = parseInt(data.loggerSerial, 10);
        if (!Number.isFinite(loggerSerial)) {
          throw new Error(this.homey.__('pair.error.invalid_serial'));
        }
      } else {
        loggerSerial = await this._fetchLoggerSerial(host);
        if (!loggerSerial) {
          throw new Error(this.homey.__('pair.error.serial_not_found'));
        }
      }

      // ── 2. Connect and read inverter serial for device name ────────────────
      const client = new SolarmanV5Client(host, loggerSerial, { port, slaveId, timeoutMs: 10_000 });
      let inverterSerial = String(loggerSerial);

      try {
        const serialDef = DEYE_STRING_2MPPT.filter(d => d.name === 'Device Serial');
        const values    = await readAll(client, serialDef);
        if (values['Device Serial']) inverterSerial = String(values['Device Serial']);
      } catch (_) {
        // fallback to logger serial as name
      } finally {
        client.disconnect();
      }

      return [{
        name:     `Deye ${inverterSerial}`,
        data:     { id: `deye-${loggerSerial}` },
        settings: { host, loggerSerial, port, slaveId },
      }];
    });
  }
}

module.exports = DeyeDriver;
