/**
 * services/smart-cube/types.ts ── 智能魔方适配器标准接口
 *
 * 设计目标: 与具体厂商 (GAN / MoYu / QiYi / GoCube / Rubik's) 完全解耦
 *   - ISmartCubeAdapter 是所有适配器必须实现的"普通话"接口
 *   - 各厂商 BLE GATT 协议差异封装在 adapters/*.ts 内部
 *   - 上层 (CubeDeviceManager / store / Cube3D) 只依赖本文件
 *
 * 事件命名故意与 csTimer 的 evtCallback(info, event) 对齐:
 *   - 'gyro'      -> 四元数 (60Hz, 高频)
 *   - 'move'      -> 单步 WCA 转动字符串 (中频, ~10Hz)
 *   - 'facelet'   -> 54 字符状态 (低频, 几秒一次)
 *   - 'battery'   -> 电量 0-100 (低频)
 *   - 'disconnect'-> 设备断开
 * 未来从 csTimer 移植协议时, 直接复用事件名, 几乎零成本
 */

/** 厂商 ID (用于 Manager 选择适配器 + UI 显示) */
export type CubeBrand = 'GAN' | 'MoYu' | 'QiYi' | 'GoCube' | 'Rubiks' | 'Unknown'

/** 设备类型 (3x3 / 4x4 / 5x5 / pyraminx / megaminx) */
export type CubeType = '3x3' | '4x4' | '5x5' | 'pyraminx' | 'megaminx' | 'unknown'

/** 统一硬件事件: 故意做成 (info, event) 二元组对齐 csTimer */
export type SmartCubeEventInfo =
  | 'gyro'        // event: { x, y, z, w } 四元数
  | 'move'        // event: { move: 'R' | "R'" | 'R2' | ..., timestamp?: number }
  | 'facelet'     // event: 54 字符字符串
  | 'battery'     // event: { level: 0-100, charging?: boolean }
  | 'disconnect'  // event: undefined 或 { reason?: string }
  | 'error'       // event: { message: string, code?: number }

export type SmartCubeEvent = {
  gyro:      { x: number; y: number; z: number; w: number }
  move:      { move: string; timestamp?: number }
  facelet:   string
  battery:   { level: number; charging?: boolean }
  disconnect: { reason?: string } | undefined
  error:     { message: string; code?: number }
}

/** 标准化设备描述 (扫描结果 -> Manager 决策用) */
export interface SmartCubeDeviceInfo {
  brand: CubeBrand
  cubeType: CubeType
  /** BLE 设备名 (用于前端展示) */
  name: string
  /** 前端无法直接拿 MAC, 用 id 标识 (Web Bluetooth 给的 device.id) */
  id: string
  /** 厂商信息 (厂家原始名 / 固件版本 / 序列号 等) */
  vendorMeta?: Record<string, unknown>
}

/** 适配器构造时需要的最小集 (各家协议读取 manufacturer data / adv / GATT 都不同) */
export interface AdapterInitContext {
  device: BluetoothDevice
  /** GATT 服务列表, 由 Manager 扫描时拿到, 传给适配器做协议层 dispatch */
  services: BluetoothRemoteGATTService[]
}

/** 适配器必须实现的能力 (对上层就是黑盒) */
export interface ISmartCubeAdapter {
  readonly brand: CubeBrand
  readonly info: SmartCubeDeviceInfo

  /** 建立 GATT 连接 + 订阅 notify + 启动解密循环 */
  connect(): Promise<void>
  /** 主动断开 (会触发 onHardwareEvent('disconnect')) */
  disconnect(): Promise<void>
  /** 单次读电量 (部分魔方需要 GATT read, 部分通过事件推) */
  getBattery(): Promise<number>
  /** 单次读 facelet 状态 (部分魔方有命令可主动拉) */
  getFacelet?(): Promise<string>

  /** 标准事件订阅: 跟 wsStore 一样是 Pub/Sub */
  on<E extends SmartCubeEventInfo>(event: E, handler: (data: SmartCubeEvent[E]) => void): () => void
  /** 等价于 on('*', handler) 一次拿所有事件 */
  onAny(handler: (info: SmartCubeEventInfo, data: SmartCubeEvent[SmartCubeEventInfo]) => void): () => void
  off(event: SmartCubeEventInfo, handler: (data: any) => void): void
}

/** Adapter 工厂签名: Manager 通过 detect() 决策后调用 */
export type AdapterFactory = (ctx: AdapterInitContext) => ISmartCubeAdapter

/** Manager 注册表的单条记录 */
export interface AdapterRegistration {
  brand: CubeBrand
  cubeType: CubeType
  /** 用于 BLE 扫描的 namePrefix 列表 (例: ['GAN', 'MG']) */
  namePrefixes: string[]
  /** 该品牌 GATT service UUIDs (128-bit hex), Web Bluetooth 必须列在 optionalServices */
  gattServiceUuids: string[]
  /** 厂商自定义 detect 逻辑 (例如读 manufacturer data 第 0 字节) */
  detect?: (device: BluetoothDevice, advData?: ArrayBuffer) => boolean
  factory: AdapterFactory
}
