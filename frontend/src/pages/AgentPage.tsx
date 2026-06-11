import { useState, useRef, useEffect } from 'react'
import { useAppStore } from '@/store/app'
import { ai } from '@/api/agent'
import { DashboardAPI } from '@/api/client'
import { useT } from '@/i18n'
import { Card, CardTitle, Button, Badge, Blob } from '@/components/ui'
import { Send, Bot, User2, Loader2 } from 'lucide-react'

type Msg = { role: 'user' | 'agent'; text: string; ts: number }

export default function AgentPage() {
  const user = useAppStore(s => s.user)!
  const { t } = useT()
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Msg[]>([
    { role: 'agent', ts: Date.now(), text: t('agent.greeting') },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const sessionIdRef = useRef<number | null>(null)
  sessionIdRef.current = sessionId

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages])

  useEffect(() => {
    DashboardAPI.today(user.id).then(d => setSessionId(d.current_session?.id ?? null))
  }, [user.id, messages])

  const send = async () => {
    const m = input.trim()
    if (!m || sending) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', text: m, ts: Date.now() }])
    setSending(true)
    const placeholderTs = Date.now()
    setMessages(prev => [...prev, { role: 'agent', text: '...', ts: placeholderTs }])
    let acc = ''
    try {
      ai.chatStream(user.id, sessionIdRef.current, m, (ev, data) => {
        if (ev === 'tool_start') acc += `\n[→ ${data.tool}]\n`
        else if (ev === 'tool_result') {
          if (data.result?.error) acc += `  [× ${data.result.error}]\n`
          else acc += `  [✓ got ${Object.keys(data.result || {}).length} fields]\n`
        } else if (ev === 'answer') {
          acc = data.text
        } else if (ev === 'error') {
          acc = `[error] ${data.message}`
        }
        setMessages(prev => prev.map(msg => msg.ts === placeholderTs ? { ...msg, text: acc || '...' } : msg))
      })
    } catch (e: any) {
      setMessages(prev => prev.map(msg => msg.ts === placeholderTs ? { ...msg, text: `[error] ${e?.message || e}` } : msg))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto h-[calc(100vh-200px)] flex flex-col">
      <div className="text-center mb-4">
        <h1 className="font-serif text-3xl md:text-4xl text-foreground">AGENT</h1>
        <p className="text-muted-foreground mt-1 text-sm">Your cubing coach in conversation</p>
      </div>

      <div className="flex items-center gap-2 mb-3">
        <Badge variant="clay" icon={Bot}>model: deepseek-chat</Badge>
        {sessionId && <Badge variant="stone">session #{sessionId}</Badge>}
      </div>

      <div ref={listRef}
           className="flex-1 overflow-y-auto card-organic card-asym-2 p-4 sm:p-6 space-y-3 scrollbar-hide"
           style={{ minHeight: 300 }}>
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div className={`h-9 w-9 rounded-full flex-shrink-0 flex items-center justify-center
                            ${m.role === 'user' ? 'bg-secondary text-white' : 'bg-primary text-white'}`}>
              {m.role === 'user' ? <User2 size={18} /> : <Bot size={18} />}
            </div>
            <div className={`max-w-[78%] px-4 py-3 whitespace-pre-wrap text-sm leading-relaxed
                            ${m.role === 'user'
                              ? 'bg-secondary text-white rounded-[1.5rem] rounded-tr-md'
                              : 'bg-muted/60 text-foreground rounded-[1.5rem] rounded-tl-md'}`}>
              {m.text}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground pl-12">
            <Loader2 size={12} className="animate-spin" /> {t('agent.thinking')}
          </div>
        )}
      </div>

      <div className="flex gap-2 mt-3">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder={t('agent.placeholder')}
          className="input-pill flex-1"
        />
        <Button variant="primary" onClick={send} disabled={sending || !input.trim()}>
          <Send size={16} /> {t('agent.send')}
        </Button>
      </div>
    </div>
  )
}
