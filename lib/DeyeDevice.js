'use strict';

const { Device } = require('homey');
const { SolarmanV5Client } = require('./solarmanV5');
const { readAll } = require('./registerParser');

/** @type {number} Polling interval in milliseconds */
const POLL_INTERVAL_MS = 60_000; // v1.2

/** @type {number} Backoff duration at night in milliseconds (30 minutes) */
const NIGHT_BACKOFF_MS = 30 * 60 * 1000;

/** @type {number} Watts above which a daytime failure marks the device unavailable */
const POWER_THRESHOLD_W = 5;

/**
 * Base Deye inverter device.
 * Subclasses must set `this._definitions` before calling `super.onInit()`.
 */
class DeyeDevice extends Device {

  async onInit() {
    this.log('DeyeDevice init v1.2:', this.getName());

    this._lastPowerW   = 0;
    this._backoffUntil = 0;
    this._polling      = false;

    const settings = this.getSettings();

    this._client = new SolarmanV5Client(
      settings.host,
      Number(settings.loggerSerial),
      {
        port:         Number(settings.port)    || 8899,
        slaveId:      Number(settings.slaveId) || 1,
        timeoutMs:    15_000,
        setTimeout:   this.homey.setTimeout.bind(this.homey),
        clearTimeout: this.homey.clearTimeout.bind(this.homey),
      },
    );

    this.homey.setTimeout(() => this._poll().catch(err => this.error('Initial poll error:', err)), 1500);

    this._pollTimer = this.homey.setInterval(
      () => this._poll().catch(err => this.error('Poll error:', err)),
      POLL_INTERVAL_MS,
    );
  }

  async onUninit() {
    if (this._pollTimer) {
      this.homey.clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
    if (this._client) {
      this._client.disconnect();
      this._client = null;
    }
  }

  async onSettings({ newSettings }) {
    await this.onUninit();
    await this.onInit();
  }

  /**
   * Computes local sunrise and sunset using the NOAA simplified algorithm.
   * Uses Homey's geolocation (lat/lng) — accurate to ~5 minutes worldwide.
   * Falls back to a conservative 06:00–19:00 window if geolocation is unavailable.
   *
   * @returns {{ sunrise: number, sunset: number }} Decimal hours in local time.
   */
  _getSunriseSunset() {
    try {
      const lat = this.homey.geolocation.getLatitude();
      const lng = this.homey.geolocation.getLongitude();
      const tz  = this.homey.clock.getTimezone();

      if (!lat || !lng) throw new Error('no geolocation');

      const now       = new Date();
      const dayOfYear = Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 86400000);

      const decl    = 23.45 * Math.sin((Math.PI / 180) * (360 / 365) * (dayOfYear - 81));
      const latRad  = lat  * Math.PI / 180;
      const declRad = decl * Math.PI / 180;
      const cosHA   = -Math.tan(latRad) * Math.tan(declRad);

      if (cosHA <= -1) return { sunrise: 0,  sunset: 24 };
      if (cosHA >=  1) return { sunrise: 12, sunset: 12 };

      const ha = Math.acos(cosHA) * 180 / Math.PI;

      const B         = (2 * Math.PI / 365) * (dayOfYear - 81);
      const eotMin    = 9.87 * Math.sin(2 * B) - 7.53 * Math.cos(B) - 1.5 * Math.sin(B);
      const tzOffsetH = tz ? (new Date(now.toLocaleString('en-US', { timeZone: tz })) - now) / 3600000 : 0;
      const lngOffset = lng / 15;
      const solarNoon = 12 - lngOffset + tzOffsetH - eotMin / 60;

      return {
        sunrise: solarNoon - ha / 15,
        sunset:  solarNoon + ha / 15,
      };
    } catch (_) {
      return { sunrise: 6, sunset: 19 };
    }
  }

  /**
   * Returns true when current local time is outside the solar production window.
   * Applies a 30-minute buffer before sunrise and after sunset.
   *
   * @returns {boolean}
   */
  _isNight() {
    try {
      const { sunrise, sunset } = this._getSunriseSunset();
      const tz    = this.homey.clock.getTimezone();
      const now   = new Date();
      const local = tz ? new Date(now.toLocaleString('en-US', { timeZone: tz })) : now;
      const h     = local.getHours() + local.getMinutes() / 60;
      return h < (sunrise - 0.5) || h >= (sunset + 0.5);
    } catch (_) {
      const h = new Date().getHours();
      return h < 6 || h >= 19;
    }
  }

  /**
   * Sets all instantaneous capabilities to zero.
   * Energy counters (meter_power, meter_power.today) are preserved.
   *
   * @returns {Promise<void>}
   */
  async _applyZeros() {
    const caps = [
      'measure_power',
      'measure_voltage.pv1', 'measure_current.pv1',
      'measure_voltage.pv2', 'measure_current.pv2',
      'measure_voltage.pv3', 'measure_current.pv3',
      'measure_voltage.pv4', 'measure_current.pv4',
      'measure_voltage.grid', 'measure_current.grid',
      'measure_frequency',
      'measure_temperature',
    ];
    await Promise.all(
      caps.filter(c => this.hasCapability(c))
          .map(c => this.setCapabilityValue(c, 0).catch(() => {})),
    );
    this._lastPowerW = 0;
  }

  /**
   * Reads all registers and updates Homey capabilities.
   * At night, poll failures are suppressed and the device stays available.
   *
   * @returns {Promise<void>}
   */
  async _poll() {
    if (Date.now() < this._backoffUntil) return;
    if (this._polling) return;
    this._polling = true;

    try {
      const values = await readAll(this._client, this._definitions);
      this.setAvailable().catch(() => {});

      for (const def of this._definitions) {
        const capId = def.homeyCapability;
        if (!capId) continue;
        const value = values[def.name];
        if (value === null || value === undefined) continue;
        if (!this.hasCapability(capId)) continue;
        // alarm_generic requires boolean — true when inverter reports Fault or Alarm
      const coerced = capId === 'alarm_generic'
        ? (value === 'Fault' || value === 'Alarm')
        : value;

      await this.setCapabilityValue(capId, coerced).catch(err =>
          this.error(`setCapabilityValue(${capId}):`, err.message),
        );
        if (capId === 'measure_power') {
          this._lastPowerW = typeof value === 'number' ? value : 0;
        }
      }

    } catch (err) {
      this._client.disconnect();
      const isNight = this._isNight();

      if (isNight) {
        // Expected offline at night — zero live values, back off 30 min
        await this._applyZeros();
        this.setAvailable().catch(() => {});
        this.log('poll: night timeout (expected), backing off 30 min:', err.message);
        this._backoffUntil = Date.now() + NIGHT_BACKOFF_MS;
      } else if (this._lastPowerW > POWER_THRESHOLD_W) {
        // Was producing — real connectivity problem
        this.error('Poll failed (inverter was active):', err.message);
        this.setUnavailable(this.homey.__('device.unavailable', { error: err.message })).catch(() => {});
      } else {
        // Idle during day — log but stay available
        this.log('Poll failed (inverter idle):', err.message);
      }
    } finally {
      this._polling = false;
    }
  }
}

module.exports = DeyeDevice;
