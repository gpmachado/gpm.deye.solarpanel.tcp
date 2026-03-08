'use strict';

/**
 * @fileoverview Register definitions for Deye Microinverters.
 *
 * Kept intentionally separate from deyeRegisters.js so that the
 * existing string/hybrid profiles are never touched.
 *
 * Profiles exported:
 *   DEYE_MICRO_2MPPT - SUN600G3 / SUN800G3 / SUN1000G3 / SUN-M80G3-EU-Q0
 *                      2x MPPT, 2x inverter channel, 2 modules
 *
 *   DEYE_MICRO_4MPPT - SUN2000G3 / SUN-M160G4-EU-Q0
 *                      4x MPPT, 4x inverter channel, 4 modules
 *
 * Source: ha-solarman deye_2mppt.yaml / deye_4mppt.yaml (MIT)
 * Register request range: 0x0001-0x007D, Modbus FC 0x03
 *
 * Rule reference (same as deyeRegisters.js / registerParser.js):
 *   1 | 3 = unsigned, N registers accumulated lo-first
 *   2 | 4 = signed,   N registers accumulated lo-first, sign-extended
 *   5     = ASCII string (chr(hi) + chr(lo) per register)
 *   7     = version nibble string
 *
 * offset/scale formula:  decoded = (raw - offset) * scale
 *
 * @typedef {import('./registerParser').RegisterDefinition} RegisterDefinition
 */

/**
 * Registers shared by both 2-MPPT and 4-MPPT microinverter variants.
 * @type {RegisterDefinition[]}
 */
const MICRO_BASE = [

  // -- Identification ------------------------------------------------------
  {
    name: 'Device Serial',
    rule: 5,
    registers: [0x0003, 0x0004, 0x0005, 0x0006, 0x0007],
    homeyCapability: null,
  },
  {
    name: 'Rated Power',
    rule: 1,
    registers: [0x0010],
    scale: 0.1,
    uom: 'W',
    homeyCapability: null,
  },

  // -- Inverter status ------------------------------------------------------
  {
    name: 'Device State',
    rule: 1,
    registers: [0x003B],
    lookup: [
      { key: 0x0000, value: 'Stand-by' },
      { key: 0x0001, value: 'Self-check' },
      { key: 0x0002, value: 'Normal' },
      { key: 0x0003, value: 'Warning' },
      { key: 0x0004, value: 'Fault' },
    ],
    homeyCapability: 'alarm_generic',
  },

  // -- Energy production ----------------------------------------------------
  {
    name: 'Today Production',
    rule: 1,
    registers: [0x003C],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power.today',
  },
  {
    // uint32 lo-first; ignore on boot if < 0.1 kWh
    name: 'Total Production',
    rule: 3,
    registers: [0x003F, 0x0040],
    scale: 0.1,
    uom: 'kWh',
    homeyCapability: 'meter_power',
    validation: { min: 0.1 },
  },

  // -- AC Grid --------------------------------------------------------------
  {
    name: 'AC Voltage',
    rule: 1,
    registers: [0x0049],
    scale: 0.1,
    uom: 'V',
    homeyCapability: 'measure_voltage.grid',
  },
  {
    name: 'Grid Current',
    rule: 2,                          // signed
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

  // -- AC Output ------------------------------------------------------------
  {
    // uint32 lo-first
    name: 'Output AC Power',
    rule: 3,
    registers: [0x0056, 0x0057],
    scale: 0.1,
    uom: 'W',
    homeyCapability: 'measure_power',
  },

  // -- Temperature ----------------------------------------------------------
  {
    // Formula: (raw - 1000) * 0.1   ->  raw 1617 = 61.7  degC
    name: 'Temperature',
    rule: 1,
    registers: [0x005A],
    offset: 1000,
    scale: 0.1,
    uom: ' degC',
    homeyCapability: 'measure_temperature',
  },

  // -- PV strings (shared: PV1 + PV2) --------------------------------------
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

/**
 * Deye Microinverter -- 2 MPPT (2 panels).
 * Models: SUN600G3, SUN800G3, SUN1000G3, SUN-M80G3-EU-Q0
 * Source: deye_2mppt.yaml (ha-solarman)
 * @type {RegisterDefinition[]}
 */
const DEYE_MICRO_2MPPT = MICRO_BASE;

/**
 * Deye Microinverter -- 4 MPPT (4 panels).
 * Models: SUN2000G3, SUN-M160G4-EU-Q0
 * Source: deye_4mppt.yaml (ha-solarman)
 *
 * Extends MICRO_BASE with PV3 / PV4 strings.
 * Register layout:
 *   PV1 V/I: 0x006D / 0x006E    PV2 V/I: 0x006F / 0x0070
 *   PV3 V/I: 0x0071 / 0x0072    PV4 V/I: 0x0073 / 0x0074
 * @type {RegisterDefinition[]}
 */
const DEYE_MICRO_4MPPT = [
  ...MICRO_BASE,
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

module.exports = { DEYE_MICRO_2MPPT, DEYE_MICRO_4MPPT };
