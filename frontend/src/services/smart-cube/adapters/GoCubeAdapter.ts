/**
 * services/smart-cube/adapters/GoCubeAdapter.ts ── GoCube / Rubik's Connected
 *
 * 协议来源: cstimer/src/js/hardware/gocube.js
 *  - 标准 Nordic UART (6e400001-b5a3-f393-e0a9-e50e24dcca9e)
 *    - chrct 6e400002 = write
 *    - chrct 6e400003 = read (notify)
 *  - 帧格式: 头 0x2a, 尾 0x0d 0x0a, msgType 在第 2 字节
 *    - 0x01: move (每 2 字节: axis + power)
 *    - 0x02: cube state (54 字节 facelet)
 *    - 0x03: quaternion
 *    - 0x05: battery level
 *    - 0x07: offline stats
 *    - 0x08: cube type
 *  - axis 转换: axisPerm = [5, 2, 0, 3, 1, 4] (cube xyz -> WCA URFDLB)
 *  - power: [0, 2] 奇数=顺, 偶数=逆 (90° 增量)
 *  - face perm/offset 用于解 54 字符 (顺序: URF DLF / BUD)
 */
import { BaseAdapter } from './BaseAdapter'
import type { CubeBrand } from '../types'
import { autoRegister } from '../CubeDeviceManager'

const UUID_SUFFIX = '-b5a3-f393-e0a9-e50e24dcca9e'
const SERVICE_UUID = `6e400001${UUID_SUFFIX}`
const CHRCT_UUID_WRITE = `6e400002${UUID_SUFFIX}`
const CHRCT_UUID_READ = `6e400003${UUID_SUFFIX}`

const WRITE_BATTERY = 50
const WRITE_STATE = 51

// 字节 -> WCA 面 + 方向
const AXIS_PERM = [5, 2, 0, 3, 1, 4]  // cube xyz -> WCA URFDLB
const FACE_PERM = [0, 1, 2, 5, 8, 7, 6, 3]  // 8 周边块位置映射
const FACE_OFFSET = [0, 0, 6, 2, 0, 0]  // 每个面的起始 offset

const GOCUBE_NAME_PREFIXES = ['GoCube', 'Rubiks', 'Rubik'] as const

// 解码 move 字节: (b >> 1) = axis, (b & 1) = power(0/1 -> 0/2)
function decodeGoCubeMoveByte(b: number): string | null {
  if (b < 0 || b > 11) return null
  const axis = AXIS_PERM[b >> 1]
  const pow = [0, 2][b & 1]
  const face = 'URFDLB'[axis]
  const suf = pow === 2 ? '2' : ''
  return face + suf
}

// 解码 54 字节 facelet
function decodeGoCubeFacelet(msg: Uint8Array, startIdx: number): string {
  // msg[startIdx..startIdx+54] 按 6 面展开, 每面 9 字节
  // facePerm 把 byte 顺序转成 WCA 3x3 顺序
  const facelet: string[] = new Array(54).fill('?')
  // 面颜色字符 (按 cstimer 顺序: BFUDRL)
  const faceColors = 'BFUDRL'
  for (let a = 0; a < 6; a++) {
    const axis = AXIS_PERM[a] * 9
    const aoff = FACE_OFFSET[a]
    // 中心 (4)
    facelet[axis + 4] = faceColors[msg[startIdx + a * 9]]
    // 8 周边
    for (let i = 0; i < 8; i++) {
      facelet[axis + FACE_PERM[(i + aoff) % 8]] = faceColors[msg[startIdx + a * 9 + i + 1]]
    }
  }
  return facelet.join('')
}

export class GoCubeAdapter extends BaseAdapter {
  private readChr: BluetoothRemoteGATTCharacteristic | null = null
  private writeChr: BluetoothRemoteGATTCharacteristic | null = null
  private curFacelet = 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB'
  private curFaceletDecoded = false
  private batteryLevel = 100

  constructor(ctx: any) {
    super(ctx, 'GoCube' as CubeBrand, {
      brand: 'GoCube',
      name: ctx.device.name ?? 'GoCube',
    })
  }

  override async connect(): Promise<void> {
    if (!this.device.gatt) throw new Error('GoCube: device.gatt 不可用')
    const server = await this.device.gatt.connect()
    const svc = await server.getPrimaryService(SERVICE_UUID)
    this.writeChr = await svc.getCharacteristic(CHRCT_UUID_WRITE)
    this.readChr = await svc.getCharacteristic(CHRCT_UUID_READ)
    this.readChr.addEventListener('characteristicvaluechanged', (e: any) => {
      const v = e.target.value as DataView
      this.handlePacket(v)
    })
    await this.readChr.startNotifications()
    // 主动请求 cube state
    await this.writeChr.writeValue(new Uint8Array([WRITE_STATE]))
  }

  private handlePacket(value: DataView): void {
    const len = value.byteLength
    if (len < 4) return
    if (value.getUint8(0) !== 0x2a || value.getUint8(len - 2) !== 0x0d || value.getUint8(len - 1) !== 0x0a) {
      return
    }
    const msgType = value.getUint8(2)
    const msgLen = len - 6
    if (msgType === 1) {
      // move: 每 2 字节一个
      const moves: string[] = []
      for (let i = 0; i < msgLen; i += 2) {
        const m = decodeGoCubeMoveByte(value.getUint8(3 + i))
        if (m) {
          moves.push(m)
          this.emitter.emit('move', { move: m, timestamp: Date.now() })
        }
      }
    } else if (msgType === 2) {
      // cube state: 54 字节
      const arr = new Uint8Array(len)
      for (let i = 0; i < len; i++) arr[i] = value.getUint8(i)
      this.curFacelet = decodeGoCubeFacelet(arr, 3)
      this.curFaceletDecoded = true
      this.emitter.emit('facelet', this.curFacelet)
    } else if (msgType === 5) {
      // battery level
      this.batteryLevel = value.getUint8(3)
      this.emitter.emit('battery', { level: this.batteryLevel })
    }
    // msgType 3 = quaternion, 7/8 = stats (暂时忽略)
  }

  override async getBattery(): Promise<number> {
    if (!this.writeChr) return 100
    try {
      await this.writeChr.writeValue(new Uint8Array([WRITE_BATTERY]))
    } catch {}
    return this.batteryLevel
  }

  override async getFacelet(): Promise<string> {
    // 主动请求 cube state, 然后等回调更新
    if (this.writeChr) {
      try { await this.writeChr.writeValue(new Uint8Array([WRITE_STATE])) } catch {}
    }
    return this.curFacelet
  }
}

autoRegister({
  brand: 'GoCube' as CubeBrand,
  cubeType: '3x3',
  namePrefixes: [...GOCUBE_NAME_PREFIXES],
  gattServiceUuids: [SERVICE_UUID],
  detect: (device) => GOCUBE_NAME_PREFIXES.some(p => device.name?.startsWith(p)),
  factory: (ctx) => new GoCubeAdapter(ctx),
})
