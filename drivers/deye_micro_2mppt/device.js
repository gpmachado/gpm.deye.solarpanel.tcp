'use strict';

const DeyeDevice = require('../../lib/DeyeDevice');
const { DEYE_MICRO_2MPPT } = require('../../lib/deyeMicroRegisters');

/**
 * Deye Microinverter -- 2 MPPT (SUN600G3 / SUN800G3 / SUN1000G3).
 */
class DeyeMicro2MpptDevice extends DeyeDevice {

  async onInit() {
    this._definitions = DEYE_MICRO_2MPPT;
    await super.onInit();
  }

}

module.exports = DeyeMicro2MpptDevice;
