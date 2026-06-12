/**
 * store/cubeStore.ts ── 智能魔方标准事件分发层
 *
 * 职责:
 *  1. 接收 ISmartCubeAdapter 推过来的标准事件 (gyro/move/facelet/battery/...)
 *  2. 高频 (gyro 60Hz, move 10Hz): 走 ref 桥 (window.__cubeBridge) -> Cube3D useFrame, 0 渲染
 *  3. 低频 (facelet, battery, disconnect, error): 走 zustand state, 触发 UI 更新
 *  4. 给 CubeDeviceManager 提供 registerCubeBridge(adapter) 一键接入
 *
 * 与 wsStore 互补:
 *  - wsStore: 接后端 WebSocket (开发期模拟 / 解算后端)
 *  - cubeStore: 接真实蓝牙硬件 (生产期)
 *  两路数据汇到同一个 window.__cubeBridge, Cube3D 不区分来源
 */
import { create } from 'zustand'
import { useShallow } from 'zustand/react/shallow'
import type { ISmartCubeAdapter, SmartCubeEventInfo, SmartCubeEvent, CubeBrand } from '@/services/smart-cube/types'

export type SmartCubeStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

interface CubeStoreState {
  status: SmartCubeStatus
  brand: CubeBrand | null
  deviceName: string | null
  battery: number | null
  /** 最近一次 54 字符 facelet (低频, 触发 React 渲染) */
  facelet: string | null
  /** 最近一次错误信息 */
  lastError: string | null
  lastEventAt: number | null

  // actions
  _setStatus: (s: SmartCubeStatus) => void
  _setBrand: (b: CubeBrand | null) => void
  _setDeviceName: (n: string | null) => void
  _setBattery: (b: number | null) => void
  _setFacelet: (f: string) => void
  _setError: (e: string | null) => void
  _touch: (ts: number) => void
}

export const useCubeStore = create<CubeStoreState>((set) => ({
  status: 'disconnected',
  brand: null,
  deviceName: null,
  battery: null,
  facelet: null,
  lastError: null,
  lastEventAt: null,

  _setStatus:    (s) => set({ status: s }),
  _setBrand:     (b) => set({ brand: b }),
  _setDeviceName:(n) => set({ deviceName: n }),
  _setBattery:   (b) => set({ battery: b }),
  _setFacelet:   (f) => set({ facelet: f, lastEventAt: Date.now() }),
  _setError:     (e) => set({ lastError: e }),
  _touch:        (t) => set({ lastEventAt: t }),
}))

/** 便捷 selector (用 useShallow 避免不相关字段变化触发 re-render) */
export function useCubeSnapshot() {
  return useCubeStore(
    useShallow(s => ({
      status: s.status,
      brand: s.brand,
      deviceName: s.deviceName,
      battery: s.battery,
      lastEventAt: s.lastEventAt,
      lastError: s.lastError,
    })),
  )
}

/**
 * registerCubeBridge(adapter) ── 把适配器事件桥接到 cubeStore + Cube3D
 * 返回一个 dispose 句柄, 断开时调用
 *
 * 这是整个"硬件无关"架构的关键:
 *  - Cube3D 不需要知道是 GAN 还是 MoYu
 *  - 适配器不需要知道上层用 zustand 还是 react-query
 *  - 高频数据走 window.__cubeBridge 跨层传递, 不进 React state
 */
export function registerCubeBridge(adapter: ISmartCubeAdapter): { dispose: () => void } {
  const store = useCubeStore.getState()
  store._setStatus('connecting')
  store._setBrand(adapter.info.brand)
  store._setDeviceName(adapter.info.name)

  const subs: Array<() => void> = []

  // ── gyro: 高频, 走 ref 桥, 不触发 React 渲染 ──
  subs.push(adapter.on('gyro', (q) => {
    // 优先走 window.__cubeBridge (Cube3D 挂载时已注册)
    if (window.__cubeBridge?.setPosture) {
      window.__cubeBridge.setPosture(q)
    }
    useCubeStore.getState()._touch(Date.now())
  }))

  // ── move: 中频, 走 ref 桥 (Cube3D 入队动画, 不触发 React 渲染) ──
  subs.push(adapter.on('move', (m) => {
    if (window.__cubeBridge?.pushRealtimeMove) {
      window.__cubeBridge.pushRealtimeMove(m.move)
    }
    useCubeStore.getState()._touch(Date.now())
  }))

  // ── facelet: 低频, 走 state, 触发 UI 重渲染 (Cube3D 接受 facelet prop) ──
  subs.push(adapter.on('facelet', (f) => {
    useCubeStore.getState()._setFacelet(f)
    // 同时也写到 window.__cubeBridge (如果 Cube3D 提供 setFacelet 通道)
    if ((window.__cubeBridge as any)?.setFacelet) {
      (window.__cubeBridge as any).setFacelet(f)
    }
  }))

  // ── battery: 低频, 走 state ──
  subs.push(adapter.on('battery', (b) => {
    useCubeStore.getState()._setBattery(b.level)
  }))

  // ── disconnect: 低频, 走 state ──
  subs.push(adapter.on('disconnect', () => {
    useCubeStore.getState()._setStatus('disconnected')
  }))

  // ── error: 低频, 走 state ──
  subs.push(adapter.on('error', (e) => {
    useCubeStore.getState()._setError(e.message)
    useCubeStore.getState()._setStatus('error')
  }))

  // 连接成功 (这里同步触发, 真实场景也可以在 connect resolve 后再 setStatus)
  useCubeStore.getState()._setStatus('connected')

  return {
    dispose: () => {
      for (const u of subs) u()
      useCubeStore.getState()._setStatus('disconnected')
    },
  }
}
