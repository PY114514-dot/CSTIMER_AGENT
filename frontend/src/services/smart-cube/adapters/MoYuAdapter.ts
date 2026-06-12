/**
 * services/smart-cube/adapters/MoYuAdapter.ts ── 魔域 (MoYu) 智能魔方
 *
 * 协议来源: cstimer/src/js/hardware/moyucube.js
 *  - service 0x1000, 4 个 characteristic:
 *    - 0x1001: write
 *    - 0x1002: read  (一般状态)
 *    - 0x1003: turn  (单步 move, 最重要)
 *    - 0x1004: gyro  (四元数, 60Hz)
 *  - turn 包: 1 字节 = move 数量, 之后每 6 字节一组:
 *      [ts_msb, ts_lsb, ts_mid, ts_2nd, face, dir]
 *    - face = 0..5 (cube xyz: x=0 L, y=2 D, z=4 F)
 *    - dir 是 0/1 增量 (1 增量 = 36 单位)
 *  - axis 转换: [3, 4, 5, 1, 2, 0] (cube xyz -> WCA URFDLB)
 *  - 通过 faceStatus[face] 的 prevRot/curRot 判定 power
 */
import { BaseAdapter } from './BaseAdapter'
import type { CubeBrand } from '../types'
import { autoRegister } from '../CubeDeviceManager'

const UUID_SUFFIX = '-0000-1000-8000-00805f9b34fb'
const SERVICE_UUID = `00001000${UUID_SUFFIX}`
const CHRCT_UUID_WRITE = `00001001${UUID_SUFFIX}`
const CHRCT_UUID_READ = `00001002${UUID_SUFFIX}`
const CHRCT_UUID_TURN = `00001003${UUID_SUFFIX}`
const CHRCT_UUID_GYRO = `00001004${UUID_SUFFIX}`

const MOYU_NAME_PREFIXES = ['Moyu', 'MFJS', 'WR', 'AiCube', 'MoYu'] as const

// face -> WCA axis (cube xyz -> URFDLB: U=2, R=0, F=4, D=3, L=1, B=5)
const FACE_TO_AXIS = [3, 4, 5, 1, 2, 0]

export class MoYuAdapter extends BaseAdapter {
  private writeChr: BluetoothRemoteGATTCharacteristic | null = null
  private turnChr: BluetoothRemoteGATTCharacteristic | null = null
  private gyroChr: BluetoothRemoteGATTCharacteristic | null = null
  private faceStatus: number[] = [0, 0, 0, 0, 0, 0]

  constructor(ctx: any) {
    super(ctx, 'MoYu', {
      brand: 'MoYu',
      name: ctx.device.name ?? 'MoYu Cube',
    })
  }

  override async connect(): Promise<void> {
    if (!this.device.gatt) throw new Error('MoYu: device.gatt 不可用')
    const server = await this.device.gatt.connect()
    const svc = await server.getPrimaryService(SERVICE_UUID)
    this.writeChr = await svc.getCharacteristic(CHRCT_UUID_WRITE)
    const readChr = await svc.getCharacteristic(CHRCT_UUID_READ)
    this.turnChr = await svc.getCharacteristic(CHRCT_UUID_TURN)
    this.gyroChr = await svc.getCharacteristic(CHRCT_UUID_GYRO)

    // turn 通道: 单步 move
    this.turnChr.addEventListener('characteristicvaluechanged', (e: any) => {
      this._parseTurn(e.target.value as DataView)
    })
    await this.turnChr.startNotifications()

    // gyro 通道: 四元数
    this.gyroChr.addEventListener('characteristicvaluechanged', (e: any) => {
      this._parseGyro(e.target.value as DataView)
    })
    await this.gyroChr.startNotifications()

    // read 通道: 一般状态
    readChr.addEventListener('characteristicvaluechanged', (e: any) => {
      this._parseRead(e.target.value as DataView)
    })
    try { await readChr.startNotifications() } catch {}
  }

  private _parseTurn(data: DataView): void {
    if (data.byteLength < 1) return
    const nMoves = data.getUint8(0)
    if (data.byteLength < 1 + nMoves * 6) return
    for (let i = 0; i < nMoves; i++) {
      const offset = 1 + i * 6
      // 4 字节时间戳 (大端): byte0=msb, byte1=lsb, byte2=mid, byte3=2nd
      const ts = (data.getUint8(offset + 1) << 24)
              | (data.getUint8(offset + 0) << 16)
              | (data.getUint8(offset + 3) << 8)
              | (data.getUint8(offset + 2))
      const tsMs = Math.round(ts / 65536 * 1000)
      const face = data.getUint8(offset + 4)
      const dir = Math.round(data.getUint8(offset + 5) / 36)
      const prevRot = this.faceStatus[face]
      const curRot = this.faceStatus[face] + dir
      this.faceStatus[face] = (curRot + 9) % 9
      const axis = FACE_TO_AXIS[face]
      let pow: number
      if (prevRot >= 5 && curRot <= 4) pow = 2
      else if (prevRot <= 4 && curRot >= 5) pow = 0
      else continue
      const m = 'URFDLB'[axis] + (' 2\''.charAt(pow)).trim()
      this.emitter.emit('move', { move: m, timestamp: tsMs })
    }
  }

  private _parseGyro(data: DataView): void {
    // 8 字节: 4 × int16 LE (qw, qx, qy, qz) / 16384
    if (data.byteLength < 8) return
    const qw = data.getInt16(0, true) / 16384
    const qx = data.getInt16(2, true) / 16384
    const qy = data.getInt16(4, true) / 16384
    const qz = data.getInt16(6, true) / 16384
    this.emitter.emit('gyro', { x: qx, y: qy, z: qz, w: qw })
  }

  private _parseRead(data: DataView): void {
    // MoYu read 通道: 协议文档不全, 暂时只 log
    if (data.byteLength === 0) return
    // 第 0 字节常见: 0xB1 (battery report), 后 1 字节 = level
    if (data.getUint8(0) === 0xb1 && data.byteLength >= 2) {
      this.emitter.emit('battery', { level: data.getUint8(1) })
    }
  }

  override async getBattery(): Promise<number> {
    // MoYu 没有标准电量命令, 通过 read 通道被动接收
    // TODO: 部分型号需要 write 0xB1 命令触发
    return 100
  }
}

autoRegister({
  brand: 'MoYu',
  cubeType: '3x3',
  namePrefixes: [...MOYU_NAME_PREFIXES],
  gattServiceUuids: [SERVICE_UUID],
  detect: (device) => MOYU_NAME_PREFIXES.some(p => device.name?.startsWith(p)),
  factory: (ctx) => new MoYuAdapter(ctx),
})
