/**
 * store/wsStore.ts ── 全局唯一 WebSocket 单例 + Pub/Sub
 *
 * 设计目标:
 *  - 整个应用只维护一条 WebSocket 连接, 避免 useWebSocketEvents 被多次调用
 *    导致的多连接风暴 (反模式)
 *  - 内部封装: Connect / Reconnect (指数退避) / Heartbeat / Close
 *  - 暴露 connect(userId) / disconnect() / subscribe(event, handler)
 *  - 不依赖 React, 可在任意模块直接 import
 *  - 状态 (status / lastEventAt) 走 zustand, 组件用 selector 订阅
 *
 * 高低频分离仍在订阅端完成 (hooks/useWebSocketEvents.ts):
 *  - subscribe 时回调会拿到原始 msg, 订阅方自行判断高频/低频
 */
import { create } from 'zustand'
import { useShallow } from 'zustand/react/shallow'

export type WSStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

export interface WSEventPayload {
  event: string
  ts: number
  data: any
}

export type WSEventHandler = (msg: WSEventPayload) => void
export type Unsubscribe = () => void

interface WSStoreState {
  status: WSStatus
  userId: number | null
  lastEventAt: number | null
  reconnectAttempts: number

  // ── 内部动作, 组件不需要直接调用 ──
  _setStatus: (s: WSStatus) => void
  _setUserId: (id: number | null) => void
  _touch: (ts: number) => void
  _incAttempts: () => void
  _resetAttempts: () => void
}

// ── Pub/Sub: 事件总线, 与 React 解耦 ──────────────────
type Topic = string  // WSEvent 字符串, 也支持 '*' 通配
const subscribers = new Map<Topic, Set<WSEventHandler>>()

function publish(msg: WSEventPayload) {
  const direct = subscribers.get(msg.event)
  if (direct) for (const h of direct) {
    try { h(msg) } catch (e) { console.error('[ws] handler error', e) }
  }
  const wildcard = subscribers.get('*')
  if (wildcard) for (const h of wildcard) {
    try { h(msg) } catch (e) { console.error('[ws] handler error', e) }
  }
}

export function subscribe(topic: Topic, handler: WSEventHandler): Unsubscribe {
  let set = subscribers.get(topic)
  if (!set) { set = new Set(); subscribers.set(topic, set) }
  set.add(handler)
  return () => {
    set!.delete(handler)
    if (set!.size === 0) subscribers.delete(topic)
  }
}

// ── 单例连接状态 ──────────────────────────────────────
let ws: WebSocket | null = null
let retryDelay = 1000
let heartbeatTimer: number | null = null
let currentUserId: number | null = null
let manuallyClosed = false

function clearHeartbeat() {
  if (heartbeatTimer != null) {
    window.clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

function startHeartbeat(send: () => void) {
  clearHeartbeat()
  heartbeatTimer = window.setInterval(() => {
    // ws readyState 1=OPEN
    if (ws && ws.readyState === 1) {
      try { send() } catch { /* ignore */ }
    }
  }, 25_000)  // < nginx 默认 60s
}

function connect(userId: number, store: WSStoreState) {
  // 已存在且未关闭: 不重建
  if (ws && (ws.readyState === 0 || ws.readyState === 1) && currentUserId === userId) {
    return
  }
  disconnect()  // 切换 userId / 重连

  currentUserId = userId
  manuallyClosed = false
  store._setUserId(userId)
  store._setStatus('connecting')

  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host  = window.location.host
  const url   = `${proto}//${host}/ws/user/${userId}`

  const sock = new WebSocket(url)
  ws = sock

  sock.onopen = () => {
    retryDelay = 1000
    store._resetAttempts()
    store._setStatus('open')
    startHeartbeat(() => { try { sock.send('ping') } catch { /* ignore */ } })
  }

  sock.onmessage = (e) => {
    let msg: WSEventPayload
    try { msg = JSON.parse(e.data) }
    catch { return }
    store._touch(Date.now())
    publish(msg)  // 派发给所有订阅者
  }

  sock.onerror = () => {
    store._setStatus('error')
  }

  sock.onclose = () => {
    clearHeartbeat()
    ws = null
    store._setStatus('closed')
    if (manuallyClosed || currentUserId !== userId) return
    // 指数退避重连, 上限 30s
    store._incAttempts()
    window.setTimeout(() => connect(userId, store), retryDelay)
    retryDelay = Math.min(retryDelay * 2, 30_000)
  }
}

function disconnect() {
  manuallyClosed = true
  clearHeartbeat()
  if (ws) {
    try { ws.close() } catch { /* ignore */ }
    ws = null
  }
  currentUserId = null
  useWSStore.getState()._setUserId(null)
  useWSStore.getState()._setStatus('idle')
}

// ── zustand 状态 (低频, 几秒变一次) ──────────────────
export const useWSStore = create<WSStoreState>((set) => ({
  status: 'idle',
  userId: null,
  lastEventAt: null,
  reconnectAttempts: 0,

  _setStatus: (s)  => set({ status: s }),
  _setUserId: (id) => set({ userId: id }),
  _touch:      (ts) => set({ lastEventAt: ts }),
  _incAttempts: () => set(st => ({ reconnectAttempts: st.reconnectAttempts + 1 })),
  _resetAttempts: () => set({ reconnectAttempts: 0 }),
}))

// ── 对外 API ─────────────────────────────────────────
export function connectWS(userId: number) {
  connect(userId, useWSStore.getState())
}

export function disconnectWS() {
  disconnect()
}

// ── 便捷 selector hook (使用 useShallow 避免渲染雪崩) ───
// 组件用: const { status } = useWSSnapshot()
export function useWSSnapshot() {
  return useWSStore(
    useShallow(s => ({
      status: s.status,
      userId: s.userId,
      lastEventAt: s.lastEventAt,
    })),
  )
}
