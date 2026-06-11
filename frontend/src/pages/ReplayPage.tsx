import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { SessionsAPI } from '@/api/client'
import { useAppStore } from '@/store/app'
import { useT } from '@/i18n'
import { Card, CardTitle, Button, Badge } from '@/components/ui'
import { RotateCcw, ChevronDown, ChevronUp, Download, BarChart3, Hourglass } from 'lucide-react'

const STAGE_COLORS: Record<string, string> = {
  cross: 'bg-[#38bdf8]/80 text-[#0c4a6e]',
  f2l:   'bg-[#a78bfa]/80 text-[#4c1d95]',
  oll:   'bg-[#f472b6]/80 text-[#831843]',
  pll:   'bg-[#34d399]/80 text-[#064e3b]',
}

function downloadCsv(url: string) {
  const a = document.createElement('a')
  a.href = url; a.download = ''
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
}

function fmt(ms: number | null | undefined): string {
  if (ms == null) return '—'
  return (ms / 1000).toFixed(2) + 's'
}

function Stat({ label, value, accent = 'primary' }: { label: string; value: any; accent?: 'primary' | 'clay' }) {
  return (
    <div className={`px-3 py-2.5 rounded-2xl ${accent === 'clay' ? 'bg-secondary/10' : 'bg-primary/8'} text-center`}>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-serif text-base sm:text-lg font-semibold text-foreground tabular-nums">{value}</div>
    </div>
  )
}

export default function ReplayPage() {
  const user = useAppStore(s => s.user)!
  const [params, setParams] = useSearchParams()
  const sidParam = params.get('session')
  const [activeSid, setActiveSid] = useState<number | null>(sidParam ? Number(sidParam) : null)
  const [expandedSolve, setExpandedSolve] = useState<number | null>(null)
  const { t } = useT()

  const sessionsQ = useQuery({
    queryKey: ['sessions', user.id],
    queryFn: () => SessionsAPI.list(user.id),
  })

  const replayQ = useQuery({
    queryKey: ['replay', activeSid],
    queryFn: () => fetch(`/api/sessions/${activeSid}/replay`).then(r => r.json()),
    enabled: activeSid != null,
  })

  useEffect(() => {
    if (sidParam) setActiveSid(Number(sidParam))
  }, [sidParam])

  const onPickSession = (id: number) => {
    setActiveSid(id)
    setParams({ session: String(id) })
    setExpandedSolve(null)
  }

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="font-serif text-3xl md:text-4xl text-foreground">{t('replay.title')}</h1>
        <p className="text-muted-foreground mt-1">Pick a session to review</p>
      </div>

      {/* Session 选择 */}
      <Card asym={2} className="flex items-center gap-3 flex-wrap">
        <span className="text-sm text-muted-foreground">{t('replay.select')}:</span>
        <select
          value={activeSid ?? ''}
          onChange={e => onPickSession(Number(e.target.value))}
          className="flex-1 min-w-[200px] h-10 px-4 rounded-full bg-white/50 border border-border/60 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          <option value="">—</option>
          {sessionsQ.data?.map((s: any) => (
            <option key={s.id} value={s.id}>
              #{s.id} · {s.cube_count}/{s.target_size} · {s.status}
            </option>
          ))}
        </select>
        {activeSid && (
          <Button variant="primary" size="sm" onClick={() => downloadCsv(`/api/sessions/${activeSid}/export.csv`)}>
            <Download size={14} /> {t('replay.export_csv')}
          </Button>
        )}
      </Card>

      {!activeSid && (
        <Card className="text-center py-12">
          <RotateCcw size={36} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-muted-foreground">{t('replay.no_session')}</p>
        </Card>
      )}

      {replayQ.data && (
        <>
          {/* 总览 */}
          <Card asym={1}>
            <CardTitle icon={BarChart3}>Overview</CardTitle>
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
              <Stat label="count" value={replayQ.data.stats?.solve_count ?? 0} />
              <Stat label="avg3" value={fmt(replayQ.data.stats?.avg3_ms)} />
              <Stat label="avg5" value={fmt(replayQ.data.stats?.avg5_ms)} />
              <Stat label="avg12" value={fmt(replayQ.data.stats?.avg12_ms)} />
              <Stat label="best" value={fmt(replayQ.data.stats?.best_ms)} accent="clay" />
              <Stat label="cross" value={fmt(replayQ.data.stats?.avg_cross_ms)} />
              <Stat label="f2l" value={fmt(replayQ.data.stats?.avg_f2l_ms)} />
              <Stat label="oll" value={fmt(replayQ.data.stats?.avg_oll_ms)} />
              <Stat label="pll" value={fmt(replayQ.data.stats?.avg_pll_ms)} />
              <Stat label="speed" value={(replayQ.data.stats?.speed_trend ?? 1).toFixed(2)} accent="clay" />
            </div>
          </Card>

          {/* AI 摘要 */}
          {replayQ.data.ai_report && (
            <Card asym={3}>
              <CardTitle icon={Hourglass}>AI Summary</CardTitle>
              <p className="text-sm text-foreground/80 leading-relaxed">
                {parseAI(replayQ.data.ai_report.parsed)?.summary || '—'}
              </p>
            </Card>
          )}

          {/* 逐把 */}
          <Card asym={2}>
            <CardTitle icon={RotateCcw}>Per-solve</CardTitle>
            <div className="space-y-2">
              {replayQ.data.cubes.map((c: any) => (
                <SolveRow key={c.solve_id} cube={c}
                  expanded={expandedSolve === c.solve_id}
                  onToggle={() => setExpandedSolve(expandedSolve === c.solve_id ? null : c.solve_id)} />
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}

function parseAI(parsed: any): { summary?: string; bottlenecks?: string[] } {
  if (!parsed) return {}
  if (typeof parsed === 'string') { try { return JSON.parse(parsed) } catch { return {} } }
  return parsed
}

function SolveRow({ cube, expanded, onToggle }: { cube: any; expanded: boolean; onToggle: () => void }) {
  const stage = cube.stages || {}
  return (
    <div className="bg-muted/30 border border-border/30 rounded-2xl overflow-hidden">
      <div onClick={onToggle}
           className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-muted/50 transition-colors">
        <span className="text-xs text-muted-foreground w-8">#{cube.seq}</span>
        <span className={`font-serif font-semibold tabular-nums w-20 ${cube.is_dnf ? 'text-destructive' : 'text-foreground'}`}>
          {cube.is_dnf ? 'DNF' : fmt(cube.total_time_ms)}
        </span>
        <code className="flex-1 text-[10px] text-muted-foreground font-mono truncate">
          {cube.scramble}
        </code>
        <span className="hidden sm:inline text-xs text-muted-foreground w-14 text-right">F2L {fmt(stage.f2l_dur_ms)}</span>
        <span className="hidden sm:inline text-xs text-muted-foreground w-14 text-right">PLL {fmt(stage.pll_dur_ms)}</span>
        <span className="text-xs text-muted-foreground w-12 text-right">⏸ {cube.pauses?.length ?? 0}</span>
        {expanded ? <ChevronUp size={16} className="text-muted-foreground" /> : <ChevronDown size={16} className="text-muted-foreground" />}
      </div>
      {expanded && (
        <div className="px-4 pb-4 pt-3 border-t border-border/30 bg-background/50">
          <MoveTimeline moves={cube.moves} pauses={cube.pauses} totalMs={cube.total_time_ms} />
        </div>
      )}
    </div>
  )
}

function MoveTimeline({ moves, pauses, totalMs }: { moves: any[]; pauses: any[]; totalMs: number }) {
  type Item = { type: 'move' | 'pause'; t: number; dur: number; label: string; stage?: string }
  const items: Item[] = []
  for (const m of moves) items.push({ type: 'move', t: m.timestamp_ms, dur: 0, label: m.move, stage: m.stage_label })
  for (const p of pauses) items.push({ type: 'pause', t: p.start_ms, dur: p.duration_ms, label: p.type, stage: p.stage_label })
  items.sort((a, b) => a.t - b.t)

  return (
    <div>
      <div className="text-xs text-muted-foreground mb-2">
        total {fmt(totalMs)} · {moves.length} moves · {pauses.length} pauses
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((it, i) => it.type === 'move' ? (
          <span key={i} title={`t=${it.t}ms ${it.stage || '?'}`}
                className={`px-2 py-1 rounded-md text-xs font-mono font-bold ${STAGE_COLORS[it.stage || ''] || 'bg-muted text-foreground'}`}>
            {it.label}
          </span>
        ) : (
          <span key={i} title={`pause ${it.dur}ms ${it.stage || '?'}`}
                className="px-2 py-1 rounded-md text-[10px] bg-[#f59e0b]/20 text-[#92400e] border border-[#f59e0b]/30">
            ⏸ {it.dur}ms
          </span>
        ))}
      </div>
    </div>
  )
}
