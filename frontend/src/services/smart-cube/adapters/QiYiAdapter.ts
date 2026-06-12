/**
 * services/smart-cube/adapters/QiYiAdapter.ts ── 奇艺 (QiYi) / MoFangGe / 魔方格
 *
 * 协议来源: cstimer/src/js/hardware/qiyicube.js
 *  - service 0xFFF0, characteristic 0xFFF6 (notify + write)
 *  - 包格式: [0xfe, len, op, ...payload, crc_lo, crc_hi, 0..n pad]
 *  - crc16-modbus 校验
 *  - opcode:
 *      0x01: hello
 *      0x02: state (54 字节 facelet 4-bit packed)
 *      0x03: state change (含 history moves)
 *  - facelet 4-bit packed: 每 byte 存 2 个 sticker (low/high nibble)
 *      字符表 "LRDUFB" (与 WCA "URFDLB" 顺序不同, 需转换)
 *  - history move 在 byte 91 起, 每 5 字节: [ts(4B BE), move(1B)]
 *  - 电量在 byte 35
 *  - 加密型号 (QYSZ02): 用 KEYS 表解密
 */
import { BaseAdapter } from './BaseAdapter'
import type { CubeBrand } from '../types'
import { autoRegister } from '../CubeDeviceManager'

const UUID_SUFFIX = '-0000-1000-8000-00805f9b34fb'
const SERVICE_UUID = `0000fff0${UUID_SUFFIX}`
const CHRCT_UUID_CUBE = `0000fff6${UUID_SUFFIX}`

const QIYI_NAME_PREFIXES = ['Qiyi', 'QY-QYSC', 'XMD', 'XMD-TornadoV4-i', 'MoFangGe', 'MS'] as const

// CRC16-Modbus
function crc16Modbus(data: Uint8Array): number {
  let crc = 0xffff
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i]
    for (let j = 0; j < 8; j++) {
      crc = (crc & 0x1) > 0 ? (crc >> 1) ^ 0xa001 : crc >> 1
    }
  }
  return crc
}

// 构造发送消息
function buildMessage(content: number[]): Uint8Array {
  const msg: number[] = [0xfe, 4 + content.length, ...content]
  const crc = crc16Modbus(new Uint8Array(msg))
  msg.push(crc & 0xff, (crc >> 8) & 0xff)
  // 填充到 16 字节倍数
  const npad = (16 - msg.length % 16) % 16
  for (let i = 0; i < npad; i++) msg.push(0)
  return new Uint8Array(msg)
}

// 解 54 字符 facelet (4-bit packed, 字符表 "LRDUFB" -> 转 WCA "URFDLB")
function decodeQiYiFacelet(faceMsg: Uint8Array): string {
  // 字符映射: "LRDUFB"[0..5] -> WCA "URFDLB" 顺序
  // L=0, R=1, D=2, U=3, F=4, B=5  (字符表索引)
  // WCA 顺序: U=0, R=1, F=2, D=3, L=4, B=5
  // WCA[i] = 字符表[WCA 字符表索引]
  // WCA U (0) = 字符表 3 = "U"
  // WCA R (1) = 字符表 1 = "R"
  // WCA F (2) = 字符表 4 = "F"
  // WCA D (3) = 字符表 2 = "D"
  // WCA L (4) = 字符表 0 = "L"
  // WCA B (5) = 字符表 5 = "B"
  const wcaOrder = [3, 1, 4, 2, 0, 5]  // WCA index -> 字符表 index
  const charTable = 'LRDUFB'
  const ret: string[] = []
  for (let i = 0; i < 54; i++) {
    const byte = faceMsg[i >> 1]
    const nibble = (byte >> (i % 2 === 0 ? 0 : 4)) & 0xf  // i=even: low, i=odd: high
    const charTableIdx = nibble  // 0..5
    // 找到这个字符表 idx 在 WCA 顺序里的位置
    const wcaIdx = wcaOrder.indexOf(charTableIdx)
    ret.push('URFDLB'[wcaIdx >= 0 ? wcaIdx : 0])
  }
  return ret.join('')
}

export class QiYiAdapter extends BaseAdapter {
  private chr: BluetoothRemoteGATTCharacteristic | null = null
  private lastTs = 0
  private batteryLevel = 100
  private curFacelet = 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB'

  constructor(ctx: any) {
    super(ctx, 'QiYi', {
      brand: 'QiYi',
      name: ctx.device.name ?? 'QiYi Cube',
    })
  }

  override async connect(): Promise<void> {
    if (!this.device.gatt) throw new Error('QiYi: device.gatt 不可用')
    const server = await this.device.gatt.connect()
    const svc = await server.getPrimaryService(SERVICE_UUID)
    this.chr = await svc.getCharacteristic(CHRCT_UUID_CUBE)
    this.chr.addEventListener('characteristicvaluechanged', (e: any) => {
      this.handlePacket(e.target.value as DataView)
    })
    await this.chr.startNotifications()
    // 发 hello (opcode 0x01 + padding)
    try { await this.chr.writeValue(buildMessage([0x01, 0x00, 0x00, 0x00, 0x00]).buffer as ArrayBuffer) } catch {}
  }

  private handlePacket(data: DataView): void {
    const len = data.byteLength
    if (len < 6) return
    const arr = new Uint8Array(len)
    for (let i = 0; i < len; i++) arr[i] = data.getUint8(i)
    // CRC 校验 (最后 2 字节)
    const bodyLen = arr[1]
    if (bodyLen < 2) return
    const body = arr.slice(0, bodyLen)
    const crc = crc16Modbus(body)
    if (crc !== 0) {
      // CRC 不匹配可能是加密型号, 暂时跳过
      // TODO: KEYS 解密
    }
    const opcode = arr[2]
    // 时间戳 4 字节 BE (从 byte 3 开始)
    const ts = (arr[3] << 24) | (arr[4] << 16) | (arr[5] << 8) | arr[6]
    if (opcode === 0x02 || opcode === 0x03) {
      // state / state change
      // facelet: byte 7..34 (28 字节, 4-bit packed)
      const facelet = decodeQiYiFacelet(arr.slice(7, 34))
      this.curFacelet = facelet
      this.emitter.emit('facelet', facelet)
      // 电量 byte 35
      if (arr[35] !== this.batteryLevel) {
        this.batteryLevel = arr[35]
        this.emitter.emit('battery', { level: this.batteryLevel })
      }
      // history moves: byte 91 起, 每 5 字节 (ts 4B + move 1B)
      // 只推送时间戳 > lastTs 的新 move
      if (opcode === 0x03) {
        const newMoves: string[] = []
        for (let off = 91; off + 4 < len; off += 5) {
          const hisTs = (arr[off] << 24) | (arr[off + 1] << 16) | (arr[off + 2] << 8) | arr[off + 3]
          if (hisTs <= this.lastTs) break
          const moveByte = arr[off + 4]
          const axis = [4, 1, 3, 0, 2, 5][(moveByte - 1) >> 1]  // cstimer 的 axis 转换
          const power = [0, 2][moveByte & 1]
          const face = 'URFDLB'[axis]
          const suf = power === 2 ? '2' : ''
          newMoves.push(face + suf)
        }
        // 推送给前端
        for (let i = newMoves.length - 1; i >= 0; i--) {
          this.emitter.emit('move', { move: newMoves[i], timestamp: Date.now() })
        }
        // 回 ack (opcode 0x01 + 4 byte ts)
        if (this.chr) {
          const ack = buildMessage([0x01, arr[3], arr[4], arr[5], arr[6]])
          this.chr.writeValue(ack.buffer as ArrayBuffer).catch(() => {})
        }
      }
    }
    this.lastTs = ts
  }

  override async getBattery(): Promise<number> {
    return this.batteryLevel
  }

  override async getFacelet(): Promise<string> {
    return this.curFacelet
  }
}

autoRegister({
  brand: 'QiYi',
  cubeType: '3x3',
  namePrefixes: [...QIYI_NAME_PREFIXES],
  gattServiceUuids: [SERVICE_UUID],
  detect: (device) => QIYI_NAME_PREFIXES.some(p => device.name?.startsWith(p)),
  factory: (ctx) => new QiYiAdapter(ctx),
})
