/**
 * 全局轻量状态 (当前用户, 今日训练项, 智能魔方连接) - zustand
 * 公式库这种大对象不放在这里, 用 react-query 缓存
 *
 * 设计:
 *  - 智能魔方 connected / battery / firmware 走 zustand (低频, 几秒变一次)
 *  - 60Hz 四元数 / 单步 move 不进 store, 走 useWebSocketEvents → window.__cubeBridge → Cube3D ref
 *  - 这样智能魔方连接时 React 一帧都不会重渲染
 */
import { create } from 'zustand'
import { UsersAPI, TrainingAPI } from '@/api/client'
import type { User, TrainingTask } from '@/types/api'

export type SmartCubeStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface SmartCubeState {
  status: SmartCubeStatus
  deviceId: string | null
  battery: number | null          // 0-100
  firmware: string | null
  lastSeen: number | null
  setStatus:  (s: SmartCubeStatus) => void
  setDevice:  (id: string | null) => void
  setBattery: (b: number | null) => void
  setFirmware:(v: string | null) => void
  setLastSeen:(t: number) => void
}

interface AppState {
  user: User | null
  loading: boolean
  tasks: TrainingTask[]
  smartCube: SmartCubeState
  /** 当前 54 字符 Kociemba facelet 状态, 驱动 3D 魔方颜色 */
  facelet: string
  setFacelet: (f: string) => void

  // actions
  login: (username: string) => Promise<User>
  /** 【已移除登录页】直接注入一个本地默认 user, 跳过登录 */
  _bootDefaultUser: () => void
  logout: () => void
  setTasks: (tasks: TrainingTask[]) => void
  markTaskDone: (id: number, result: object) => Promise<void>
  skipTask: (id: number) => Promise<void>
}

const LS_KEY = 'cstimer_user_v1'

export const useAppStore = create<AppState>((set, get) => ({
  user: (() => {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || 'null') } catch { return null }
  })(),
  loading: false,
  tasks: [],
  facelet: 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB',  // solved
  setFacelet: (f) => set({ facelet: f }),

  smartCube: {
    status: 'disconnected',
    deviceId: null,
    battery: null,
    firmware: null,
    lastSeen: null,
    setStatus:  (s)  => set(st => ({ smartCube: { ...st.smartCube, status: s  } })),
    setDevice:  (id) => set(st => ({ smartCube: { ...st.smartCube, deviceId: id } })),
    setBattery: (b)  => set(st => ({ smartCube: { ...st.smartCube, battery: b  } })),
    setFirmware:(v)  => set(st => ({ smartCube: { ...st.smartCube, firmware: v } })),
    setLastSeen:(t)  => set(st => ({ smartCube: { ...st.smartCube, lastSeen: t } })),
  },

  login: async (username) => {
    set({ loading: true })
    const u = await UsersAPI.create(username)
    localStorage.setItem(LS_KEY, JSON.stringify(u))
    set({ user: u, loading: false })
    return u
  },
  // 【已移除登录页】启动时直接挂一个本地默认 user
  // 如果你后端数据库里的真实 user id 不是 1, 改下面 DEFAULT_USER_ID
  _bootDefaultUser: () => {
    if (get().user) return  // 已有 (例如 LS 残留), 不覆盖
    const defaultUser: User = {
      id: 1,
      username: 'guest',
      timezone: 'Asia/Shanghai',
      created_at: Date.now(),
    }
    localStorage.setItem(LS_KEY, JSON.stringify(defaultUser))
    set({ user: defaultUser })
  },
  logout: () => {
    localStorage.removeItem(LS_KEY)
    set({ user: null, tasks: [] })
  },
  setTasks: (tasks) => set({ tasks }),
  markTaskDone: async (id, result) => {
    const updated = await TrainingAPI.markDone(id, result)
    set({ tasks: get().tasks.map(t => t.id === id ? updated : t) })
  },
  skipTask: async (id) => {
    const updated = await TrainingAPI.skip(id)
    set({ tasks: get().tasks.map(t => t.id === id ? updated : t) })
  },
}))

// 便捷 selector, 避免不必要 re-render
export const useSmartCube = () => useAppStore(s => s.smartCube)
