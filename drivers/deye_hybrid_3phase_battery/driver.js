'use strict';

const { Driver } = require('homey');

/**
 * Driver for the battery sub-device of the Deye SG04LP3 hybrid inverter.
 *
 * This device is NOT paired directly by the user. It is created automatically
 * by DeyeHybrid3PhaseDriver during the solar inverter pairing flow.
 * No onPair() handler is needed here.
 */
class DeyeHybrid3PhaseBatteryDriver extends Driver {

  async onInit() {
    this.log('DeyeHybrid3PhaseBatteryDriver init');
  }

}

module.exports = DeyeHybrid3PhaseBatteryDriver;
