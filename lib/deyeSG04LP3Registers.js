'use strict';

/**
 * @fileoverview Register definitions for Deye SUN-8/10/12K-SG04LP3-EU
 *
 * Three-phase hybrid inverter with low-voltage battery, 2x MPPT.
 * Kept separate from deyeRegisters.js -- existing profiles untouched.
 *
 * Source: deye_sg04lp3.yaml by Mathajas (PR #739 on ha-solarman, MIT)
 *         Tested on SUN-10K-SG04LP3-EU, fw LSW3_15_FFFF_1.0.91R
 *         Based on official Deye Modbus documentation.
 *
 * Register request ranges (7 separate blocks):
 *   0x0003-0x0059   0x0080-0x0085   0x0202-0x022E
 *   0x024A-0x024F   0x0256-0x027C   0x0284-0x028D
 *   0x02A0-0x02A7
 *
 * Rule reference (same as registerParser.js):
 *   1 | 3 = unsigned, N registers lo-first
 *   2 | 4 = signed,   N registers lo-first, sign-extended
 *   5     = ASCII string (chr(hi)+chr(lo) per register)
 *   6     = hex bit array (alert/fault flags)
 *
 * offset/scale formula: decoded = (raw - offset) * scale
 *
 * NOTE -- Load L1/L2/L3 bug fix vs ha-solarman main:
 *   The old YAML used registers 0x0168-0x016A (rule 1, unsigned) for Load
 *   per-phase power. When solar export exceeded load, the signed value went
 *   negative, raw read as ~0xFFxx, decoded as ~65kW per phase (issue #685).
 *   Mathajas fixes this by using a NEW register block 0x028A-0x028C which
 *   the firmware always populates with positive load values (no sign bit).
 *   Rule 1 (unsigned) is therefore correct for these new registers.
 *
 * @typedef {import('./registerParser').RegisterDefinition} RegisterDefinition
 */

// -- Solar / PV --------------------------------------------------------------

/** @type {RegisterDefinition[]} */
const DEYE_SG04LP3 = [

  // Block 0x02A0-0x02A7
  {
    name: 'PV1 Power',
    rule: 1,
    registers: [0x02A0],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.pv1',
  },
  {
    name: 'PV2 Power',
    rule: 1,
    registers: [0x02A1],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.pv2',
  },
  {
    name: 'PV1 Voltage',
    rule: 1,
    registers: [0x02A4],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.pv1',
  },
  {
    name: 'PV1 Current',
    rule: 1,
    registers: [0x02A5],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.pv1',
  },
  {
    name: 'PV2 Voltage',
    rule: 1,
    registers: [0x02A6],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.pv2',
  },
  {
    name: 'PV2 Current',
    rule: 1,
    registers: [0x02A7],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.pv2',
  },

  // Production energy -- Block 0x0202-0x022E
  {
    name: 'Daily Production',
    rule: 1,
    registers: [0x0211],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.today',
    validation: { max: 100 },
  },
  {
    name: 'Total Production',
    rule: 3,
    registers: [0x0216, 0x0217],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power',
  },

  // -- Battery ----------------------------------------------------------------

  // Energy counters -- Block 0x0202-0x022E
  {
    name: 'Daily Battery Charge',
    rule: 1,
    registers: [0x0202],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.battery_charged_today',
  },
  {
    name: 'Daily Battery Discharge',
    rule: 1,
    registers: [0x0203],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.battery_discharged_today',
  },
  {
    name: 'Total Battery Charge',
    rule: 3,
    registers: [0x0204, 0x0205],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.battery_charged',
  },
  {
    name: 'Total Battery Discharge',
    rule: 3,
    registers: [0x0206, 0x0207],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.battery_discharged',
  },

  // Instantaneous -- Block 0x024A-0x024F
  {
    name: 'Battery Temperature',
    rule: 1,
    registers: [0x024A],
    offset: 1000,
    scale: 0.1,
    uom: ' degC',
    homeyCapability: 'measure_temperature.battery',
    validation: { min: 1, max: 99 },
  },
  {
    name: 'Battery Voltage',
    rule: 1,
    registers: [0x024B],
    scale: 0.01,
    uom: 'V',
    homeyCapability: 'measure_voltage.battery',
  },
  {
    name: 'Battery SOC',
    rule: 1,
    registers: [0x024C],
    scale: 1,
    uom: '%',
    homeyCapability: 'measure_battery',
    validation: { min: 0, max: 101 },
  },
  {
    // positive = charging, negative = discharging
    name: 'Battery Power',
    rule: 2,
    registers: [0x024E],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.battery',
  },
  {
    name: 'Battery Current',
    rule: 2,
    registers: [0x024F],
    scale: 0.01,
    uom: 'A',
    homeyCapability: 'measure_current.battery',
  },

  // Battery status -- Block 0x0003-0x0059
  {
    name: 'Battery Status',
    rule: 1,
    registers: [0x0058],
    lookup: [
      { key: 0, value: 'Idle' },
      { key: 1, value: 'Charging' },
      { key: 2, value: 'Discharging' },
      { key: 3, value: 'Full' },
      { key: 65535, value: 'N/A' },
    ],
    homeyCapability: null,
  },

  // -- Grid -------------------------------------------------------------------

  // Voltage / frequency -- Block 0x0256-0x027C
  {
    name: 'Grid Voltage L1',
    rule: 1,
    registers: [0x0256],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.l1',
  },
  {
    name: 'Grid Voltage L2',
    rule: 1,
    registers: [0x0257],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.l2',
  },
  {
    name: 'Grid Voltage L3',
    rule: 1,
    registers: [0x0258],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.l3',
  },
  {
    name: 'Grid Frequency',
    rule: 1,
    registers: [0x0261],
    scale: 0.01,
    uom: 'Hz',
    homeyCapability: 'measure_frequency',
  },
  {
    // positive = import, negative = export
    name: 'Total Grid Power',
    rule: 2,
    registers: [0x0271],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.grid',
  },

  // Internal CT per phase -- signed (rule 2)
  {
    name: 'Internal CT L1 Power',
    rule: 2,
    registers: [0x025C],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.ct_int_l1',
  },
  {
    name: 'Internal CT L2 Power',
    rule: 2,
    registers: [0x025D],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.ct_int_l2',
  },
  {
    name: 'Internal CT L3 Power',
    rule: 2,
    registers: [0x025E],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.ct_int_l3',
  },

  // External CT per phase -- signed (rule 2)
  {
    name: 'External CT L1 Power',
    rule: 2,
    registers: [0x0268],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.ct_ext_l1',
  },
  {
    name: 'External CT L2 Power',
    rule: 2,
    registers: [0x0269],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.ct_ext_l2',
  },
  {
    name: 'External CT L3 Power',
    rule: 2,
    registers: [0x026A],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.ct_ext_l3',
  },

  // Inverter output current & power per phase
  {
    name: 'Current L1',
    rule: 2,
    registers: [0x0276],
    scale: 0.01,
    uom: 'A',
    homeyCapability: 'measure_current.l1',
  },
  {
    name: 'Current L2',
    rule: 2,
    registers: [0x0277],
    scale: 0.01,
    uom: 'A',
    homeyCapability: 'measure_current.l2',
  },
  {
    name: 'Current L3',
    rule: 2,
    registers: [0x0278],
    scale: 0.01,
    uom: 'A',
    homeyCapability: 'measure_current.l3',
  },
  {
    name: 'Inverter L1 Power',
    rule: 2,
    registers: [0x0279],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.inv_l1',
  },
  {
    name: 'Inverter L2 Power',
    rule: 2,
    registers: [0x027A],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.inv_l2',
  },
  {
    name: 'Inverter L3 Power',
    rule: 2,
    registers: [0x027B],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.inv_l3',
  },
  {
    // Derived: sum of the three inverter phase outputs.
    // The SG04LP3 has no dedicated total-AC-output register -- this is the
    // correct way to get total production for Homey Energy.
    name: 'Total AC Output Power',
    rule: 'sum',
    sources: ['Inverter L1 Power', 'Inverter L2 Power', 'Inverter L3 Power'],
    uom: 'W',
    homeyCapability: 'measure_power',
  },

  // Grid energy counters -- Block 0x0202-0x022E
  {
    name: 'Daily Energy Bought',
    rule: 1,
    registers: [0x0208],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.grid_imported_today',
  },
  {
    name: 'Total Energy Bought',
    rule: 3,
    registers: [0x020A, 0x020B],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.grid_imported',
  },
  {
    name: 'Daily Energy Sold',
    rule: 1,
    registers: [0x0209],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.grid_exported_today',
  },
  {
    name: 'Total Energy Sold',
    rule: 3,
    registers: [0x020C, 0x020D],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.grid_exported',
  },

  // -- Load (Block 0x0284-0x028D) ---------------------------------------------
  // Load L1/L2/L3 Power: rule 1 (unsigned) -- new register block from Mathajas
  // PR #739. These always return positive load values, avoiding the 65kW
  // overflow bug present in the old 0x0168-0x016A block (issue #685).
  {
    name: 'Load Voltage L1',
    rule: 1,
    registers: [0x0284],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.load_l1',
  },
  {
    name: 'Load Voltage L2',
    rule: 1,
    registers: [0x0285],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.load_l2',
  },
  {
    name: 'Load Voltage L3',
    rule: 1,
    registers: [0x0286],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.load_l3',
  },
  {
    name: 'Load L1 Power',
    rule: 1,
    registers: [0x028A],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.load_l1',
  },
  {
    name: 'Load L2 Power',
    rule: 1,
    registers: [0x028B],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.load_l2',
  },
  {
    name: 'Load L3 Power',
    rule: 1,
    registers: [0x028C],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.load_l3',
  },
  {
    name: 'Total Load Power',
    rule: 1,
    registers: [0x028D],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.load',
  },

  // Load energy counters -- Block 0x0202-0x022E
  {
    name: 'Daily Load Consumption',
    rule: 1,
    registers: [0x020E],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.load_today',
  },
  {
    name: 'Total Load Consumption',
    rule: 3,
    registers: [0x020F, 0x0210],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.load_total',
  },

  // -- Inverter / temperature -------------------------------------------------

  // Block 0x0202-0x022E
  {
    // (raw - 1000) * 0.1
    name: 'DC Temperature',
    rule: 2,
    registers: [0x021C],
    offset: 1000,
    scale: 0.1,
    uom: ' degC',
    homeyCapability: 'measure_temperature',
  },
  {
    name: 'AC Temperature',
    rule: 2,
    registers: [0x021D],
    offset: 1000,
    scale: 0.1,
    uom: ' degC',
    homeyCapability: 'measure_temperature.ac',
  },
  {
    name: 'Inverter Run Time',
    rule: 3,
    registers: [0x0218, 0x0219],
    scale: 1,
    uom: 'h',
    homeyCapability: null,
  },

  // -- Identification -- Block 0x0003-0x0059 ----------------------------------
  {
    name: 'Inverter ID',
    rule: 5,
    registers: [0x0003, 0x0004, 0x0005, 0x0006, 0x0007],
    homeyCapability: null,
  },
  {
    name: 'Communication Board Version',
    rule: 1,
    registers: [0x0011],
    homeyCapability: null,
  },
  {
    name: 'Control Board Version',
    rule: 1,
    registers: [0x000D],
    homeyCapability: null,
  },

  // -- System status ----------------------------------------------------------
  {
    name: 'Inverter Mode',
    rule: 1,
    registers: [0x0055],
    lookup: [
      { key: 0, value: 'Standby' },
      { key: 1, value: 'Normal (On-Grid)' },
      { key: 2, value: 'Fault' },
      { key: 3, value: 'Flash Update' },
    ],
    homeyCapability: 'alarm_generic',
  },
  {
    name: 'MPPT1 Status',
    rule: 1,
    registers: [0x0056],
    lookup: [
      { key: 0, value: 'Not Connected' },
      { key: 1, value: 'Connected' },
      { key: 2, value: 'Producing' },
      { key: 65535, value: 'N/A' },
    ],
    homeyCapability: null,
  },
  {
    name: 'MPPT2 Status',
    rule: 1,
    registers: [0x0057],
    lookup: [
      { key: 0, value: 'Not Connected' },
      { key: 1, value: 'Connected' },
      { key: 2, value: 'Producing' },
      { key: 65535, value: 'N/A' },
    ],
    homeyCapability: null,
  },
  {
    name: 'Grid Synchronization',
    rule: 1,
    registers: [0x0059],
    lookup: [
      { key: 0, value: 'Not Synchronized' },
      { key: 1, value: 'Synchronized' },
    ],
    homeyCapability: null,
  },

  // -- Export / power control -- Block 0x0080-0x0085 --------------------------
  {
    name: 'Export Control Limit',
    rule: 1,
    registers: [0x0081],
    scale: 1,
    uom: '%',
    homeyCapability: null,
  },
  {
    name: 'Export Control Mode',
    rule: 1,
    registers: [0x0082],
    lookup: [
      { key: 0, value: 'Off' },
      { key: 1, value: 'Enabled' },
    ],
    homeyCapability: null,
  },
  {
    name: 'PQ Mode Status',
    rule: 1,
    registers: [0x0083],
    lookup: [
      { key: 0, value: 'Disabled' },
      { key: 1, value: 'Enabled' },
    ],
    homeyCapability: null,
  },
  {
    name: 'V(Q) Control Status',
    rule: 1,
    registers: [0x0084],
    lookup: [
      { key: 0, value: 'Disabled' },
      { key: 1, value: 'Enabled' },
    ],
    homeyCapability: null,
  },
  {
    name: 'F(W) Control Status',
    rule: 1,
    registers: [0x0085],
    lookup: [
      { key: 0, value: 'Disabled' },
      { key: 1, value: 'Enabled' },
    ],
    homeyCapability: null,
  },

  // -- SmartLoad / Generator --------------------------------------------------
  {
    name: 'SmartLoad Enable Status',
    rule: 1,
    registers: [0x0085],
    lookup: [
      { key: 0, value: 'GEN Use' },
      { key: 1, value: 'SMART Load output' },
      { key: 2, value: 'Microinverter' },
    ],
    homeyCapability: null,
  },
  {
    name: 'Phase voltage of Gen port A',
    rule: 1,
    registers: [0x0295],
    scale: 0.1,
    uom: 'V',
    homeyCapability: null,
  },
  {
    name: 'Phase voltage of Gen port B',
    rule: 1,
    registers: [0x0296],
    scale: 0.1,
    uom: 'V',
    homeyCapability: null,
  },
  {
    name: 'Phase voltage of Gen port C',
    rule: 1,
    registers: [0x0297],
    scale: 0.1,
    uom: 'V',
    homeyCapability: null,
  },
  {
    name: 'Phase power of Gen port A',
    rule: 1,
    registers: [0x0298, 0x029C],
    scale: 1,
    uom: 'W',
    homeyCapability: null,
  },
  {
    name: 'Phase power of Gen port B',
    rule: 1,
    registers: [0x0299, 0x029D],
    scale: 1,
    uom: 'W',
    homeyCapability: null,
  },
  {
    name: 'Phase power of Gen port C',
    rule: 1,
    registers: [0x029A, 0x029E],
    scale: 1,
    uom: 'W',
    homeyCapability: null,
  },
  {
    name: 'Total Power of Gen port',
    rule: 1,
    registers: [0x029B, 0x029F],
    scale: 1,
    uom: 'W',
    homeyCapability: null,
  },
  {
    name: 'Generator daily power generation',
    rule: 3,
    registers: [0x0218],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: null,
  },
  {
    name: 'Generator total power generation',
    rule: 3,
    registers: [0x0219, 0x021A],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: null,
  },

  // -- Alert / fault flags -- Block 0x0202-0x022E -----------------------------
  // rule 6 = hex bit array; no capability, raw diagnostic only
  {
    name: 'Alert',
    rule: 6,
    registers: [0x0229, 0x022A, 0x022B, 0x022C, 0x022D, 0x022E],
    homeyCapability: null,
  },
];

/**
 * Modbus request blocks for DEYE_SG04LP3.
 * 8 separate address ranges -- must all be queried each polling cycle.
 * @type {Array<{start: number, end: number, mbFunctionCode: number}>}
 */
const DEYE_SG04LP3_REQUESTS = [
  { start: 0x0003, end: 0x0059, mbFunctionCode: 0x03 },
  { start: 0x0080, end: 0x0085, mbFunctionCode: 0x03 },
  { start: 0x0202, end: 0x022E, mbFunctionCode: 0x03 },
  { start: 0x024A, end: 0x024F, mbFunctionCode: 0x03 },
  { start: 0x0256, end: 0x027C, mbFunctionCode: 0x03 },
  { start: 0x0284, end: 0x028D, mbFunctionCode: 0x03 },
  { start: 0x0295, end: 0x029F, mbFunctionCode: 0x03 },
  { start: 0x02A0, end: 0x02A7, mbFunctionCode: 0x03 },
];

// Attach explicit request blocks directly to the definitions array.
// readAll() in registerParser.js checks for ._requests and uses these
// instead of auto-merging, avoiding large gaps that the inverter may reject.
DEYE_SG04LP3._requests = DEYE_SG04LP3_REQUESTS;

module.exports = { DEYE_SG04LP3, DEYE_SG04LP3_REQUESTS };
