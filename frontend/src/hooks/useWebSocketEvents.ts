/**
 * useWebSocketEvents.ts ── 退化: 纯事件订阅 Hook
 *
 * 重要变化 (相比旧版):
 *  - WebSocket 连接生命周期 (Connect / Reconnect / Heartbeat) 已迁出到 store/wsStore.ts
 *    全局只有一条连接 (Singleton), 多个组件调用此 Hook 也不会创建新连接
 *  - 此 Hook 只做两件事:
 *      1) 当 userId 变化时, 调一次 connectWS(userId)
 *      2) 订阅指定事件, 触发 react-query 失效 / 用户回调
 *  - 内部用 Pub/Sub, 每次调用只是注册回调, 不会重复订阅底层 WebSocket
 *  - 高低频分离:
 *      - 高频 (cube_posture / realtime_move / cube_accel / cube_gyro) 走桥接 ref, 不进 React state
 *      - 低频 (solve_saved / session_updated / ...) 走 qc.invalidateQueries
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  connectWS, disconnectWS, subscribe, type WSEventPayload, type Unsubscribe,
} from '@/store/wsStore'

// ─── 高低频事件白名单 ──────────────────────────────
const HIGH_FREQ_EVENTS = new Set<string>([
  'cube_posture',   // 60Hz 四元数
  'realtime_move',  // 智能魔方 push 的单步
  'cube_accel',     // IMU 原始数据
  'cube_gyro',
])

// 低频事件: 自动 invalidate 相关 queryKey
const LOW_FREQ_QUERY_KEYS: Record<string, string[][]> = {
  solve_saved:       [['dashboard'], ['training-today'], ['sessions']],
  session_updated:   [['dashboard'], ['sessions']],
  training_done:     [['dashboard'], ['training-today']],
  device_connected:  [['devices']],
  device_battery:    [['devices']],
}

export interface WSEventHandlers {
  /** 智能魔方 60Hz 四元数 - 默认走 bridge, 不会触发 React 渲染 */
  onPosture?: (q: { x: number; y: number; z: number; w: number }) => void
  /** 单步实时 move */
  onRealtimeMove?: (move: string) => void
  /** 其它低频事件自定义处理 (例如弹 toast) */
  onCustom?: (msg: WSEventPayload) => void
}

export function useWebSocketEvents(
  opts: { userId: number | null },
  handlers: WSEventHandlers = {},
) {
  const qc = useQueryClient()
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const userIdRef = useRef(opts.userId)
  userIdRef.current = opts.userId

  // ── 1) 连接生命周期: 只在 userId 变化时触发, 多次调用此 Hook 不会重建连接 ──
  useEffect(() => {
    if (!opts.userId) return
    connectWS(opts.userId)
    // 注意: 不在卸载时 disconnect, 因为别的组件可能还在用同一条连接
  }, [opts.userId])

  // ── 2) 事件订阅: 注册高低频处理 + 用户自定义 ──
  useEffect(() => {
    const uid = userIdRef.current
    const unsubs: Unsubscribe[] = []

    // 高频事件订阅 (走桥接, 不调 qc.invalidateQueries)
    unsubs.push(subscribe('cube_posture', (msg) => {
      const q = msg.data?.quaternion ?? msg.data
      if (q && window.__cubeBridge?.setPosture) {
        window.__cubeBridge.setPosture(q)
      } else if (q) {
        handlersRef.current.onPosture?.(q)
      }
    }))
    unsubs.push(subscribe('realtime_move', (msg) => {
      const m = msg.data?.move ?? msg.data
      if (typeof m === 'string') {
        if (window.__cubeBridge?.pushRealtimeMove) {
          window.__cubeBridge.pushRealtimeMove(m)
        } else {
          handlersRef.current.onRealtimeMove?.(m)
        }
      }
    }))
    // IMU 原始数据: 不做任何处理, 留着将来订阅 (这里依然走 subscribe 占位)
    for (const ev of ['cube_accel', 'cube_gyro']) {
      unsubs.push(subscribe(ev, () => { /* 暂不处理 */ }))
    }

    // 低频事件订阅: 用通配 '*' 一次性拿到所有消息, 内部判断
    unsubs.push(subscribe('*', (msg) => {
      if (HIGH_FREQ_EVENTS.has(msg.event)) return  // 上面已处理
      // 低频: 触发 query 失效
      if (uid != null) {
        qc.invalidateQueries({ queryKey: ['dashboard', uid] })
        qc.invalidateQueries({ queryKey: ['training-today', uid] })
      }
      const keys = LOW_FREQ_QUERY_KEYS[msg.event]
      if (keys) {
        for (const k of keys) qc.invalidateQueries({ queryKey: k })
      }
      // 用户自定义 hook
      handlersRef.current.onCustom?.(msg)
    }))

    return () => { for (const u of unsubs) u() }
  }, [qc])

  // ── 3) 组件卸载且 userId 仍有效时, 选择性断连 (留作可选, 默认不主动断) ──
  // 如果你希望"整个 App 关闭时断连", 在根组件的 unmount 调用 disconnectWS()
}

// 提供给根组件主动断连
export { disconnectWS }
