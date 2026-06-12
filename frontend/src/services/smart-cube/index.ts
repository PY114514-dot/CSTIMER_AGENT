/**
 * services/smart-cube/index.ts ── 适配器体系 barrel export
 *
 * 只需要在应用入口 (main.tsx) 加一行:
 *   import '@/services/smart-cube'
 * 就会触发 GanAdapter / MoYuAdapter / QiYiAdapter / GoCubeAdapter / GiikerAdapter 的 autoRegister
 */
import './adapters/GanAdapter'
import './adapters/MoYuAdapter'
import './adapters/QiYiAdapter'
import './adapters/GoCubeAdapter'
import './adapters/GiikerAdapter'

export * from './types'
export { deviceManager } from './CubeDeviceManager'
export { useCubeStore, useCubeSnapshot, registerCubeBridge } from '@/store/cubeStore'
