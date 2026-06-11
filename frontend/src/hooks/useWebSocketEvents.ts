/**
 * 订阅后端 ws_manager 的 WebSocket 事件, 触发 react-query 失效
 *
 * 用法:
 *   useWebSocketEvents({ userId }, {
 *     onMove:    () => qc.invalidateQueries({ queryKey: ['dashboard', userId] }),
 *     onSolve:   () => qc.invalidateQueries({ queryKey: ['dashboard', userId] }),
 *     onSession: () => qc.invalidateQueries({ queryKey: ['dashboard', userId] }),
 *     onAI:      () => qc.invalidateQueries({ queryKey: ['dashboard', userId] }),
 *   })
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

export type WSEvent = string
export interface WSEventPayload {
  event: WSEvent
  ts: number
  data: any
}

export function useWebSocketEvents(
  opts: { userId: number | null },
  handlers: Partial<Record<WSEvent, () => void>>,
) {
  const qc = useQueryClient()
  const wsRef = useRef<WebSocket | null>(null)
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  useEffect(() => {
    if (!opts.userId) return

    // dev 走 vite proxy, prod 走同源
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host  // 含端口
    const url = `${proto}//${host}/ws/user/${opts.userId}`

    let stopped = false
    let retryDelay = 1000

    const connect = () => {
      if (stopped) return
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        retryDelay = 1000  // 重置
        // 触发一个 ping
        try { ws.send('ping') } catch {}
      }
      ws.onmessage = (e) => {
        try {
          const msg: WSEventPayload = JSON.parse(e.data)
          // 任意事件 -> 默认 invalidate dashboard (简化: 跟用户相关的查一次就行)
          qc.invalidateQueries({ queryKey: ['dashboard', opts.userId] })
          qc.invalidateQueries({ queryKey: ['training-today', opts.userId] })
          // 用户注册的事件 handler
          const h = handlersRef.current[msg.event]
          if (h) h()
        } catch { /* ignore */ }
      }
      ws.onclose = () => {
        if (stopped) return
        setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 30_000)
      }
      ws.onerror = () => { ws.close() }
    }

    connect()
    return () => {
      stopped = true
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [opts.userId, qc])
}
