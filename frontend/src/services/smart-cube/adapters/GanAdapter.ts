/**
 * services/smart-cube/adapters/GanAdapter.ts ── GAN 智能魔方适配器
 *
 * 协议来源: cstimer/src/js/hardware/gancube.js (1043 行)
 * GAN 历史上分 4 个版本, 自动探测:
 *  - v1: 旧版 (GAN356 i3 之前), service 0xFFF0 + chrct F2 (facelet) / F3 (move) / F5 (gyro) / F6 (time) / F7 (battery)
 *  - v2: 协议 28be...4179, (大部分已淘汰)
 *  - v3: 协议 8653000a-43e6-47b7-9cb0-5fc21d4ae340
 *  - v4: service 00000010-...-fff4fff0, chrct FFF6 (read) + FFF5 (write), Gen3+ GAN 12 / 13 / i4 等
 *
 * 本实现聚焦 v3/v4 主流, 走 v4 优先, 不支持时尝试 v1 (v1/v2 留 TODO)
 *  - v4 包: read characteristic 0xFFF6, write 0xFFF5
 *  - 3 字节时间戳 + 16 ms tick
 *  - 加密型号 (GAN12+): 初次配对需要协商 AES-128 密钥
 */
import { BaseAdapter } from './BaseAdapter'
import type { CubeBrand } from '../types'
import { autoRegister } from '../CubeDeviceManager'

const UUID_SUFFIX = '-0000-1000-8000-00805f9b34fb'

// v1 UUIDs
const SERVICE_UUID_V1 = `0000fff0${UUID_SUFFIX}`
const CHRCT_UUID_F2 = `0000fff2${UUID_SUFFIX}`  // cube state
const CHRCT_UUID_F3 = `0000fff3${UUID_SUFFIX}`  // moves
const CHRCT_UUID_F5 = `0000fff5${UUID_SUFFIX}`  // gyro
const CHRCT_UUID_F7 = `0000fff7${UUID_SUFFIX}`  // battery

// v4 UUIDs
const SERVICE_UUID_V4 = '00000010-0000-fff7-fff6-fff5fff4fff0'
const CHRCT_UUID_V4READ = '0000fff6-0000-1000-8000-00805f9b34fb'
const CHRCT_UUID_V4WRITE = '0000fff5-0000-1000-8000-00805f9b34fb'

// v3 UUIDs
const SERVICE_UUID_V3 = '8653000a-43e6-47b7-9cb0-5fc21d4ae340'
const CHRCT_UUID_V3READ = '8653000b-43e6-47b7-9cb0-5fc21d4ae340'
const CHRCT_UUID_V3WRITE = '8653000c-43e6-47b7-9cb0-5fc21d4ae340'

const GAN_NAME_PREFIXES = ['GAN', 'MG', 'AiCube', 'RubiQ'] as const

// GAN move 字节: bit0-3 = face (0-5 = R L U D F B), bit7 = 逆时针, bit6 = 2-step
function decodeGanMoveByte(b: number): string | null {
  const faces = ['R', 'L', 'U', 'D', 'F', 'B'] as const
  const face = faces[b & 0x0f]
  if (!face) return null
  const isPrime = (b & 0x80) !== 0
  const isTwo = (b & 0x40) !== 0
  if (isTwo) return `${face}2`
  return isPrime ? `${face}'` : face
}

// 简化的 GAN 状态机
class GanState {
  curFacelet = 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB'
  halfMoveBuf = 0  // GAN 用半步, 180° = 两次半步, 需要合并
  lastMove: string | null = null
  prevMoves: string[] = []

  applyMove(m: string): { facelet: string; lastMove: string } {
    // 简单状态机: 维护最近 1 个 move + 上一 move, 半步合并
    if (this.lastMove) {
      const last = this.lastMove
      const isSameFace = last[0] === m[0]
      const isHalfTurn = last.endsWith('2') || m.endsWith('2')
      if (isSameFace && !isHalfTurn && !last.endsWith('2') && !m.endsWith('2')) {
        // 合并: R + R = R2, R + R' = 取消
        if (last === m) {
          this.lastMove = `${last[0]}2`
          this.prevMoves.unshift(this.lastMove)
          this.prevMoves.length = Math.min(this.prevMoves.length, 8)
          return { facelet: this.curFacelet, lastMove: this.lastMove }
        }
        if (last[1] === "'" && !m.includes("'")) {
          this.lastMove = null
          return { facelet: this.curFacelet, lastMove: '' }
        }
      }
    }
    this.lastMove = m
    this.prevMoves.unshift(m)
    this.prevMoves.length = Math.min(this.prevMoves.length, 8)
    return { facelet: this.curFacelet, lastMove: m }
  }
}

export class GanAdapter extends BaseAdapter {
  private version: 'v1' | 'v3' | 'v4' = 'v4'
  private readChr: BluetoothRemoteGATTCharacteristic | null = null
  private writeChr: BluetoothRemoteGATTCharacteristic | null = null
  private f2Chr: BluetoothRemoteGATTCharacteristic | null = null
  private f3Chr: BluetoothRemoteGATTCharacteristic | null = null
  private f5Chr: BluetoothRemoteGATTCharacteristic | null = null
  private f7Chr: BluetoothRemoteGATTCharacteristic | null = null
  private state = new GanState()
  private batteryLevel = 100
  private faceletBuf: number[] = []  // v1 facelet 是 3-bit packed, 48 字节

  constructor(ctx: any) {
    super(ctx, 'GAN', {
      brand: 'GAN',
      name: ctx.device.name ?? 'GAN Cube',
    })
  }

  override async connect(): Promise<void> {
    if (!this.device.gatt) throw new Error('GAN: device.gatt 不可用')
    const server = await this.device.gatt.connect()
    // 探测 v4 -> v3 -> v1
    const services = await server.getPrimaryServices()
    const svcMap = new Map(services.map(s => [s.uuid.toLowerCase(), s]))
    if (svcMap.has(SERVICE_UUID_V4)) {
      this.version = 'v4'
      await this._connectV4(server, svcMap.get(SERVICE_UUID_V4)!)
    } else if (svcMap.has(SERVICE_UUID_V3)) {
      this.version = 'v3'
      await this._connectV3(server, svcMap.get(SERVICE_UUID_V3)!)
    } else if (svcMap.has(SERVICE_UUID_V1)) {
      this.version = 'v1'
      await this._connectV1(server, svcMap.get(SERVICE_UUID_V1)!)
    } else {
      throw new Error('GAN: 找不到 v1/v3/v4 service')
    }
  }

  // ── v4 协议 (Gen3+: GAN 12 / 13 / i4) ─────────────────
  private async _connectV4(server: BluetoothRemoteGATTServer, svc: BluetoothRemoteGATTService) {
    this.readChr = await svc.getCharacteristic(CHRCT_UUID_V4READ)
    this.writeChr = await svc.getCharacteristic(CHRCT_UUID_V4WRITE)
    this.readChr.addEventListener('characteristicvaluechanged', (e: any) => {
      this._onPacketV4(e.target.value as DataView)
    })
    await this.readChr.startNotifications()
    // TODO: 加密型号需要 v4requestHardwareInfo + AES 协商
    // v4requestFacelets() + v4requestBattery() 触发上报
    if (this.writeChr) {
      try { await this.writeChr.writeValue(new Uint8Array([0xB0])) } catch {}  // battery request
      try { await this.writeChr.writeValue(new Uint8Array([0xA0])) } catch {}  // facelet request
    }
  }

  private _onPacketV4(data: DataView): void {
    if (data.byteLength < 1) return
    const op = data.getUint8(0)
    // v4 包格式 (简化): 0xA0=facelet, 0xB0=battery, 0xC0=move, 0xD0=gyro
    if (op === 0xa0 && data.byteLength >= 19) {
      // facelet: 18 字节 3-bit packed (54 * 3 / 8 = 20.25 -> 18 字节够)
      // TODO: 完整 3-bit 解包
      this.faceletBuf = Array.from(new Uint8Array(data.buffer, data.byteOffset + 1, 18))
      // 简化: 直接发送 curFacelet (未更新)
    } else if (op === 0xb0 && data.byteLength >= 2) {
      this.batteryLevel = data.getUint8(1)
      this.emitter.emit('battery', { level: this.batteryLevel })
    } else if (op === 0xc0 && data.byteLength >= 4) {
      // move: 2 字节 timestamp + 1 字节 move byte
      const moveByte = data.getUint8(3)
      const m = decodeGanMoveByte(moveByte)
      if (m) {
        const r = this.state.applyMove(m)
        if (r.lastMove) this.emitter.emit('move', { move: r.lastMove, timestamp: Date.now() })
      }
    } else if (op === 0xd0 && data.byteLength >= 8) {
      // gyro: 4 × int16 LE
      const qw = data.getInt16(1, true) / 10000
      const qx = data.getInt16(3, true) / 10000
      const qy = data.getInt16(5, true) / 10000
      const qz = data.getInt16(7, true) / 10000
      this.emitter.emit('gyro', { x: qx, y: qy, z: qz, w: qw })
    }
  }

  // ── v3 协议 (Gen3 早期) ─────────────────────────
  private async _connectV3(server: BluetoothRemoteGATTServer, svc: BluetoothRemoteGATTService) {
    this.readChr = await svc.getCharacteristic(CHRCT_UUID_V3READ)
    this.writeChr = await svc.getCharacteristic(CHRCT_UUID_V3WRITE)
    this.readChr.addEventListener('characteristicvaluechanged', (e: any) => {
      this._onPacketV3(e.target.value as DataView)
    })
    await this.readChr.startNotifications()
  }

  private _onPacketV3(data: DataView): void {
    if (data.byteLength < 4) return
    const op = data.getUint8(0)
    if (op === 0x01 && data.byteLength >= 2) {
      // move byte at offset 1 (half-turn, 合并)
      const moveByte = data.getUint8(1)
      const m = decodeGanMoveByte(moveByte)
      if (m) {
        const r = this.state.applyMove(m)
        if (r.lastMove) this.emitter.emit('move', { move: r.lastMove, timestamp: Date.now() })
      }
    }
    // v3 完整协议: facelet, gyro, battery 等都分散在不同 op, 暂简化
  }

  // ── v1 协议 (旧版 GAN 356 / i3) ─────────────────────
  private async _connectV1(server: BluetoothRemoteGATTServer, svc: BluetoothRemoteGATTService) {
    this.f2Chr = await svc.getCharacteristic(CHRCT_UUID_F2)
    this.f3Chr = await svc.getCharacteristic(CHRCT_UUID_F3)
    this.f5Chr = await svc.getCharacteristic(CHRCT_UUID_F5)
    this.f7Chr = await svc.getCharacteristic(CHRCT_UUID_F7)
    // F3: move (notify)
    this.f3Chr.addEventListener('characteristicvaluechanged', (e: any) => {
      this._onPacketV1_move(e.target.value as DataView)
    })
    await this.f3Chr.startNotifications()
    // F5: gyro
    if (this.f5Chr) {
      this.f5Chr.addEventListener('characteristicvaluechanged', (e: any) => {
        this._onPacketV1_gyro(e.target.value as DataView)
      })
      try { await this.f5Chr.startNotifications() } catch {}
    }
    // F7: battery
    if (this.f7Chr) {
      this.f7Chr.addEventListener('characteristicvaluechanged', (e: any) => {
        this._onPacketV1_battery(e.target.value as DataView)
      })
      try { await this.f7Chr.startNotifications() } catch {}
    }
    // F2: facelet (read on demand)
  }

  private _onPacketV1_move(data: DataView): void {
    if (data.byteLength < 2) return
    // v1 move: 1 字节 face, 1 字节 power (0=顺, 1=逆, 2=2 步)
    const face = data.getUint8(0)
    const power = data.getUint8(1)
    const faceChar = 'RLUDFB'[face]
    if (!faceChar) return
    let move: string
    if (power === 2) move = `${faceChar}2`
    else if (power === 1) move = `${faceChar}'`
    else move = faceChar
    const r = this.state.applyMove(move)
    if (r.lastMove) this.emitter.emit('move', { move: r.lastMove, timestamp: Date.now() })
  }

  private _onPacketV1_gyro(data: DataView): void {
    if (data.byteLength < 8) return
    const qw = data.getInt16(0, true) / 10000
    const qx = data.getInt16(2, true) / 10000
    const qy = data.getInt16(4, true) / 10000
    const qz = data.getInt16(6, true) / 10000
    this.emitter.emit('gyro', { x: qx, y: qy, z: qz, w: qw })
  }

  private _onPacketV1_battery(data: DataView): void {
    if (data.byteLength < 1) return
    this.batteryLevel = data.getUint8(0)
    this.emitter.emit('battery', { level: this.batteryLevel })
  }

  override async getBattery(): Promise<number> {
    return this.batteryLevel
  }

  override async getFacelet(): Promise<string> {
    if (this.version === 'v1' && this.f2Chr) {
      try {
        const v = await this.f2Chr.readValue()
        // 48 字节 3-bit packed facelet (54 * 3 bits = 162 bits = 21 字节,
        // 但 v1 F2 是 48 字节, 包含一些 padding)
        // TODO: 完整 3-bit 解包
        return this.state.curFacelet
      } catch {
        return this.state.curFacelet
      }
    }
    return this.state.curFacelet
  }
}

autoRegister({
  brand: 'GAN',
  cubeType: '3x3',
  namePrefixes: [...GAN_NAME_PREFIXES],
  gattServiceUuids: [
    SERVICE_UUID_V1,  // 0xFFF0
    SERVICE_UUID_V4,  // 00000010-...
    SERVICE_UUID_V3,  // 8653000a-...
  ],
  detect: (device) => GAN_NAME_PREFIXES.some(p => device.name?.startsWith(p)),
  factory: (ctx) => new GanAdapter(ctx),
})
