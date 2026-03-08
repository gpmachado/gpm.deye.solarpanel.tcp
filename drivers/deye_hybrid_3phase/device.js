'use strict';

const DeyeDevice = require('../../lib/DeyeDevice');
const { DEYE_SG04LP3 } = require('../../lib/deyeSG04LP3Registers');

/**
 * Deye Hybrid 3-phase -- SUN-8/10/12K-SG04LP3-EU
 * Low voltage battery, 2x MPPT, 3-phase grid.
 */
class DeyeHybrid3PhaseDevice extends DeyeDevice {

  async onInit() {
    this._definitions = DEYE_SG04LP3;
    await super.onInit();
  }

}

module.exports = DeyeHybrid3PhaseDevice;
