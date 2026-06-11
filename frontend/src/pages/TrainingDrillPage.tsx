import { useState, useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { TrainingAPI, FormulasAPI } from '@/api/client'
import { useAppStore } from '@/store/app'
import { useT } from '@/i18n'
import { Card, CardTitle, Button, Badge, ProgressRing, Blob } from '@/components/ui'
import { ArrowLeft, Check, X, Volume2, Play, Pause, Sparkles, BookOpen } from 'lucide-react'
import { type FormulaCase, type TrainingTask } from '@/types/api'

type Mode = 'recognition' | 'slow-lookahead' | 'metronome' | 'default'

function pickMode(t: TrainingTask): Mode {
  if (t.category === 'metronome') return 'metronome'
  if (['pll','oll','f2l'].includes(t.category)) {
    const ids = (t.config as any)[`${t.category}_case_ids`] as number[] | undefined
    if (ids && ids.length > 0) return 'recognition'
  }
  if ((t.config as any).metronome_ms) return 'slow-lookahead'
  return 'default'
}

export default function TrainingDrillPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const user = useAppStore(s => s.user)!
  const nav = useNavigate()
  const { t } = useT()

  const { data: task, isLoading } = useQuery<TrainingTask | undefined>({
    queryKey: ['training-task', taskId],
    queryFn: () => TrainingAPI.today(user.id).then(list => list.find((t: TrainingTask) => t.id === Number(taskId))),
  })

  if (isLoading) return <div className="text-center text-muted-foreground">Loading…</div>
  if (!task) return <Card className="text-center">Task not found</Card>

  const mode = pickMode(task)
  const onDone = async () => {
    await useAppStore.getState().markTaskDone(task.id, { felt: 'completed' })
    nav('/training')
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <button onClick={() => nav('/training')}
              className="flex items-center gap-2 text-muted-foreground hover:text-primary transition-colors">
        <ArrowLeft size={16} /> back
      </button>

      <Card asym={1} className="p-6">
        <div className="flex items-center gap-3 flex-wrap mb-2">
          <Badge variant="clay">{task.category.toUpperCase()}</Badge>
          <Badge variant="stone">{mode}</Badge>
        </div>
        <h2 className="font-serif text-2xl font-bold text-foreground">{task.title}</h2>
        <p className="text-muted-foreground mt-2">{task.description}</p>
      </Card>

      {mode === 'recognition'  && <RecognitionDrill task={task} onDone={onDone} />}
      {mode === 'slow-lookahead' && <SlowLookaheadDrill task={task} onDone={onDone} />}
      {mode === 'metronome'     && <MetronomeDrill task={task} onDone={onDone} />}
      {mode === 'default'       && <DefaultDrill task={task} onDone={onDone} />}
    </div>
  )
}

// ── Recognition ────────────────────────────────
function RecognitionDrill({ task, onDone }: {
  task: TrainingTask
  onDone: (result: { attempts: number; avg_ms: number; correct: number }) => void
}) {
  const setKey = task.category.toUpperCase()
  const caseIds: number[] = (task.config as any)[`${task.category}_case_ids`] || []
  const { data: setDetail } = useQuery({
    queryKey: ['formula-set', setKey],
    queryFn: () => FormulasAPI.set(setKey),
    enabled: caseIds.length > 0,
  })
  const cases: FormulaCase[] = useMemo(() => {
    if (!setDetail) return []
    return setDetail.cases.filter((c: FormulaCase) => caseIds.includes(c.id))
  }, [setDetail, caseIds])
  const [idx, setIdx] = useState(0)
  const [reactionMs, setReactionMs] = useState<number[]>([])
  const [correct, setCorrect] = useState(0)
  const [guess, setGuess] = useState('')
  const shownAtRef = useRef<number>(0)

  useEffect(() => { shownAtRef.current = performance.now(); setGuess('') }, [idx])

  if (cases.length === 0) {
    return <Card className="text-center text-muted-foreground py-8">
      Formula library empty. Run <code className="font-mono">python -m scripts.import_formulas {setKey}</code>
    </Card>
  }

  const cur = cases[idx]
  const firstAlg = cur.algs[0]?.alg_text || ''
  const avgMs = reactionMs.length
    ? Math.round(reactionMs.reduce((a, b) => a + b, 0) / reactionMs.length)
    : 0
  const targetMs = (task.config as any).max_recognition_ms || 500

  const submit = (val: string) => {
    const ms = performance.now() - shownAtRef.current
    setReactionMs(prev => [...prev, ms])
    const wasRight = val.toLowerCase() === cur.code.toLowerCase()
    if (wasRight) setCorrect(c => c + 1)
    if (idx + 1 >= cases.length) {
      const total = [...reactionMs, ms]
      onDone({ attempts: cases.length, avg_ms: Math.round(total.reduce((a,b)=>a+b,0)/total.length), correct: correct + (wasRight ? 1 : 0) })
    } else {
      setIdx(i => i + 1)
    }
  }

  return (
    <Card asym={2} className="p-8 relative overflow-hidden">
      <Blob color="moss" className="!opacity-15 -top-20 -right-20 w-72 h-72 animate-breathe" />

      <div className="flex items-center justify-between mb-4">
        <Badge variant="primary" icon={Sparkles}>{idx + 1} / {cases.length}</Badge>
        <span className="text-xs text-muted-foreground">target ≤ {targetMs}ms</span>
      </div>

      <div className="rounded-[2rem] bg-muted/40 p-6 my-4 space-y-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Recognition</div>
          <div className="text-foreground">{cur.recognition || '—'}</div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">Algorithm</div>
          <code className="font-mono text-sm text-primary">{firstAlg}</code>
        </div>
      </div>

      <input
        autoFocus
        value={guess}
        onChange={e => setGuess(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && guess && submit(guess)}
        placeholder="Enter case code, e.g. Aa / E / OLL 21"
        className="input-pill mb-3"
      />
      <div className="flex gap-2">
        <Button variant="primary" onClick={() => submit(guess)} disabled={!guess}>submit (Enter)</Button>
        <Button variant="ghost" onClick={() => submit('__skip__')}>skip</Button>
      </div>

      <div className="mt-4 flex items-center gap-3 text-sm">
        <Badge variant={correct > idx ? 'success' : 'stone'} icon={Check}>{correct}</Badge>
        <Badge variant="stone" icon={Volume2}>{avgMs}ms avg</Badge>
      </div>
    </Card>
  )
}

// ── Slow lookahead ───────────────────────────────
function SlowLookaheadDrill({ task, onDone }: { task: TrainingTask; onDone: () => void }) {
  const setKey = task.category.toUpperCase()
  const caseIds: number[] = (task.config as any)[`${task.category}_case_ids`] || []
  const { data: setDetail } = useQuery({
    queryKey: ['formula-set', setKey],
    queryFn: () => FormulasAPI.set(setKey),
    enabled: caseIds.length > 0,
  })
  const cases = (setDetail?.cases || []).filter((c: FormulaCase) => caseIds.includes(c.id))
  const [tick, setTick] = useState(0)
  const [running, setRunning] = useState(false)
  const intervalMs = (task.config as any).metronome_ms || 600
  const ref = useRef<number | null>(null)

  useEffect(() => {
    if (running) {
      ref.current = window.setInterval(() => setTick(t => t + 1), intervalMs)
    } else if (ref.current) { clearInterval(ref.current); ref.current = null }
    return () => { if (ref.current) clearInterval(ref.current) }
  }, [running, intervalMs])

  return (
    <Card asym={2} className="p-8 text-center">
      <div className="font-serif text-5xl font-bold tabular-nums text-foreground my-6">
        <div className={`inline-block w-4 h-4 rounded-full mb-3 ${tick % 2 === 0 ? 'bg-primary' : 'bg-muted'}`} />
        <div>tick {tick + 1}</div>
        <div className="text-sm text-muted-foreground mt-1">interval {intervalMs}ms</div>
      </div>
      <div className="flex justify-center gap-3">
        <Button variant="primary" onClick={() => setRunning(r => !r)}>
          {running ? (<><Pause size={16} /> pause</>) : (<><Play size={16} /> start</>)}
        </Button>
        <Button variant="outline" onClick={onDone}>finish</Button>
      </div>

      {cases.length > 0 && (
        <div className="mt-8 text-left">
          <CardTitle icon={BookOpen}>case set</CardTitle>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {cases.map((c: FormulaCase) => (
              <div key={c.id} className="px-3 py-2 rounded-2xl bg-muted/40 border border-border/30">
                <div className="font-bold text-foreground text-sm">{c.code} · {c.name}</div>
                <div className="text-[11px] text-muted-foreground line-clamp-1">{c.recognition || '—'}</div>
                <code className="text-[11px] text-primary">{c.algs[0]?.alg_text || '?'}</code>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  )
}

// ── Metronome ─────────────────────────────────
function MetronomeDrill({ task, onDone }: { task: TrainingTask; onDone: () => void }) {
  const intervalMs = (task.config as any).metronome_ms || 4000
  const count = (task.config as any).count || 25
  const [tick, setTick] = useState(0)
  const [running, setRunning] = useState(false)
  const ref = useRef<number | null>(null)

  useEffect(() => {
    if (running) {
      ref.current = window.setInterval(() => {
        setTick(t => {
          if (t + 1 >= count) {
            if (ref.current) { clearInterval(ref.current); ref.current = null }
            setRunning(false)
            onDone()
          }
          return t + 1
        })
      }, intervalMs)
    }
    return () => { if (ref.current) clearInterval(ref.current) }
  }, [running, intervalMs, count, onDone])

  return (
    <Card asym={3} className="p-8 text-center">
      <div className="my-8">
        <ProgressRing pct={(tick / count) * 100} size={140}
          label={<span className="font-serif text-3xl font-bold">{tick}<span className="text-base text-muted-foreground">/{count}</span></span>} />
        <div className="text-sm text-muted-foreground mt-3">interval {intervalMs}ms</div>
      </div>
      <div className="flex justify-center gap-3">
        <Button variant="primary" onClick={() => setRunning(r => !r)}>
          {running ? <><Pause size={16} /> pause</> : <><Play size={16} /> start</>}
        </Button>
        <Button variant="outline" onClick={onDone}>end</Button>
      </div>
    </Card>
  )
}

// ── Default ───────────────────────────────────
function DefaultDrill({ task, onDone }: { task: TrainingTask; onDone: () => void }) {
  const [count, setCount] = useState(0)
  const target = (task.config as any).count || 10
  return (
    <Card asym={1} className="p-8 text-center">
      <div className="font-serif text-6xl font-bold tabular-nums my-6">{count} / {target}</div>
      <div className="flex justify-center gap-3">
        <Button variant="primary" onClick={() => setCount(c => c + 1)}>+1 solve</Button>
        <Button variant="outline" onClick={onDone} disabled={count < target}>finish</Button>
      </div>
    </Card>
  )
}
