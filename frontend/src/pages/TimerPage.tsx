import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '@/store/app'
import { useT } from '@/i18n'
import { Card, CardTitle, Button, Badge, ProgressRing, Blob, Status } from '@/components/ui'
import { useWebSocketEvents } from '@/hooks/useWebSocketEvents'
import { DevicesAPI } from '@/api/devices'
import { Cube3D, type Cube3DRef } from '@/components/Cube3D'
import {
  Play, Square, RotateCcw, Eye, Sparkles, Cpu, Battery,
} from 'lucide-react'
import type { Device } from '@/api/devices'
import { useRef as _useRef } from 'react'

/**
 * 新 Timer 页 - 走设备链路
 *  - 选定一个 manual/simulator 设备
 *  - 按流程: scramble -> inspect(15s) -> start -> 3D 实时同步 -> 检测复原 -> stop
 *  - 复原检测: 后端 apply_move 时已检测, 收到 cube_state=solved 事件自动 stop
 */
export default function TimerPage() {
  const user = useAppStore(s => s.user)!
  const nav = useNavigate()
  const qc = useQueryClient()
  const { t } = useT()
  const cubeRef = _useRef<Cube3DRef>(null)
  const animTickRef = useRef<number | null>(null)

  useWebSocketEvents({ userId: user.id }, {})

  // 已配对的 simulator/manual 设备
  const { data: devices } = useQuery<Device[]>({
    queryKey: ['devices', user.id],
    queryFn: () => DevicesAPI.list(user.id),
    refetchInterval: 5000,
  })
  const simDevices = (devices || []).filter(d => d.adapter === 'simulator' && d.state !== 'idle')
  const idleDevices = (devices || []).filter(d => d.state === 'idle' && d.adapter === 'simulator')

  const [activeId, setActiveId] = useState<number | null>(null)
  const activeDev = (devices || []).find(d => d.id === activeId) || simDevices[0] || idleDevices[0] || null
  const state = activeDev?.state || 'idle'

  // 本地累计 move (用于 3D 同步)
  const [moveCount, setMoveCount] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const elapsedRef = useRef(0)
  const tickRef = useRef<number | null>(null)
  const sessionStartRef = useRef<number>(0)

  // WS 收到 cube_move -> 3D 同步 + 计数
  const lastEventTsRef = useRef(0)
  useWebSocketEvents({ userId: user.id }, {
    cube_move: (() => {
      // 注意: useWebSocketEvents 的 handler 类型是 ()=>void, 我们走 invalidation 而非 callback
      // 真正 3D 同步靠下方的 ref-based 监听
    }),
  } as any)

  // 单独订阅 WS (避开 useWebSocketEvents 只能注册已知 event 的限制)
  useEffect(() => {
    if (!user) return
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${window.location.host}/ws/user/${user.id}`
    let ws: WebSocket | null = null
    let stopped = false
    const connect = () => {
      if (stopped) return
      ws = new WebSocket(url)
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.event === 'cube_move') {
            // 收到硬件/模拟器 move: 同步 3D + 计数
            const move = msg.data?.move
            if (move) {
              cubeRef.current?.applyMove(move)
              setMoveCount(c => c + 1)
            }
          } else if (msg.event === 'cube_state') {
            // 设备状态变化, 重新拉设备列表
            qc.invalidateQueries({ queryKey: ['devices', user.id] })
            if (msg.data?.state === 'solved') {
              // 复原! 自动 stop
              if (activeDev) DevicesAPI.stop(user.id, activeDev.id)
            }
          } else if (msg.event === 'cube_battery') {
            qc.invalidateQueries({ queryKey: ['devices', user.id] })
          }
        } catch {}
      }
      ws.onclose = () => setTimeout(connect, 1500)
      ws.onerror = () => { ws?.close() }
    }
    connect()
    return () => { stopped = true; ws?.close() }
  }, [user.id, activeDev?.id])

  // 计时器
  useEffect(() => {
    if (state === 'solving') {
      sessionStartRef.current = Date.now()
      tickRef.current = window.setInterval(() => {
        const cur = Date.now() - sessionStartRef.current
        elapsedRef.current = cur
        setElapsed(cur)
      }, 50)
    } else {
      if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
      if (state === 'idle') { setElapsed(0); elapsedRef.current = 0 }
    }
    return () => { if (tickRef.current) clearInterval(tickRef.current) }
  }, [state])

  const onScramble = async () => {
    if (!activeDev) return
    const r = await DevicesAPI.scramble(user.id, activeDev.id)
    setMoveCount(0)
    if (r?.scramble) cubeRef.current?.scramble(r.scramble)
  }
  const onInspect = async () => activeDev && DevicesAPI.inspect(user.id, activeDev.id)
  const onStart = async () => {
    if (!activeDev) return
    await DevicesAPI.start(user.id, activeDev.id)
    sessionStartRef.current = Date.now()
  }
  const onStop = async () => activeDev && DevicesAPI.stop(user.id, activeDev.id)
  const onReset = async () => {
    if (!activeDev) return
    await DevicesAPI.reset(user.id, activeDev.id)
    cubeRef.current?.reset()
    setMoveCount(0); setElapsed(0); elapsedRef.current = 0
  }

  // simulator 下手动触发一个 move (走后端, 让 3D 通过 WS 同步)
  const onManualMove = (move: string) => {
    if (!activeDev || state !== 'solving') return
    DevicesAPI.applyMove(user.id, activeDev.id, move)
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="text-center">
        <h1 className="font-serif text-3xl md:text-4xl text-foreground">{t('nav.timer')}</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          走智能魔方链路 · 3D 同步 · 自动复原检测
        </p>
      </div>

      {/* 设备选择 */}
      <Card asym={1} className="p-5">
        <div className="flex items-center gap-3 flex-wrap">
          <CardTitle icon={Cpu}>Device</CardTitle>
          {!devices || devices.length === 0 ? (
            <div className="flex-1 flex items-center gap-3">
              <span className="text-muted-foreground text-sm">No devices paired</span>
              <Button variant="primary" size="sm" onClick={() => nav('/devices')}>
                pair simulator
              </Button>
            </div>
          ) : (
            <select value={activeId || activeDev?.id || ''}
                    onChange={e => setActiveId(Number(e.target.value))}
                    className="flex-1 h-10 px-4 rounded-full bg-white/50 border border-border/60 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30">
              {[...idleDevices, ...simDevices].map(d => (
                <option key={d.id} value={d.id}>
                  {d.nickname || d.model || d.brand} · {d.state}
                </option>
              ))}
            </select>
          )}
          {activeDev && (
            <>
              <Badge variant={state === 'solving' ? 'success' : state === 'inspecting' ? 'warning' : 'stone'}>
                {state}
              </Badge>
              {activeDev.battery_pct != null && (
                <Badge variant="clay" icon={Battery}>{activeDev.battery_pct}%</Badge>
              )}
            </>
          )}
        </div>
      </Card>

      {/* 3D 魔方 + 计时器 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card asym={2} className="p-6 flex flex-col items-center justify-center min-h-[320px] relative">
          <Blob color="moss" className="!opacity-15 -top-10 -left-10 w-60 h-60 animate-breathe" />
          <div className="relative">
            <Cube3D ref={cubeRef} size={260} />
          </div>
          <div className="mt-4 text-sm text-muted-foreground">
            <StatusBadge state={state} />
          </div>
        </Card>

        <Card asym={3} className="p-6 text-center flex flex-col justify-center">
          <div className="font-serif tabular-nums">
            <div className="text-6xl md:text-7xl font-bold tracking-tighter text-foreground">
              {(elapsed / 1000).toFixed(2)}
              <span className="text-2xl text-muted-foreground ml-2">s</span>
            </div>
            <div className="text-sm text-muted-foreground mt-1">moves {moveCount}</div>
          </div>

          <div className="mt-6 flex justify-center gap-2 flex-wrap">
            {state === 'idle' && (
              <>
                <Button variant="outline" onClick={onScramble} disabled={!activeDev}>
                  <Sparkles size={14} /> scramble
                </Button>
                <Button variant="primary" onClick={onInspect} disabled={!activeDev}>
                  <Eye size={14} /> inspect (15s)
                </Button>
              </>
            )}
            {state === 'inspecting' && (
              <Button variant="primary" onClick={onStart} disabled={!activeDev}>
                <Play size={14} /> start now
              </Button>
            )}
            {state === 'solving' && (
              <Button variant="outline" onClick={onStop} disabled={!activeDev}>
                <Square size={14} /> stop
              </Button>
            )}
            {(state === 'solved' || state === 'solving' || state === 'inspecting') && (
              <Button variant="ghost" onClick={onReset} disabled={!activeDev}>
                <RotateCcw size={14} /> reset
              </Button>
            )}
          </div>

          {/* simulator 下手动录入 move (真硬件无需) */}
          {activeDev && state === 'solving' && (
            <div className="mt-4 flex gap-1.5 flex-wrap justify-center">
              {['R','U','F','L','D','B',"R'","U'","F'",'R2','U2','F2','x','y','z'].map(m => (
                <button key={m} onClick={() => onManualMove(m)}
                        className="h-9 min-w-[40px] px-2.5 rounded-full bg-background border border-border
                                   text-xs font-mono font-semibold hover:border-primary hover:bg-primary/5
                                   transition-all">
                  {m}
                </button>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

function StatusBadge({ state }: { state: string }) {
  const labels: Record<string, string> = {
    idle:       'ready',
    scrambling: 'scrambling…',
    inspecting: 'inspecting (15s)',
    solving:    'solving…',
    solved:     '✓ solved',
  }
  return (
    <span className="font-mono text-xs px-3 py-1 rounded-full bg-muted/60 text-foreground">
      {labels[state] || state}
    </span>
  )
}
