/** AGENT 客户端 - 调用 /api/agent/chat (非流式) + /api/agent/chat/stream (SSE) */
import { api } from './client'

export const ai = {
  chat: (user_id: number, session_id: number | null, message: string) =>
    api.post('/agent/chat', { user_id, session_id, message }).then(r => r.data),

  /**
   * 流式: 回调 (event, data) 逐次被调用
   * - 'tool_start' / 'tool_result'  -> 中间过程
   * - 'answer' -> 最终文本
   * - 'final'  -> 结束
   * - 'error'  -> 失败
   * 返回一个 cancel() 函数
   */
  chatStream: (
    user_id: number, session_id: number | null, message: string,
    onEvent: (event: string, data: any) => void,
  ) => {
    const ctrl = new AbortController()
    fetch('/api/agent/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id, session_id, message }),
      signal: ctrl.signal,
    }).then(async (resp) => {
      if (!resp.body) return
      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buf = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        // SSE: 一次事件由 \n\n 分隔
        let idx
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const chunk = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const lines = chunk.split('\n')
          let ev = 'message', data = ''
          for (const line of lines) {
            if (line.startsWith('event:')) ev = line.slice(6).trim()
            else if (line.startsWith('data:')) data += line.slice(5).trim()
          }
          if (data) {
            try { onEvent(ev, JSON.parse(data)) } catch { onEvent(ev, data) }
          }
        }
      }
    }).catch((e) => onEvent('error', { message: String(e) }))
    return () => ctrl.abort()
  },
}
