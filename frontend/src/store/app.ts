/**
 * 全局轻量状态 (当前用户, 今日训练项) - zustand
 * 公式库这种大对象不放在这里, 用 react-query 缓存
 */
import { create } from 'zustand'
import { UsersAPI, TrainingAPI } from '@/api/client'
import type { User, TrainingTask } from '@/types/api'

interface AppState {
  user: User | null
  loading: boolean
  tasks: TrainingTask[]
  // actions
  login: (username: string) => Promise<User>
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

  login: async (username) => {
    set({ loading: true })
    const u = await UsersAPI.create(username)
    localStorage.setItem(LS_KEY, JSON.stringify(u))
    set({ user: u, loading: false })
    return u
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
