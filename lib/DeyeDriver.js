'use strict';

const { Driver } = require('homey');
const { SolarmanV5Client } = require('./solarmanV5');
const { readAll } = require('./registerParser');
const { DEYE_STRING_2MPPT } = require('./deyeRegisters');
const { getLoggerWifiStatus } = require('./getLoggerWifiStatus');
const { scanLoggers } = require('./scanLoggers');

/**
 * Shared Deye driver with pairing logic.
 * All string / hybrid / micro drivers extend this class.
 *
 * Pairing -- three paths:
 *
 *  A) Auto-discover (user clicks "Scan"):
 *     pair.html emits 'discover' -> UDP broadcast -> returns [{ip, mac, serial}]
 *     User picks a logger -> pair.html emits 'list_devices' with full {host, loggerSerial}
 *
 *  B) Manual IP + auto serial (default admin/admin password):
 *     pair.html emits 'list_devices' with { host } only
 *     Driver fetches serial via status.html
 *
 *  C) Manual IP + manual serial (custom password or auto-detect failed):
 *     Frontend shows serial field after B fails
 *     pair.html emits 'list_devices' with { host, loggerSerial }
 */
class DeyeDriver extends Driver {

  async onInit() {
    this.log('DeyeDriver init:', this.id);
  }

  /**
   * Tries to read the logger serial from status.html (admin/admin).
   * Returns null on any failure -- never throws.
   *
   * @param {string} host
   * @returns {Promise<number|null>}
   */
  async _fetchLoggerSerial(host) {
    try {
      const status = await getLoggerWifiStatus({ host, user: 'admin', pass: 'admin', timeoutMs: 3000 });
      const match = status.ap?.ssid?.match(/^AP_(\d+)$/);
      if (match) {
        const serial = parseInt(match[1], 10);
        if (Number.isFinite(serial)) return serial;
      }
    } catch (_) {
      // Ignore HTTP error
    }

    try {
      const loggers = await scanLoggers({ timeoutMs: 2500 });
      const found = loggers.find(l => l.ip === host);
      if (found && Number.isFinite(found.serial)) {
        return found.serial;
      }
    } catch (_) {
      // Ignore UDP error
    }

    return null;
  }

  /**
   * Reads the inverter serial number over Modbus for use as device name.
   * Falls back to the logger serial on any error.
   *
   * @param {string} host
   * @param {number} loggerSerial
   * @param {{ port?: number, slaveId?: number }} opts
   * @returns {Promise<string>}
   */
  async _readInverterSerial(host, loggerSerial, { port = 8899, slaveId = 1 } = {}) {
    const client = new SolarmanV5Client(host, loggerSerial, { port, slaveId, timeoutMs: 10_000 });
    try {
      const defs = DEYE_STRING_2MPPT.filter(d => d.name === 'Device Serial');
      const values = await readAll(client, defs);
      return values['Device Serial'] ? String(values['Device Serial']) : String(loggerSerial);
    } catch (_) {
      return String(loggerSerial);
    } finally {
      client.disconnect();
    }
  }

  /**
   * Resolves connection params, reads inverter serial and returns the list
   * of Homey devices to create. Subclasses can override this method to
   * return additional companion devices (e.g. a battery sub-device).
   *
   * @param {object} data - Data from the pairing session
   * @returns {Promise<object[]>}
   */
  async _buildDeviceList(data) {
    const host = (data.host ?? '').trim();
    const port = parseInt(data.port ?? '8899', 10);
    const slaveId = parseInt(data.slaveId ?? '1', 10);

    if (!host) throw new Error(this.homey.__('pair.error.host_required'));

    // Resolve serial -- from data (paths A/C) or auto-detect (path B)
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

    const inverterSerial = await this._readInverterSerial(host, loggerSerial, { port, slaveId });

    return [{
      name: `Deye ${inverterSerial}`,
      data: { id: `deye-${loggerSerial}` },
      settings: { host, loggerSerial, port, slaveId },
    }];
  }

  /**
   * @param {object} session - Homey PairSession
   */
  async onPair(session) {

    // -- Path A: UDP broadcast scan ------------------------------------------
    session.setHandler('discover', async () => {
      this.log('pair: UDP discovery...');
      const loggers = await scanLoggers({ timeoutMs: 3000 });
      this.log(`pair: found ${loggers.length} logger(s)`);
      return loggers; // [{ ip, mac, serial }]
    });

    // -- Path B helper: try to fetch serial for a given IP ------------------
    session.setHandler('check_serial', async ({ host }) => {
      const serial = await this._fetchLoggerSerial((host ?? '').trim());
      return { serial }; // { serial: null } means auto-detect failed
    });

    // -- Paths B + C: validate connection and create device(s) --------------
    session.setHandler('list_devices', async (data) => {
      return this._buildDeviceList(data);
    });
  }
}

module.exports = DeyeDriver;
