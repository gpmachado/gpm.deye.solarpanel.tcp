'use strict';

const DeyeDevice = require('../../lib/DeyeDevice');
const { DEYE_STRING_4MPPT } = require('../../lib/deyeRegisters');

/**
 * Deye String Inverter — 4 MPPT inputs (PV1–PV4).
 * Extends the shared DeyeDevice with the 4-string register profile.
 */
class DeyeString4MpptDevice extends DeyeDevice {

  async onInit() {
    this._definitions = DEYE_STRING_4MPPT;
    await super.onInit();
  }
}

module.exports = DeyeString4MpptDevice;
