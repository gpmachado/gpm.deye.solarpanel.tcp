'use strict';

const DeyeDevice = require('../../lib/DeyeDevice');
const { DEYE_SG04LP3 } = require('../../lib/deyeSG04LP3Registers');

/**
 * Battery-only device for Deye SUN-8/10/12K-SG04LP3-EU.
 *
 * Shares the same physical inverter as DeyeHybrid3PhaseDevice but
 * exposes only battery capabilities so Homey Energy can correctly
 * classify charging / discharging separately from solar generation.
 *
 * The register definitions are filtered to battery-related capabilities
 * only -- no PV, grid or load registers are polled by this device.
 */

/** Battery-related capability names polled by this device */
const BATTERY_CAPABILITIES = new Set([
  'measure_battery',
  'measure_power.battery',
  'measure_voltage.battery',
  'measure_temperature.battery',
  'meter_power.battery_charged',
  'meter_power.battery_discharged',
  'meter_power.battery_charged_today',
  'meter_power.battery_discharged_today',
]);

const BATTERY_DEFINITIONS = DEYE_SG04LP3.filter(
  d => d.homeyCapability && BATTERY_CAPABILITIES.has(d.homeyCapability),
);

// Preserve explicit request blocks so registerParser uses the correct
// address ranges instead of auto-merging across large gaps.
BATTERY_DEFINITIONS._requests = DEYE_SG04LP3._requests;

class DeyeHybrid3PhaseBatteryDevice extends DeyeDevice {

  async onInit() {
    this._definitions = BATTERY_DEFINITIONS;
    await super.onInit();
  }

}

module.exports = DeyeHybrid3PhaseBatteryDevice;
