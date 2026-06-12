/**
 * services/smart-cube/adapters/BaseAdapter.ts ── 适配器基类
 *
 * 抽离所有适配器公共逻辑:
 *  - Emitter 持有
 *  - on / off / onAny
 *  - connect / disconnect 模板
 * 子类只需实现 _onPacket(value) 即可
 */
import { AdapterEventEmitter } from '../EventEmitter'
import type {
  ISmartCubeAdapter, SmartCubeDeviceInfo, AdapterInitContext, CubeBrand,
} from '../types'

export abstract class BaseAdapter implements ISmartCubeAdapter {
  readonly brand: CubeBrand
  readonly info: SmartCubeDeviceInfo

  protected device: BluetoothDevice
  protected emitter = new AdapterEventEmitter()
  protected characteristic: BluetoothRemoteGATTCharacteristic | null = null

  constructor(ctx: AdapterInitContext, brand: CubeBrand, extra: Partial<SmartCubeDeviceInfo> = {}) {
    this.brand = brand
    this.device = ctx.device
    this.info = {
      brand,
      cubeType: '3x3',
      name: ctx.device.name ?? brand,
      id: ctx.device.id,
      ...extra,
    }
  }

  async connect(): Promise<void> {
    if (!this.device.gatt) throw new Error(`${this.brand}: device.gatt 不可用`)
    const server = await this.device.gatt.connect()
    // 子类可重写整个 connect 流程 (GAN/QiYi 等多 service 协议)
    // 此时 _selectService / _selectCharacteristic 标记为 no-op
    const service = await this._selectService(server)
    const chars = await service.getCharacteristics()
    this.characteristic = await this._selectCharacteristic(chars)
    this.characteristic.addEventListener('characteristicvaluechanged', (event) => {
      const value = (event.target as BluetoothRemoteGATTCharacteristic).value
      if (value && this._onPacket) this._onPacket(value)
    })
    await this.characteristic.startNotifications()
  }

  async disconnect(): Promise<void> {
    try { await this.characteristic?.stopNotifications() } catch { /* ignore */ }
    try { this.device.gatt?.disconnect() } catch { /* ignore */ }
    this.emitter.emit('disconnect', undefined)
  }

  /** 子类按需重写: 选择 GATT service. 多数单 service 协议用这个.
   *  多 service 协议 (GAN/QiYi/GoCube) 重写整个 connect() 即可. */
  protected async _selectService(_server: BluetoothRemoteGATTServer): Promise<BluetoothRemoteGATTService> {
    throw new Error(`${this.brand}: 子类必须实现 _selectService 或重写 connect()`)
  }
  /** 子类按需重写: 从 characteristics 列表里挑 notify 通道 */
  protected async _selectCharacteristic(_chars: BluetoothRemoteGATTCharacteristic[]): Promise<BluetoothRemoteGATTCharacteristic> {
    throw new Error(`${this.brand}: 子类必须实现 _selectCharacteristic 或重写 connect()`)
  }
  /** 子类实现: 把一个 DataView 解码成标准事件. 多数单 service 协议用这个.
   *  重写 connect() 的多 service 协议 (GAN/QiYi) 不需要实现. */
  protected _onPacket?(_value: DataView): void

  // 默认 battery/facelet 桩, 子类可重写
  async getBattery(): Promise<number> { return 100 }
  async getFacelet(): Promise<string> { return 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB' }

  // 事件接口代理
  on = this.emitter.on.bind(this.emitter)
  onAny = this.emitter.onAny.bind(this.emitter)
  off = this.emitter.off.bind(this.emitter)
}
