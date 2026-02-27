'use strict';

const DeyeDevice = require('../../lib/DeyeDevice');
const { DEYE_STRING_2MPPT } = require('../../lib/deyeRegisters');

/**
 * Deye String Inverter — 2 MPPT inputs (PV1 + PV2).
 * Extends the shared DeyeDevice with the 2-string register profile.
 */
class DeyeString2MpptDevice extends DeyeDevice {

  async onInit() {
    this._definitions = DEYE_STRING_2MPPT;
    await super.onInit();
  }
}

module.exports = DeyeString2MpptDevice;
