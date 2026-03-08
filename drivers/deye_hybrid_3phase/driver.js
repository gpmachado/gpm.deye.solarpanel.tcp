'use strict';

const DeyeDriver = require('../../lib/DeyeDriver');

/**
 * Driver for the Deye SUN-8/10/12K-SG04LP3-EU hybrid inverter.
 *
 * During pairing this driver creates TWO Homey devices from a single
 * physical inverter:
 *
 *   1. Solar inverter  (this driver, class: solarpanel)
 *      → PV, grid, load, temperature capabilities
 *
 *   2. Home battery    (deye_hybrid_3phase_battery, class: battery)
 *      → battery SOC, power, voltage, temperature, energy counters
 *
 * Homey Energy requires separate device classes to correctly account for
 * solar generation and battery charge/discharge independently.
 */
class DeyeHybrid3PhaseDriver extends DeyeDriver {

  /**
   * Override _buildDeviceList to also create the battery companion device.
   */
  async _buildDeviceList(data) {
    const baseDevices = await super._buildDeviceList(data);
    if (!baseDevices || baseDevices.length === 0) return baseDevices;

    const solar = baseDevices[0];

    // Battery companion device -- same connection settings, separate driver
    const battery = {
      name:     `${solar.name} Battery`,
      data:     { id: `${solar.data.id}-battery` },
      settings: { ...solar.settings },
      driver:   'deye_hybrid_3phase_battery',
    };

    return [solar, battery];
  }

}

module.exports = DeyeHybrid3PhaseDriver;
