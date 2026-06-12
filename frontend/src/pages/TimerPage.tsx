/**
 * TimerPage.tsx ── 统一计时/训练/魔方连接 (cstimer 风格 3-in-1)
 *
 * 布局 (左 1 : 右 1):
 *   ┌─────────────────┬──────────────────────────────┐
 *   │   3D 魔方        │  大字计时器                  │
 *   │   (实时同步)     │  当前打乱                    │
 *   │                  │  训练模块 tab                │
 *   │   状态/电量      │   ├ Cross (十字)             │
 *   │   扫描/MAC 按钮  │   ├ OLL 顶层                 │
 *   └─────────────────┴──────────────────────────────┘
 *
 * 完整流程:
 *   idle → 选/连接魔方 → 自动 scramble (弹打乱) → 15s inspect 倒计时
 *       → start 计时 (旋转魔方开始复原) → 收到 solved → stop + 显示成绩
 *
 * 训练模式:
 *   选定一个 case (PLL/OLL/F2L) → 在右侧显示 alg + 步骤拆解
 *   实时从硬件读 move 计数, 给完成判定 (最佳 N 步)
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAppStore } from '@/store/app'
import { useCubeSnapshot, useCubeStore } from '@/store/cubeStore'
import { useT } from '@/i18n'
import { Card, CardTitle, Button, Input, Badge, Blob } from '@/components/ui'
import { useWebSocketEvents } from '@/hooks/useWebSocketEvents'
import { DevicesAPI } from '@/api/devices'
import { TrainingAPI, FormulasAPI } from '@/api/client'
import { deviceManager } from '@/services/smart-cube'
import { Cube3D, type Cube3DRef } from '@/components/Cube3D'
import {
  Play, Square, RotateCcw, Eye, Sparkles, Bluetooth, Loader2, Cpu, Battery,
  Shuffle, Crosshair, Layers, Grid3X3, Timer, Check, X, Volume2,
} from 'lucide-react'
import type { Device } from '@/api/devices'
import type { FormulaCase, TrainingTask } from '@/types/api'

type TrainMode = 'free' | 'cross' | 'oll' | 'pll' | 'f2l'

interface ScrambleState {
  text: string
  startedAt: number
}

export default function TimerPage() {
  const user = useAppStore(s => s.user)!
  const qc = useQueryClient()
  const { t } = useT()
  const cubeRef = useRef<Cube3DRef>(null)

  useWebSocketEvents({ userId: user.id }, {})

  // ── 设备列表 (BLE 扫描出来的硬件 + simulator) ──
  const { data: devices } = useQuery<Device[]>({
    queryKey: ['devices', user.id],
    queryFn: () => DevicesAPI.list(user.id),
    refetchInterval: 5000,
  })
  const allDevices = devices || []
  const activeDev = allDevices.find(d => d.state !== 'idle') || allDevices.find(d => d.state === 'idle') || null
  const state = activeDev?.state || 'idle'

  // ── 唯一连接状态源: useCubeStore (BLE 真实硬件) ──
  // 这里 status/brand/deviceName/battery 全部由 registerCubeBridge 写入,
  // 不再各自读 scanState / allDevices / scanErr, 避免出现"左下角已连接, 3D 下方未连接"的不一致.
  const cubeSnap = useCubeSnapshot()
  const bleConnected = cubeSnap.status === 'connected'
  const setCubeFacelet = useCubeStore(s => s._setFacelet)

  // ── 训练模块 ──
  const { data: trainingTasks = [] } = useQuery<TrainingTask[]>({
    queryKey: ['training-today', user.id],
    queryFn: () => TrainingAPI.today(user.id),
  })
  const [trainMode, setTrainMode] = useState<TrainMode>('free')
  const [selectedCase, setSelectedCase] = useState<FormulaCase | null>(null)

  // ── 计时 + 打乱状态 ──
  const [scramble, setScramble] = useState<ScrambleState | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [moveCount, setMoveCount] = useState(0)
  const [inspectLeft, setInspectLeft] = useState(0)
  const [solvedTime, setSolvedTime] = useState<number | null>(null)  // 完成时间
  const [history, setHistory] = useState<Array<{ time: number; scramble: string; date: string }>>([])

  const elapsedRef = useRef(0)
  const sessionStartRef = useRef(0)
  const tickRef = useRef<number | null>(null)
  const inspectTickRef = useRef<number | null>(null)

  // ── 蓝牙/MAC 配对状态 ──
  const [scanState, setScanState] = useState<'idle' | 'scanning' | 'success' | 'error'>('idle')
  const [scanErr, setScanErr] = useState<string | null>(null)
  const [macInput, setMacInput] = useState('')

  // ── 自动开始 scramble: 设备状态从 idle 变到 ready (后端 create 之后 connect 自动到 ready) ──
  const lastStateRef = useRef<string>('idle')
  useEffect(() => {
    // 新设备刚连上 -> 自动 scramble
    if (lastStateRef.current !== 'idle' && state === 'idle' && activeDev) {
      // skip; 已经在 idle
    }
    if (lastStateRef.current === 'idle' && state !== 'idle' && activeDev) {
      // 设备刚被 connect -> 不自动 scramble, 等用户点
    }
    lastStateRef.current = state
  }, [state, activeDev?.id])

  // ── 计时器 (state === 'solving') ──
  useEffect(() => {
    if (state === 'solving') {
      if (sessionStartRef.current === 0) sessionStartRef.current = Date.now()
      tickRef.current = window.setInterval(() => {
        const cur = Date.now() - sessionStartRef.current
        elapsedRef.current = cur
        setElapsed(cur)
      }, 50)
    } else {
      if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
      if (state === 'idle') {
        setElapsed(0); elapsedRef.current = 0; sessionStartRef.current = 0
      }
    }
    return () => { if (tickRef.current) clearInterval(tickRef.current) }
  }, [state])

  // ── 15s inspect 倒计时 ──
  useEffect(() => {
    if (state === 'inspecting') {
      setInspectLeft(15)
      inspectTickRef.current = window.setInterval(() => {
        setInspectLeft(prev => {
          if (prev <= 1) {
            // 自动 start
            if (activeDev) {
              DevicesAPI.start(user.id, activeDev.id).catch(() => {})
              sessionStartRef.current = Date.now()
            }
            if (inspectTickRef.current) { clearInterval(inspectTickRef.current); inspectTickRef.current = null }
            return 0
          }
          return prev - 1
        })
      }, 1000)
    } else {
      if (inspectTickRef.current) { clearInterval(inspectTickRef.current); inspectTickRef.current = null }
      if (state !== 'inspecting') setInspectLeft(0)
    }
    return () => { if (inspectTickRef.current) clearInterval(inspectTickRef.current) }
  }, [state, activeDev?.id])

  // ── WS 实时事件 (cube_move / cube_state / cube_battery) ──
  useEffect(() => {
    if (!user) return
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host || '127.0.0.1:8000'
    const url = `${proto}//${host}/ws/user/${user.id}`
    let ws: WebSocket | null = null
    let stopped = false
    let reconnectTimer: any = null
    const connect = () => {
      if (stopped) return
      try {
        ws = new WebSocket(url)
      } catch {
        reconnectTimer = setTimeout(connect, 2000)
        return
      }
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.event === 'cube_move') {
            const move = msg.data?.move
            if (move) {
              cubeRef.current?.applyMove(move)
              setMoveCount(c => c + 1)
            }
          } else if (msg.event === 'cube_state') {
            qc.invalidateQueries({ queryKey: ['devices', user.id] })
            // 复原 -> 自动 stop + 记录成绩
            if (msg.data?.state === 'solved' && state === 'solving') {
              const finalTime = Date.now() - sessionStartRef.current
              setSolvedTime(finalTime)
              setHistory(h => [{
                time: finalTime,
                scramble: scramble?.text || '',
                date: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
              }, ...h].slice(0, 10))
              if (activeDev) DevicesAPI.stop(user.id, activeDev.id).catch(() => {})
            }
          } else if (msg.event === 'cube_battery') {
            qc.invalidateQueries({ queryKey: ['devices', user.id] })
          }
        } catch {}
      }
      ws.onclose = () => {
        if (!stopped) reconnectTimer = setTimeout(connect, 2000)
      }
      ws.onerror = () => { try { ws?.close() } catch {} }
    }
    connect()
    return () => {
      stopped = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      try { ws?.close() } catch {}
      try { cubeRef.current?.dispose() } catch {}
    }
  }, [user.id, activeDev?.id, state, scramble?.text])

  // ── Action handlers ──
  const onScanBluetooth = async () => {
    if (!('bluetooth' in navigator)) {
      setScanErr('当前浏览器不支持 Web Bluetooth, 请用 Chrome / Edge')
      setScanState('error')
      return
    }
    setScanState('scanning')
    setScanErr(null)
    try {
      const adapter = await deviceManager.scanAndConnect()
      setScanState('success')
      console.log('[BLE] connected:', adapter.info)
      qc.invalidateQueries({ queryKey: ['devices', user.id] })
    } catch (e: any) {
      if (e?.name === 'NotFoundError') { setScanState('idle'); return }
      setScanErr(e?.message || '扫描失败')
      setScanState('error')
    }
  }

  const onPairByMac = async () => {
    const mac = macInput.trim()
    if (!mac) return
    try {
      const d = await DevicesAPI.create(user.id, {
        brand: 'gan', mac_address: mac, protocol: 'gan_v4', adapter: 'simulator',
      })
      setMacInput('')
      // 自动 connect (simulator 设备在 backend 会变成 idle 可用)
      await DevicesAPI.connect(user.id, d.id).catch(() => {})
      qc.invalidateQueries({ queryKey: ['devices', user.id] })
    } catch (e: any) {
      setScanErr(e?.response?.data?.detail || e?.message || '配对失败')
      setScanState('error')
    }
  }

  // 自动 scramble + inspect 流程
  const onScramble = async () => {
    if (!activeDev) return
    try {
      const r = await DevicesAPI.scramble(user.id, activeDev.id)
      if (r?.scramble) {
        setScramble({ text: r.scramble, startedAt: Date.now() })
        cubeRef.current?.scramble(r.scramble)
        setMoveCount(0)
        setSolvedTime(null)
        // 打乱完成后, 后端会让设备进入 ready 状态; 这里我们等 0.5s 再触发 inspect
        setTimeout(() => {
          if (activeDev) DevicesAPI.inspect(user.id, activeDev.id).catch(() => {})
        }, 500)
      }
    } catch (e: any) {
      console.error('[scramble]', e)
    }
  }

  const onStart = async () => {
    if (!activeDev) return
    await DevicesAPI.start(user.id, activeDev.id).catch(() => {})
    sessionStartRef.current = Date.now()
  }

  const onStop = async () => {
    if (!activeDev) return
    const finalTime = elapsedRef.current
    if (state === 'solving' && finalTime > 0) {
      setSolvedTime(finalTime)
      setHistory(h => [{
        time: finalTime,
        scramble: scramble?.text || '',
        date: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      }, ...h].slice(0, 10))
    }
    await DevicesAPI.stop(user.id, activeDev.id).catch(() => {})
  }

  const onReset = async () => {
    if (!activeDev) return
    await DevicesAPI.reset(user.id, activeDev.id).catch(() => {})
    cubeRef.current?.reset()
    setMoveCount(0); setElapsed(0); elapsedRef.current = 0
    setSolvedTime(null); setScramble(null); setInspectLeft(0)
  }

  // simulator 手动录入 move
  const onManualMove = (move: string) => {
    if (!activeDev || state !== 'solving') return
    DevicesAPI.applyMove(user.id, activeDev.id, move).catch(() => {})
  }

  // ── 训练模块: 根据 mode 拉 formula set ──
  const { data: formulaSets = [] } = useQuery<any[]>({
    queryKey: ['formula-sets'],
    queryFn: () => FormulasAPI.sets(),
  })
  const modeSetCode = trainMode === 'pll' ? 'pll' : trainMode === 'oll' ? 'oll' : trainMode === 'f2l' ? 'f2l' : null
  const modeSet = useMemo(() => formulaSets.find(s => s.code === modeSetCode), [formulaSets, modeSetCode])
  const modeCases: FormulaCase[] = modeSet?.cases || []

  // ── 渲染 ──
  return (
    <div className="space-y-4 max-w-7xl mx-auto">
      {/* 顶栏: 模式选择 + 历史成绩 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-serif text-2xl md:text-3xl text-foreground">
            计时 · 训练 · 魔方
          </h1>
          <p className="text-muted-foreground text-xs mt-0.5">
            cstimer 风格 · 3D 实时同步 · 自动复原检测
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {history.length > 0 && (
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-muted-foreground">本轮最佳</span>
              <Badge variant="clay">{(Math.min(...history.map(h => h.time)) / 1000).toFixed(2)}s</Badge>
              <span className="text-muted-foreground">· 平均</span>
              <Badge variant="stone">{(history.reduce((a, b) => a + b.time, 0) / history.length / 1000).toFixed(2)}s</Badge>
            </div>
          )}
        </div>
      </div>

      {/* 主体两栏 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* ── 左: 3D 魔方 + 设备控制 ── */}
        <Card asym={1} className="p-4 flex flex-col gap-3 relative">
          <Blob color="moss" className="!opacity-15 -top-10 -left-10 w-60 h-60 animate-breathe" />
          <div className="flex items-center justify-between">
            <CardTitle icon={Bluetooth}>3D 魔方</CardTitle>
            {activeDev && (
              <div className="flex items-center gap-1.5">
                <Badge variant={state === 'solving' ? 'success' : state === 'inspecting' ? 'warning' : 'stone'}>
                  {state}
                </Badge>
                {activeDev.battery_pct != null && <Badge variant="clay" icon={Battery}>{activeDev.battery_pct}%</Badge>}
              </div>
            )}
          </div>

          {/* 3D 魔方 */}
          <div className="relative flex items-center justify-center" style={{ minHeight: 380 }}>
            <Cube3D ref={cubeRef} size={360} />
            {/* 浮层: 复原成绩 */}
            {solvedTime != null && (
              <div className="absolute top-2 left-1/2 -translate-x-1/2 bg-success/15 backdrop-blur px-4 py-2 rounded-2xl shadow-soft animate-fade-in">
                <div className="text-xs text-muted-foreground text-center">本次成绩</div>
                <div className="text-2xl font-serif font-bold text-success tabular-nums">{(solvedTime / 1000).toFixed(2)}s</div>
                <div className="text-[10px] text-muted-foreground text-center">{moveCount} 步</div>
              </div>
            )}
            {/* 浮层: 15s inspect 倒计时 */}
            {state === 'inspecting' && (
              <div className="absolute inset-0 bg-warning/15 backdrop-blur-sm flex items-center justify-center rounded-2xl">
                <div className="text-center">
                  <div className="text-xs text-muted-foreground uppercase tracking-widest">Inspecting</div>
                  <div className="text-6xl font-serif font-bold text-warning tabular-nums">{inspectLeft}</div>
                  <div className="text-xs text-muted-foreground mt-1">观察期 · {inspectLeft > 0 ? '记得预判 F2L 思路' : '开始!'}</div>
                </div>
              </div>
            )}
          </div>

          {/* 设备状态: 唯一来源 = bleConnected (cubeStore.status) + scanState (扫描中) */}
          <div className="flex items-center gap-2 text-xs">
            <Cpu size={14} className={bleConnected ? 'text-success' : 'text-muted-foreground'} />
            <span className={`font-medium truncate ${bleConnected ? 'text-success' : 'text-muted-foreground'}`}>
              {bleConnected
                ? (cubeSnap.deviceName || '已连接')
                : scanState === 'scanning' ? '扫描中…'
                : scanState === 'error' ? '连接失败'
                : '暂未连接魔方'}
            </span>
            {bleConnected && cubeSnap.battery != null && (
              <Badge variant="clay" icon={Battery}>{cubeSnap.battery}%</Badge>
            )}
          </div>

          {/* 蓝牙扫描 + MAC 输入 (折叠在一行) */}
          <div className="flex items-center gap-2 flex-wrap">
            <Input
              value={macInput}
              onChange={e => setMacInput(e.target.value)}
              placeholder="MAC 地址 (AA:BB:CC:DD:EE:FF)"
              className="flex-1 min-w-[140px] h-8 text-xs font-mono"
              onKeyDown={e => e.key === 'Enter' && onPairByMac()}
            />
            <Button variant="outline" size="sm" onClick={onPairByMac} disabled={!macInput.trim()} className="h-8 text-xs">
              按 MAC
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={onScanBluetooth}
              disabled={scanState === 'scanning'}
              className="h-8 text-xs"
            >
              {scanState === 'scanning' ? (
                <><Loader2 size={12} className="animate-spin" /> 扫描中</>
              ) : (
                <><Bluetooth size={12} /> 扫描</>
              )}
            </Button>
          </div>
          {scanErr && <div className="text-xs text-destructive">⚠ {scanErr}</div>}
        </Card>

        {/* ── 右: 计时 + 打乱 + 训练 ── */}
        <div className="flex flex-col gap-4">
          {/* 计时 + 打乱 */}
          <Card asym={2} className="p-6 flex flex-col items-center">
            <CardTitle icon={Timer}>计时</CardTitle>
            <div className="font-serif tabular-nums my-2">
              <div className="text-7xl md:text-8xl font-bold tracking-tighter text-foreground">
                {(elapsed / 1000).toFixed(2)}
                <span className="text-2xl text-muted-foreground ml-2">s</span>
              </div>
              <div className="text-sm text-muted-foreground text-center">步数 {moveCount}</div>
            </div>

            {/* 当前打乱 */}
            <div className="w-full mt-3 min-h-[60px]">
              {scramble ? (
                <div className="bg-muted/40 rounded-2xl p-3 text-center">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-widest mb-1">打乱</div>
                  <div className="font-mono text-sm font-semibold text-foreground break-all leading-relaxed">
                    {scramble.text}
                  </div>
                </div>
              ) : (
                <div className="bg-muted/20 rounded-2xl p-3 text-center text-muted-foreground text-xs">
                  点 "打乱" 开始一把
                </div>
              )}
            </div>

            {/* 操作按钮 */}
            <div className="mt-3 flex justify-center gap-2 flex-wrap">
              {state === 'idle' && (
                <>
                  <Button variant="primary" onClick={onScramble} disabled={!activeDev}>
                    <Shuffle size={14} /> 打乱
                  </Button>
                </>
              )}
              {state === 'inspecting' && (
                <Button variant="primary" onClick={onStart} disabled={!activeDev}>
                  <Play size={14} /> 直接开始
                </Button>
              )}
              {state === 'solving' && (
                <Button variant="outline" onClick={onStop} disabled={!activeDev}>
                  <Square size={14} /> 停止
                </Button>
              )}
              {(state === 'solved' || state === 'solving' || state === 'inspecting' || state === 'idle') && (
                <Button variant="ghost" onClick={onReset} disabled={!activeDev}>
                  <RotateCcw size={14} /> 重置
                </Button>
              )}
            </div>

            {/* simulator 手动录入 */}
            {activeDev && state === 'solving' && (
              <div className="mt-3 flex gap-1 flex-wrap justify-center">
                {['R','U','F','L','D','B',"R'","U'","F'",'R2','U2','F2','x','y','z'].map(m => (
                  <button key={m} onClick={() => onManualMove(m)}
                          className="h-7 min-w-[32px] px-2 rounded-full bg-background border border-border
                                     text-[10px] font-mono font-semibold hover:border-primary hover:bg-primary/5">
                    {m}
                  </button>
                ))}
              </div>
            )}
          </Card>

          {/* 训练模块 tab */}
          <Card asym={3} className="p-4">
            <CardTitle icon={Sparkles}>训练</CardTitle>
            {/* tab bar */}
            <div className="mt-3 flex items-center gap-1 flex-wrap">
              {([
                ['free', '自由', Play],
                ['cross', '十字', Crosshair],
                ['f2l', 'F2L', Layers],
                ['oll', 'OLL', Grid3X3],
                ['pll', 'PLL', Grid3X3],
              ] as const).map(([m, label, Icon]) => (
                <button
                  key={m}
                  onClick={() => { setTrainMode(m); setSelectedCase(null) }}
                  className={`h-8 px-3 rounded-full text-xs font-medium flex items-center gap-1.5
                              ${trainMode === m
                                ? 'bg-primary text-primary-foreground shadow-soft'
                                : 'bg-muted/50 text-muted-foreground hover:bg-muted'}`}
                >
                  <Icon size={12} /> {label}
                </button>
              ))}
            </div>

            {/* tab content */}
            <div className="mt-3">
              {trainMode === 'free' ? (
                <FreeMode
                  moveCount={moveCount}
                  elapsed={elapsed}
                  onStart={onStart}
                  onStop={onStop}
                  onReset={onReset}
                  state={state}
                />
              ) : (
                <TrainModePanel
                  mode={trainMode}
                  cases={modeCases}
                  selected={selectedCase}
                  onSelect={setSelectedCase}
                />
              )}
            </div>
          </Card>

          {/* 历史成绩 */}
          {history.length > 0 && (
            <Card asym={1} className="p-4">
              <CardTitle icon={Timer}>本轮历史</CardTitle>
              <div className="mt-2 space-y-1.5 max-h-40 overflow-y-auto">
                {history.map((h, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-full bg-muted/30">
                    <span className="text-muted-foreground w-12">{h.date}</span>
                    <span className="font-mono font-semibold tabular-nums w-16">{(h.time / 1000).toFixed(2)}s</span>
                    <span className="text-muted-foreground truncate flex-1">{h.scramble.slice(0, 30)}…</span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

// ── 自由模式 ──
function FreeMode({ moveCount, elapsed, onStart, onStop, onReset, state }: any) {
  const avgTPS = moveCount > 0 ? (moveCount / (elapsed / 1000)).toFixed(2) : '0.00'
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2 text-center">
        <Stat label="moves" value={String(moveCount)} />
        <Stat label="time" value={`${(elapsed / 1000).toFixed(2)}s`} />
        <Stat label="TPS" value={avgTPS} />
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        自由模式: 不限定 case, 适合热身或新算法试拧. 转动魔方即可累计步数, 时间从第一次 move 开始.
      </p>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-muted/40 rounded-2xl p-2">
      <div className="text-[10px] text-muted-foreground uppercase">{label}</div>
      <div className="font-mono font-semibold text-sm tabular-nums">{value}</div>
    </div>
  )
}

// ── 训练模式 (cross / oll / pll / f2l) ──
function TrainModePanel({ mode, cases, selected, onSelect }: {
  mode: TrainMode
  cases: FormulaCase[]
  selected: FormulaCase | null
  onSelect: (c: FormulaCase) => void
}) {
  const modeLabel: Record<TrainMode, string> = { free: '自由', cross: '十字', oll: 'OLL', pll: 'PLL', f2l: 'F2L' }
  if (mode === 'free') return null
  if (cases.length === 0) {
    const label = modeLabel[mode]
    return (
      <div className="text-xs text-muted-foreground text-center py-4">
        加载 {label} cases 中… 或后端未 seed
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-1.5 max-h-48 overflow-y-auto">
        {cases.map(c => (
          <button
            key={c.id}
            onClick={() => onSelect(c)}
            className={`px-2 py-1.5 rounded-full text-[10px] font-mono font-semibold
                        ${selected?.id === c.id
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted/40 text-foreground hover:bg-muted'}`}
          >
            {c.code}
          </button>
        ))}
      </div>
      {selected && (
        <div className="bg-muted/30 rounded-2xl p-3 mt-2">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-[10px] text-muted-foreground uppercase">{modeLabel[mode]}</span>
            <span className="font-mono font-semibold text-sm">{selected.code}</span>
          </div>
          {selected.recognition && (
            <div className="text-xs text-foreground/80 mb-1.5">
              <span className="text-muted-foreground">识别:</span> {selected.recognition}
            </div>
          )}
          <div className="font-mono text-sm font-semibold text-primary break-all leading-relaxed">
            {selected.algs?.[0]?.alg_text || '—'}
          </div>
          <div className="mt-1.5 text-[10px] text-muted-foreground">
            步数 {selected.algs?.[0]?.move_count ?? selected.algs?.[0]?.alg_text?.split(/\s+/).filter(Boolean).length ?? 0} · 在 3D 魔方上拧一次这个 alg
          </div>
        </div>
      )}
    </div>
  )
}
