/**
 * services/smart-cube/CubeDeviceManager.ts ── 智能魔方设备管理器
 *
 * 职责:
 *  1. 注册所有厂商的 Adapter 工厂
 *  2. 调用 Web Bluetooth API 扫描设备
 *  3. 根据 device.name / manufacturerData 自动匹配到对应 Adapter
 *  4. 实例化 Adapter, 桥接适配器事件 -> wsStore (高频走 bridge, 低频走 store)
 *  5. 维护当前连接 (单设备, 未来要支持多设备再做 pool)
 *
 * 【架构关键】
 *  Cube3D / useAppStore 完全不知道 GAN / MoYu 的存在
 *  它们只看到统一的 ISmartCubeAdapter 接口
 */
import type {
  ISmartCubeAdapter, AdapterRegistration, AdapterFactory, CubeBrand,
  SmartCubeEventInfo, SmartCubeEvent,
} from './types'
import { registerCubeBridge } from '@/store/cubeStore'

class CubeDeviceManager {
  private registry: AdapterRegistration[] = []
  private currentAdapter: ISmartCubeAdapter | null = null
  private currentUnsub: (() => void) | null = null

  /** 注册一个厂商的适配器 (各 adapter 模块在 import 时自动调) */
  register(reg: AdapterRegistration): void {
    // 同 brand 后注册的覆盖先注册的 (允许 hot-replace 协议版本)
    this.registry = this.registry.filter(r => r.brand !== reg.brand)
    this.registry.push(reg)
  }

  /** 列出当前已注册的厂商 (UI 显示用) */
  listBrands(): CubeBrand[] {
    return this.registry.map(r => r.brand)
  }

  /**
   * 扫描并连接
   * @param acceptFilters  - 进一步限制前端 UI 候选 (例: 只显示 GAN)
   *                        为空时用全部已注册 adapter 的 namePrefix
   */
  async scanAndConnect(acceptFilters?: CubeBrand[]): Promise<ISmartCubeAdapter> {
    if (!('bluetooth' in navigator)) {
      throw new Error('当前浏览器不支持 Web Bluetooth, 请使用 Chrome / Edge')
    }

    // 1) 准备 BLE 扫描 filters (把 namePrefix 摊平)
    const candidates = acceptFilters?.length
      ? this.registry.filter(r => acceptFilters.includes(r.brand))
      : this.registry
    const namePrefixes = [...new Set(candidates.flatMap(r => r.namePrefixes))]
    const filters: BluetoothLEScanFilter[] = namePrefixes.map(prefix => ({ namePrefix: prefix }))
    // 关键: 把所有候选 adapter 的 GATT service UUID 摊平, Web Bluetooth
    // 要求列在 optionalServices, 否则 connect 阶段 GATT 拒绝访问 (Origin not allowed)
    const optionalServices = [...new Set(candidates.flatMap(r => r.gattServiceUuids))]

    // 2) 调 navigator.bluetooth.requestDevice
    const device = await navigator.bluetooth.requestDevice({
      filters,
      optionalServices,
    })

    // 3) 决策: 哪个 adapter 接这个 device
    const adapter = await this._instantiateForDevice(device, candidates)
    if (!adapter) {
      throw new Error(`未找到匹配 "${device.name}" 的适配器, 请先注册该品牌`)
    }

    // 4) 连接 + 桥接到 store
    await adapter.connect()
    this._attachToStore(adapter)
    this.currentAdapter = adapter
    return adapter
  }

  /** 已拿到 device (例如从历史列表), 直接 attach 适配器 */
  async attachDevice(device: BluetoothDevice): Promise<ISmartCubeAdapter> {
    const adapter = await this._instantiateForDevice(device, this.registry)
    if (!adapter) throw new Error(`未找到 "${device.name}" 对应的适配器`)
    await adapter.connect()
    this._attachToStore(adapter)
    this.currentAdapter = adapter
    return adapter
  }

  /** 断开当前连接 */
  async disconnect(): Promise<void> {
    if (this.currentUnsub) { this.currentUnsub(); this.currentUnsub = null }
    if (this.currentAdapter) {
      await this.currentAdapter.disconnect()
      this.currentAdapter = null
    }
  }

  get current(): ISmartCubeAdapter | null {
    return this.currentAdapter
  }

  // ─── 内部 ────────────────────────────────────────
  private async _instantiateForDevice(
    device: BluetoothDevice,
    candidates: AdapterRegistration[],
  ): Promise<ISmartCubeAdapter | null> {
    // 优先级 1: namePrefix 精确匹配
    const nameMatch = candidates.find(r =>
      r.namePrefixes.some(p => device.name?.startsWith(p))
    )
    let chosen: AdapterRegistration | undefined = nameMatch
    // 优先级 2: detect() 自定义逻辑 (读 manufacturer data 等)
    if (!chosen) {
      chosen = candidates.find(r => r.detect?.(device))
    }
    if (!chosen) return null

    // 连接 GATT 拿服务列表
    if (!device.gatt) return null
    const server = await device.gatt.connect()
    // 简化: 把 server 本身当作 services 列表的入口, 由 adapter 自己二次遍历
    return chosen.factory({
      device,
      services: [],  // 真实实现里可以根据 chosen.brand 的 service UUID 主动 getPrimaryService
    })
  }

  /**
   * 桥接适配器事件到 cubeStore
   * - 高频 (gyro, move) -> cubeStore 内部走 ref 桥, 不进 React state
   * - 低频 (facelet, battery) -> cubeStore 走 zustand state
   */
  private _attachToStore(adapter: ISmartCubeAdapter): void {
    if (this.currentUnsub) { this.currentUnsub(); this.currentUnsub = null }

    const bridge = registerCubeBridge(adapter)
    this.currentUnsub = () => {
      bridge.dispose()
    }
  }
}

export const deviceManager = new CubeDeviceManager()

/** 让各 adapter 文件能自注册的辅助 */
export function autoRegister(reg: AdapterRegistration): void {
  deviceManager.register(reg)
}
