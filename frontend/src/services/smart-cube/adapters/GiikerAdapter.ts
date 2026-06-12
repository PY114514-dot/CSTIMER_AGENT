/**
 * services/smart-cube/adapters/GiikerAdapter.ts ── Giiker / 小米魔方适配器
 *
 * 协议来源: cstimer/src/js/hardware/giikercube.js
 *  - service 0xAADB (notify) + 0xAAAA (R/W for battery)
 *  - 每包 20 字节 (encrypted 时 raw[18] == 0xa7)
 *  - 包格式 (解密后 nibbles):
 *      [0..7]   角块位置 (8 角)
 *      [8..15]  角块方向
 *      [16..27] 边块位置 (12 边, 每 nibble)
 *      [28..31] 边块方向 (3 字节 × 8 mask)
 *      [32..39] 最近 4 个 move (每 2 nibble: face + power)
 *  - 解密密钥: 36 字节数组, 由 raw[19] 决定偏移
 */
import { BaseAdapter } from './BaseAdapter'
import type { CubeBrand } from '../types'
import { autoRegister } from '../CubeDeviceManager'

const UUID_SUFFIX = '-0000-1000-8000-00805f9b34fb'
const SERVICE_UUID_DATA = `0000aadb${UUID_SUFFIX}`
const CHRCT_UUID_DATA = `0000aadc${UUID_SUFFIX}`
const SERVICE_UUID_RW = `0000aaaa${UUID_SUFFIX}`
const CHRCT_UUID_READ = `0000aaab${UUID_SUFFIX}`
const CHRCT_UUID_WRITE = `0000aaac${UUID_SUFFIX}`

// 角块 -> facelet 转换 (cstimer cFacelet / eFacelet)
const C_FACELET = [
  [26, 15, 29], [20, 8, 9], [18, 38, 6], [24, 27, 44],
  [51, 35, 17], [45, 11, 2], [47, 0, 36], [53, 42, 33],
]
const E_FACELET = [
  [25, 28], [23, 12], [19, 7], [21, 41], [32, 16], [5, 10],
  [3, 37], [30, 43], [52, 34], [48, 14], [46, 1], [50, 39],
]

// 36 字节解密 key (来自 cstimer)
const DECRYPT_KEY = [
  176, 81, 104, 224, 86, 137, 237, 119, 38, 26, 193, 161,
  210, 126, 150, 81, 93, 13, 236, 249, 89, 235, 88, 24,
  113, 81, 214, 131, 130, 199, 2, 169, 39, 165, 171, 41,
]

const GIIKER_NAME_PREFIXES = ['Gi', 'Mi Smart Magic Cube', 'Hi-', 'Quner'] as const

// 设备: state machine (保持最近 8 个 move + 当前位置)
class GiikerState {
  curFacelet = 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB'
  prevMoves: string[] = []
  // 内部 cubie 状态 (简化: 直接维护 facelet 字符串 + 解析 move)
  applyMove(m: string): string {
    // 应用单步到 facelet 字符串
    const f = parseFaceIdx(m[0])
    const p = m[1] === "'" ? 3 : m[1] === '2' ? 2 : 1
    this.curFacelet = applyMoveToFacelet(this.curFacelet, f, p)
    this.prevMoves.unshift(m)
    if (this.prevMoves.length > 8) this.prevMoves.length = 8
    return this.curFacelet
  }
}

// 解析一个 byte 拿到 cubie 状态
function parseGiikerState(value: DataView): { facelet: string; lastMoves: string[] } | null {
  if (value.byteLength < 20) return null
  // 拿到 40 个 nibble
  let nibbles: number[] = []
  for (let i = 0; i < 20; i++) {
    const b = value.getUint8(i)
    nibbles.push((b >> 4) & 0xf)
    nibbles.push(b & 0xf)
  }
  // 如果 raw[18] == 0xa7 触发解密
  if (value.getUint8(18) === 0xa7) {
    const k1 = (value.getUint8(19) >> 4) & 0xf
    const k2 = value.getUint8(19) & 0xf
    // 替换前 18 字节
    for (let i = 0; i < 18; i++) {
      const orig = (nibbles[i * 2] << 4) | nibbles[i * 2 + 1]
      const newByte = (orig - DECRYPT_KEY[i + k1] - DECRYPT_KEY[i + k2]) & 0xff
      nibbles[i * 2] = (newByte >> 4) & 0xf
      nibbles[i * 2 + 1] = newByte & 0xf
    }
    nibbles = nibbles.slice(0, 36)
  }
  // 边块方向 (nibbles[28..31])
  const eo: number[] = []
  for (let i = 0; i < 3; i++) {
    for (let mask = 8; mask > 0; mask >>= 1) {
      eo.push((nibbles[28 + i] & mask) ? 1 : 0)
    }
  }
  // 角块位置 + 方向 (cstimer 用 mathlib.CubieCube, 这里直接转 facelet)
  // 简化算法: 用 (corner_pos, corner_ori, edge_pos, edge_ori) -> 54 字符 facelet
  // TODO: 完整实现需要 cstimer 的 CubieCube 数学; 这里用占位 + 优先发送 prevMoves 由前端重放
  const coMask = [-1, 1, -1, 1, 1, -1, 1, -1]
  const corner = []
  for (let i = 0; i < 8; i++) {
    const cp = nibbles[i] - 1             // 0..7
    const co = (((3 + nibbles[8 + i] * coMask[i]) % 3) << 3) | cp
    corner.push(co)
  }
  const edge = []
  for (let i = 0; i < 12; i++) {
    const ep = nibbles[16 + i] - 1
    const eOri = eo[i] << 1
    edge.push((ep << 1) | eOri)
  }
  const facelet = cubieToFacelet(corner, edge)
  // 最近 4 个 move (nibbles[32..39], 每 2 nibble: face + power)
  const lastMoves: string[] = []
  for (let i = 0; i < 8; i += 2) {
    const f = nibbles[32 + i]
    if (f === 0) break  // 没有更多
    const p = (nibbles[32 + i + 1] - 1) % 7
    const face = 'BDLURF'[f - 1]
    const suf = p === 2 ? '2' : ''
    lastMoves.push(face + suf)
  }
  return { facelet, lastMoves }
}

// cubie -> facelet (简化版: 用 C_FACELET / E_FACELET 表)
function cubieToFacelet(corner: number[], edge: number[]): string {
  // 颜色字符: 0..5 = U R F D L B
  const cColors = 'URFDLB'
  const ret: string[] = new Array(54).fill('U')
  // 8 角块
  for (let i = 0; i < 8; i++) {
    const c = corner[i]
    const cp = c & 7
    const co = (c >> 3) & 3
    const faces = C_FACELET[i]  // 3 个面位置
    const colors = cornerColors(cp, co)
    ret[faces[0]] = cColors[colors[0]]
    ret[faces[1]] = cColors[colors[1]]
    ret[faces[2]] = cColors[colors[2]]
  }
  // 12 边块
  for (let i = 0; i < 12; i++) {
    const e = edge[i]
    const ep = e >> 1
    const eOri = e & 1
    const faces = E_FACELET[i]
    const colors = edgeColors(ep, eOri)
    ret[faces[0]] = cColors[colors[0]]
    ret[faces[1]] = cColors[colors[1]]
  }
  return ret.join('')
}

// 角块位置 -> 3 个面颜色 (URFDLB)
// cp = 0..7, co = 0..2 (twist)
function cornerColors(cp: number, co: number): [number, number, number] {
  // 标准角块位置 -> 面 (URFDLB)
  const cornerFaces: Array<[number, number, number]> = [
    [0, 4, 1],  // 0: URF
    [0, 1, 5],  // 1: ULF  (UFL)
    [0, 3, 4],  // 2: UDF  (UDR -> 用 UDF)
    [0, 5, 3],  // 3: UDL
    [2, 1, 4],  // 4: DFR
    [2, 4, 3],  // 5: DFL  (DFL -> DFR/DFL)
    [2, 3, 5],  // 6: DBL
    [2, 5, 1],  // 7: DRL
  ]
  const f = cornerFaces[cp]
  // co 表示 twist: 0 = 正确, 1 = 顺时针 120°, 2 = 逆时针 120°
  if (co === 0) return f
  if (co === 1) return [f[1], f[2], f[0]]
  return [f[2], f[0], f[1]]
}

function edgeColors(ep: number, eOri: number): [number, number] {
  // 0..11 = UR, UF, UL, UB, DR, DF, DL, DB, FR, FL, BL, BR
  const edgeFaces: Array<[number, number]> = [
    [0, 1],  // UR
    [0, 4],  // UF
    [0, 5],  // UL
    [0, 3],  // UB
    [2, 1],  // DR
    [2, 4],  // DF
    [2, 5],  // DL
    [2, 3],  // DB
    [4, 1],  // FR
    [4, 5],  // FL
    [3, 5],  // BL
    [3, 1],  // BR
  ]
  const f = edgeFaces[ep]
  if (eOri === 0) return f
  return [f[1], f[0]]
}

function parseFaceIdx(c: string): number {
  return 'URFDLB'.indexOf(c)
}

function applyMoveToFacelet(state: string, face: number, power: number): string {
  // 简化: 这里需要完整的 facelet 旋转算法
  // 暂时返回原状态 (move 解析不完整, 但 BLE 链路是工作的)
  // TODO: 实现 6 面 9 格旋转
  return state
}

export class GiikerAdapter extends BaseAdapter {
  private state = new GiikerState()
  private dataChr: BluetoothRemoteGATTCharacteristic | null = null
  private readChr: BluetoothRemoteGATTCharacteristic | null = null
  private writeChr: BluetoothRemoteGATTCharacteristic | null = null

  constructor(ctx: any) {
    super(ctx, 'GoCube' as CubeBrand, {
      brand: 'GoCube',
      name: ctx.device.name ?? 'Giiker Cube',
    })
  }

  /** Giiker 用 2 个 service, BaseAdapter 默认模板不适配, 重写 connect */
  override async connect(): Promise<void> {
    if (!this.device.gatt) throw new Error('Giiker: device.gatt 不可用')
    const server = await this.device.gatt.connect()
    // 1) data service
    const dataSvc = await server.getPrimaryService(SERVICE_UUID_DATA)
    this.dataChr = await dataSvc.getCharacteristic(CHRCT_UUID_DATA)
    this.dataChr.addEventListener('characteristicvaluechanged', (e: any) => {
      const v = e.target.value as DataView
      const parsed = parseGiikerState(v)
      if (!parsed) return
      this.state.curFacelet = parsed.facelet
      this.state.prevMoves = parsed.lastMoves
      this.emitter.emit('facelet', parsed.facelet)
      // 把最近的 move 推送给前端
      for (let i = parsed.lastMoves.length - 1; i >= 0; i--) {
        this.emitter.emit('move', { move: parsed.lastMoves[i], timestamp: Date.now() })
      }
    })
    await this.dataChr.startNotifications()
    // 2) RW service for battery (lazily connected on getBattery)
    const rwSvc = await server.getPrimaryService(SERVICE_UUID_RW)
    this.readChr = await rwSvc.getCharacteristic(CHRCT_UUID_READ)
    this.writeChr = await rwSvc.getCharacteristic(CHRCT_UUID_WRITE)
  }

  override async getBattery(): Promise<number> {
    if (!this.readChr || !this.writeChr) return 100
    return new Promise<number>(async (resolve) => {
      const handler = (e: any) => {
        const lvl = (e.target.value as DataView).getUint8(1)
        this.readChr!.removeEventListener('characteristicvaluechanged', handler)
        this.readChr!.stopNotifications().catch(() => {})
        resolve(lvl)
      }
      try {
        await this.readChr!.startNotifications()
        this.readChr!.addEventListener('characteristicvaluechanged', handler)
        await this.writeChr!.writeValue(new Uint8Array([0xb5]).buffer as ArrayBuffer)
      } catch {
        resolve(100)
      }
      setTimeout(() => resolve(100), 2000)  // 超时兜底
    })
  }
}

autoRegister({
  brand: 'GoCube' as CubeBrand,
  cubeType: '3x3',
  namePrefixes: [...GIIKER_NAME_PREFIXES],
  gattServiceUuids: [
    SERVICE_UUID_DATA,
    SERVICE_UUID_RW,
  ],
  detect: (device) => GIIKER_NAME_PREFIXES.some(p => device.name?.startsWith(p)),
  factory: (ctx) => new GiikerAdapter(ctx),
})
