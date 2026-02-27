'use strict';

/**
 * @fileoverview Deye inverter register definitions.
 *
 * Profiles exported:
 *   DEYE_STRING_2MPPT – G0* String Inverter, 2 active PV strings
 *   DEYE_STRING_4MPPT – G0* String Inverter, 4 active PV strings
 *   DEYE_HYBRID       – SG0xLP1 / SG0xHP single-phase hybrid with battery
 *
 * Rule reference (identical to ha-solarman parser.py):
 *   1 | 3 = unsigned, N registers accumulated lo-first
 *   2 | 4 = signed,   N registers accumulated lo-first, then sign-extended
 *   5     = ASCII string (chr(hi) + chr(lo) per register)
 *
 * offset/scale formula:
 *   decoded = (raw - offset) * scale
 */

/**
 * @typedef {import('./registerParser').RegisterDefinition} RegisterDefinition
 */

/**
 * Shared registers present on all string inverter profiles.
 *
 * @type {RegisterDefinition[]}
 */
const STRING_BASE = [

  {
    name: 'Device Serial',
    rule: 5,
    registers: [0x0003, 0x0004, 0x0005, 0x0006, 0x0007],
    homeyCapability: null,
  },
  {
    name: 'Device State',
    rule: 1,
    registers: [0x003B],
    lookup: [
      { key: 0x0000, value: 'Standby' },
      { key: 0x0001, value: 'Self-test' },
      { key: 0x0002, value: 'Normal' },
      { key: 0x0003, value: 'Alarm' },
      { key: 0x0004, value: 'Fault' },
    ],
    homeyCapability: 'alarm_generic',
  },
  {
    name: 'Today Production',
    rule: 1,
    registers: [0x003C],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.today',
  },
  {
    name: 'Total Production',
    rule: 3,
    registers: [0x003F, 0x0040],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power',
  },
  {
    name: 'Grid L1 Voltage',
    rule: 1,
    registers: [0x0049],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.grid',
  },
  {
    name: 'Grid L1 Current',
    rule: 2,
    registers: [0x004C],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.grid',
  },
  {
    name: 'Grid Frequency',
    rule: 1,
    registers: [0x004F],
    scale: 0.01,
    uom: 'Hz',
    homeyCapability: 'measure_frequency',
  },
  {
    name: 'Output AC Power',
    rule: 3,
    registers: [0x0050, 0x0051],
    scale: 0.1,
    uom: 'W',
    homeyCapability: 'measure_power',
  },
  {
    // Formula: (s16(raw) - 1000) * 0.1
    // 0x005A = DC/MPPT temperature (active on string inverters)
    // 0x005B = AC temperature (reads 0 on string models, omitted)
    name: 'Temperature',
    rule: 2,
    registers: [0x005A],
    offset: 1000,
    scale: 0.1,
    uom: '°C',
    homeyCapability: 'measure_temperature',
  },
  {
    name: 'PV1 Voltage',
    rule: 1,
    registers: [0x006D],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.pv1',
  },
  {
    name: 'PV1 Current',
    rule: 1,
    registers: [0x006E],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.pv1',
  },
  {
    name: 'PV2 Voltage',
    rule: 1,
    registers: [0x006F],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.pv2',
  },
  {
    name: 'PV2 Current',
    rule: 1,
    registers: [0x0070],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.pv2',
  },
];

/** @type {RegisterDefinition[]} */
const DEYE_STRING_2MPPT = STRING_BASE;

/** @type {RegisterDefinition[]} */
const DEYE_STRING_4MPPT = [
  ...STRING_BASE,
  {
    name: 'PV3 Voltage',
    rule: 1,
    registers: [0x0071],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.pv3',
  },
  {
    name: 'PV3 Current',
    rule: 1,
    registers: [0x0072],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.pv3',
  },
  {
    name: 'PV4 Voltage',
    rule: 1,
    registers: [0x0073],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.pv4',
  },
  {
    name: 'PV4 Current',
    rule: 1,
    registers: [0x0074],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.pv4',
  },
];

/** @type {RegisterDefinition[]} */
const DEYE_HYBRID = [

  {
    name: 'Device Serial',
    rule: 5,
    registers: [0x0003, 0x0004, 0x0005, 0x0006, 0x0007],
    homeyCapability: null,
  },
  {
    name: 'Device State',
    rule: 1,
    registers: [0x003B],
    lookup: [
      { key: 0x0000, value: 'Standby' },
      { key: 0x0001, value: 'Self-test' },
      { key: 0x0002, value: 'Normal' },
      { key: 0x0003, value: 'Alarm' },
      { key: 0x0004, value: 'Fault' },
    ],
    homeyCapability: null,
  },
  {
    name: 'Today Production',
    rule: 1,
    registers: [0x006C],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.today',
  },
  {
    name: 'Total Production',
    rule: 3,
    registers: [0x0060, 0x0061],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power',
  },
  {
    name: 'Grid Frequency',
    rule: 1,
    registers: [0x004F],
    scale: 0.01,
    uom: 'Hz',
    homeyCapability: 'measure_frequency',
  },
  {
    name: 'Grid Voltage',
    rule: 1,
    registers: [0x0096],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.grid',
  },
  {
    name: 'Grid Power',
    rule: 2,
    registers: [0x00A9],
    scale: 10,
    uom: 'W',
    homeyCapability: 'measure_power.grid',
  },
  {
    name: 'Load Power',
    rule: 2,
    registers: [0x00B2],
    scale: 10,
    uom: 'W',
    homeyCapability: 'measure_power.load',
  },
  {
    name: 'DC Temperature',
    rule: 2,
    registers: [0x005A],
    offset: 1000,
    scale: 0.1,
    uom: '°C',
    homeyCapability: 'measure_temperature',
  },
  {
    name: 'AC Temperature',
    rule: 2,
    registers: [0x005B],
    offset: 1000,
    scale: 0.1,
    uom: '°C',
    homeyCapability: 'measure_temperature.ac',
  },
  {
    name: 'PV1 Voltage',
    rule: 1,
    registers: [0x006D],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.pv1',
  },
  {
    name: 'PV1 Current',
    rule: 1,
    registers: [0x006E],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.pv1',
  },
  {
    name: 'PV2 Voltage',
    rule: 1,
    registers: [0x006F],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.pv2',
  },
  {
    name: 'PV2 Current',
    rule: 1,
    registers: [0x0070],
    scale: 0.1,
    uom: 'A',
    homeyCapability: 'measure_current.pv2',
  },
  {
    name: 'Battery SOC',
    rule: 1,
    registers: [0x00B8],
    scale: 1,
    uom: '%',
    homeyCapability: 'measure_battery',
  },
  {
    name: 'Battery Voltage',
    rule: 1,
    registers: [0x00B7],
    scale: 0.01,
    uom: 'V',
    homeyCapability: 'measure_voltage.battery',
  },
  {
    name: 'Battery Power',
    rule: 2,
    registers: [0x00BE],
    scale: 1,
    uom: 'W',
    homeyCapability: 'measure_power.battery',
  },
  {
    name: 'Battery Temperature',
    rule: 2,
    registers: [0x00B6],
    offset: 1000,
    scale: 0.1,
    uom: '°C',
    homeyCapability: 'measure_temperature.battery',
  },
];

module.exports = { DEYE_STRING_2MPPT, DEYE_STRING_4MPPT, DEYE_HYBRID };
