'use strict';

const DeyeDevice = require('../../lib/DeyeDevice');
const { DEYE_MICRO_4MPPT } = require('../../lib/deyeMicroRegisters');

/**
 * Deye Microinverter -- 4 MPPT (SUN2000G3 / SUN-M160G4-EU-Q0).
 */
class DeyeMicro4MpptDevice extends DeyeDevice {

  async onInit() {
    this._definitions = DEYE_MICRO_4MPPT;
    await super.onInit();
  }

}

module.exports = DeyeMicro4MpptDevice;
