'use strict';

const net = require('net');

/**
 * @fileoverview SolarmanV5 protocol client for Node.js.
 * Supports Modbus RTU-in-V5 and Modbus TCP-in-V5 (auto-detect).
 *
 * Solarman V5 header layout (matches pysolarmanv5):
 *  [0]   : 0xA5
 *  [1..2]: payload length (LE)
 *  [3]   : 0x10
 *  [4]   : control code (0x45 request, 0x15 response)
 *  [5..6]: sequence (LE)
 *  [7..10]: logger serial (LE)
 *
 * Payload begins at offset 11.
 * For REQUEST, payload prefix is 15 bytes then Modbus ADU.
 * For RESPONSE, payload prefix is 14 bytes then Modbus ADU.
 */

const V5_START = 0xa5;
const V5_END = 0x15;

const V5_CTRL_REQUEST = 0x4510;   // bytes: 0x10 0x45
const V5_CTRL_RESPONSE = 0x1510;  // bytes: 0x10 0x15

const MODBUS_FC_READ_HOLDING = 0x03;
const MODBUS_FC_READ_INPUT = 0x04;
const MODBUS_FC_WRITE_SINGLE = 0x06;

const DEFAULT_PORT = 8899;
const DEFAULT_SLAVE_ID = 1;
const DEFAULT_TIMEOUT_MS = 15000;

const MODBUS_TCP_PROTOCOL_ID = 0x0000;
const MODBUS_TCP_HEADER_LEN = 7;

/**
 * Calculates Modbus RTU CRC16.
 * @param {Buffer} buf
 * @returns {number}
 */
function crc16(buf) {
  let crc = 0xffff;
  for (let i = 0; i < buf.length; i++) {
    crc ^= buf[i];
    for (let j = 0; j < 8; j++) {
      if (crc & 0x0001) crc = (crc >> 1) ^ 0xa001;
      else crc >>= 1;
    }
  }
  return crc;
}

/**
 * V5 checksum = sum(frame[1..len-3]) & 0xFF.
 * @param {Buffer} frame
 * @returns {number}
 */
function v5Checksum(frame) {
  let sum = 0;
  for (let i = 1; i < frame.length - 2; i++) sum += frame[i];
  return sum & 0xff;
}

/**
 * Build Modbus RTU ADU (with CRC).
 * @param {number} slaveId
 * @param {number} fc
 * @param {number} register
 * @param {number} valueOrCount
 * @returns {Buffer}
 */
function buildModbusRtuFrame(slaveId, fc, register, valueOrCount) {
  const frame = Buffer.allocUnsafe(6);
  frame[0] = slaveId;
  frame[1] = fc;
  frame.writeUInt16BE(register, 2);
  frame.writeUInt16BE(valueOrCount, 4);

  const crc = crc16(frame);
  const result = Buffer.allocUnsafe(8);
  frame.copy(result, 0);
  result.writeUInt16LE(crc, 6);
  return result;
}

/**
 * Build Modbus TCP ADU (MBAP + PDU). No CRC in TCP.
 * @param {number} transactionId
 * @param {number} unitId
 * @param {number} fc
 * @param {number} register
 * @param {number} valueOrCount
 * @returns {Buffer}
 */
function buildModbusTcpFrame(transactionId, unitId, fc, register, valueOrCount) {
  const pdu = Buffer.allocUnsafe(5);
  pdu[0] = fc;
  pdu.writeUInt16BE(register, 1);
  pdu.writeUInt16BE(valueOrCount, 3);

  const mbap = Buffer.allocUnsafe(7);
  mbap.writeUInt16BE(transactionId & 0xffff, 0);
  mbap.writeUInt16BE(MODBUS_TCP_PROTOCOL_ID, 2);
  // length = UnitId(1) + PDU(len)
  mbap.writeUInt16BE(1 + pdu.length, 4);
  mbap[6] = unitId;

  return Buffer.concat([mbap, pdu]);
}

/**
 * Wrap Modbus ADU in V5 request frame.
 * @param {Buffer} modbusFrame
 * @param {number} loggerSerial
 * @param {number} sequence
 * @returns {Buffer}
 */
function encodeV5Frame(modbusFrame, loggerSerial, sequence) {
  const payloadLen = 15 + modbusFrame.length;
  const frameLen = 11 + payloadLen + 2;

  const buf = Buffer.alloc(frameLen, 0);
  let offset = 0;

  buf[offset++] = V5_START;
  buf.writeUInt16LE(payloadLen, offset); offset += 2;
  buf.writeUInt16LE(V5_CTRL_REQUEST, offset); offset += 2;
  buf.writeUInt16LE(sequence, offset); offset += 2;
  buf.writeUInt32LE(loggerSerial >>> 0, offset); offset += 4;

  // request prefix (15 bytes)
  buf[offset++] = 0x02; // frame type
  buf.writeUInt16LE(0x0000, offset); offset += 2; // sensor type
  buf.writeUInt32LE(0x00000000, offset); offset += 4; // total working time
  buf.writeUInt32LE(0x00000000, offset); offset += 4; // power on time
  buf.writeUInt32LE(0x00000000, offset); offset += 4; // offset time

  modbusFrame.copy(buf, offset); offset += modbusFrame.length;

  buf[offset++] = v5Checksum(buf);
  buf[offset++] = V5_END;

  return buf;
}

/**
 * Extract Modbus ADU bytes from V5 response.
 * @param {Buffer} v5Frame
 * @returns {Buffer}
 */
function decodeV5Frame(v5Frame) {
  if (v5Frame[0] !== V5_START) throw new Error('Invalid V5 start byte');
  if (v5Frame[v5Frame.length - 1] !== V5_END) throw new Error('Invalid V5 end byte');

  const ctrl = v5Frame.readUInt16LE(3);
  if (ctrl !== V5_CTRL_RESPONSE) {
    throw new Error(`Unexpected V5 control code: 0x${ctrl.toString(16)}`);
  }

  const payloadLen = v5Frame.readUInt16LE(1);

  // Response prefix is 14 bytes, Modbus starts at 11 + 14 = 25 (same as HA pysolarman)
  const modbusStart = 25;
  let modbusEnd = 11 + payloadLen;

  if (modbusEnd > v5Frame.length - 2) throw new Error('V5 payload length out of bounds');

  let modbus = v5Frame.slice(modbusStart, modbusEnd);

  // Some devices append "0000" at end; also seen "double CRC" weirdness.
  if (modbus.length >= 2 && modbus[modbus.length - 2] === 0x00 && modbus[modbus.length - 1] === 0x00) {
    modbus = modbus.slice(0, -2);
  }

  return modbus;
}

/**
 * Detect if buffer looks like Modbus TCP ADU (MBAP header).
 * @param {Buffer} frame
 * @returns {boolean}
 */
function looksLikeModbusTcp(frame) {
  if (frame.length < MODBUS_TCP_HEADER_LEN + 2) return false;
  const protocolId = frame.readUInt16BE(2);
  const len = frame.readUInt16BE(4);
  // Basic sanity: protocol id must be 0, length must fit remaining bytes
  if (protocolId !== 0x0000) return false;
  if (len < 2) return false; // at least unit + fc
  if (MODBUS_TCP_HEADER_LEN + len > frame.length + 2) {
    // allow small truncation, but should not be wildly off
    // We'll still treat as TCP if protocolId is correct.
  }
  return true;
}

/**
 * Parse registers from either Modbus RTU or Modbus TCP response.
 * @param {Buffer} adu
 * @param {number} expectedFc
 * @returns {number[]}
 */
function parseRegistersAuto(adu, expectedFc) {
  // Modbus TCP path
  if (looksLikeModbusTcp(adu)) {
    const unitId = adu[6];
    const fc = adu[7];

    if (fc & 0x80) throw new Error(`Modbus TCP exception code: ${adu[8]}`);
    if (fc !== expectedFc) throw new Error(`Unexpected Modbus TCP FC: expected ${expectedFc}, got ${fc}`);

    const byteCount = adu[8];
    const values = [];
    const start = 9;
    for (let i = 0; i < byteCount; i += 2) {
      values.push(adu.readUInt16BE(start + i));
    }
    // unitId not used now, but kept for debugging
    void unitId;
    return values;
  }

  // Modbus RTU path
  if (adu.length < 5) throw new Error('Invalid Modbus RTU frame (too short)');

  const fc = adu[1];
  if (fc & 0x80) throw new Error(`Modbus RTU exception code: ${adu[2]}`);
  if (fc !== expectedFc) throw new Error(`Unexpected Modbus RTU FC: expected ${expectedFc}, got ${fc}`);

  const byteCount = adu[2];
  const values = [];
  for (let i = 0; i < byteCount; i += 2) {
    values.push(adu.readUInt16BE(3 + i));
  }
  return values;
}

class SolarmanV5Client {
  /**
   * @param {string} host
   * @param {number} loggerSerial
   * @param {object} [options]
   * @param {number} [options.port=8899]
   * @param {number} [options.slaveId=1]
   * @param {number} [options.timeoutMs=15000]
   */
  constructor(host, loggerSerial, options = {}) {
    this.host = host;
    this.loggerSerial = loggerSerial >>> 0;
    this.port = options.port ?? DEFAULT_PORT;
    this.slaveId = options.slaveId ?? DEFAULT_SLAVE_ID;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

    this._sequence = Math.floor(Math.random() * 0xffff);
    this._socket = null;

    /** @type {'rtu'|'tcp'} */
    this._transport = 'rtu';

    /** @type {number} */
    this._txId = Math.floor(Math.random() * 0xffff);

    // Allow injecting a custom setTimeout (e.g. homey.setTimeout in Homey SDK).
    // Must return an object with a cancel() method.
    const rawFn = options.setTimeout ?? setTimeout;
    const clearFn = options.clearTimeout ?? clearTimeout;
    this._timeoutFn = (ms, cb) => {
      const id = rawFn(cb, ms);
      return { cancel: () => clearFn(id) };
    };
  }

  _nextSequence() {
    this._sequence = (this._sequence + 1) & 0xffff;
    return this._sequence;
  }

  _nextTxId() {
    this._txId = (this._txId + 1) & 0xffff;
    return this._txId;
  }

  async connect() {
    // Always create a fresh socket — logger accepts only one connection at a time
    if (this._socket) { this._socket.destroy(); this._socket = null; }

    return new Promise((resolve, reject) => {
      const sock = new net.Socket();

      const timer = setTimeout(() => {
        sock.destroy();
        reject(new Error(`Connection timeout to ${this.host}:${this.port}`));
      }, this.timeoutMs);

      sock.once('connect', () => {
        clearTimeout(timer);
        this._socket = sock;
        resolve();
      });

      sock.once('error', (err) => {
        clearTimeout(timer);
        sock.destroy();
        reject(err);
      });

      sock.connect(this.port, this.host);
    });
  }

  disconnect() {
    if (this._socket) {
      this._socket.destroy();
      this._socket = null;
    }
  }

  async _sendReceive(v5Request) {
    await this.connect();

    return new Promise((resolve, reject) => {
      const chunks = [];
      let expectedLen = null;

      const timer = this._timeoutFn(this.timeoutMs, () => {
        cleanup();
        this.disconnect();
        reject(new Error(`Response timeout after ${this.timeoutMs}ms`));
      });

      const onData = (chunk) => {
        chunks.push(chunk);
        const buf = Buffer.concat(chunks);

        if (expectedLen === null && buf.length >= 3) {
          const payloadLen = buf.readUInt16LE(1);
          expectedLen = 11 + payloadLen + 2;
        }

        if (expectedLen !== null && buf.length >= expectedLen) {
          cleanup();
          resolve(buf.slice(0, expectedLen));
        }
      };

      const onError = (err) => { cleanup(); reject(err); };
      const onClose = () => { cleanup(); reject(new Error('Socket closed before response')); };

      const cleanup = () => {
        timer.cancel();
        this._socket?.removeListener('data', onData);
        this._socket?.removeListener('error', onError);
        this._socket?.removeListener('close', onClose);
      };

      this._socket.on('data', onData);
      this._socket.once('error', onError);
      this._socket.once('close', onClose);

      this._socket.write(v5Request);
    });
  }

  /**
   * Build Modbus request (RTU or TCP) based on current transport.
   * @param {number} fc
   * @param {number} register
   * @param {number} countOrValue
   * @returns {Buffer}
   */
  _buildModbusRequest(fc, register, countOrValue) {
    if (this._transport === 'tcp') {
      return buildModbusTcpFrame(this._nextTxId(), this.slaveId, fc, register, countOrValue);
    }
    return buildModbusRtuFrame(this.slaveId, fc, register, countOrValue);
  }

  async _readRegisters(fc, register, count) {
    const modbusReq = this._buildModbusRequest(fc, register, count);
    const v5Req = encodeV5Frame(modbusReq, this.loggerSerial, this._nextSequence());

    const v5Resp = await this._sendReceive(v5Req);
    const adu = decodeV5Frame(v5Resp);

    try {
      const values = parseRegistersAuto(adu, fc);

      // Auto-switch to TCP if response looked like TCP but we were on RTU
      if (this._transport === 'rtu' && looksLikeModbusTcp(adu)) {
        this._transport = 'tcp';
      }

      return values;
    } catch (e) {
      // If we were on RTU and parsing indicates TCP-ish, switch and retry once.
      if (this._transport === 'rtu' && looksLikeModbusTcp(adu)) {
        this._transport = 'tcp';
        return this._readRegisters(fc, register, count);
      }
      throw e;
    }
  }

  async readHoldingRegisters(register, count) {
    return this._readRegisters(MODBUS_FC_READ_HOLDING, register, count);
  }

  async readInputRegisters(register, count) {
    return this._readRegisters(MODBUS_FC_READ_INPUT, register, count);
  }

  async writeSingleRegister(register, value) {
    const modbusReq = this._buildModbusRequest(MODBUS_FC_WRITE_SINGLE, register, value);
    const v5Req = encodeV5Frame(modbusReq, this.loggerSerial, this._nextSequence());
    const v5Resp = await this._sendReceive(v5Req);
    const adu = decodeV5Frame(v5Resp);

    // Accept either RTU or TCP response
    if (looksLikeModbusTcp(adu)) {
      const fc = adu[7];
      if (fc & 0x80) throw new Error(`Modbus TCP write exception code: ${adu[8]}`);
      if (fc !== MODBUS_FC_WRITE_SINGLE) throw new Error(`Unexpected Modbus TCP FC: ${fc}`);
      return;
    }

    const fc = adu[1];
    if (fc & 0x80) throw new Error(`Modbus RTU write exception code: ${adu[2]}`);
    if (fc !== MODBUS_FC_WRITE_SINGLE) throw new Error(`Unexpected Modbus RTU FC: ${fc}`);
  }
}

module.exports = { SolarmanV5Client };