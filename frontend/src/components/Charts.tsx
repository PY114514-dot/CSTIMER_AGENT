/**
 * 纯 SVG 图表组件 (无第三方依赖)
 * - StageStackedBar: 每行 = 一次 solve 的 cross/f2l/oll/pll 阶段堆叠
 * - PauseHeatmap: 每行 = 一次 solve, 16 列 = 0~15s 时间窗, 颜色按 pause 累计时长
 * - TrendLine: 历史 avg3/avg5 折线
 *
 * 入参用后端 /api/dashboard/today 返回的 stage_breakdown / pause_heatmap / trend_30
 */
import type { CSSProperties } from 'react'

// ── StageStackedBar ───────────────────────────────────
export interface StageRow {
  solve_id: number
  seq: number
  cross_ms: number | null
  f2l_ms: number | null
  oll_ms: number | null
  pll_ms: number | null
}

const STAGE_COLORS: Record<string, string> = {
  cross: '#38bdf8',
  f2l:   '#a78bfa',
  oll:   '#f472b6',
  pll:   '#34d399',
}

export function StageStackedBar({ rows }: { rows: StageRow[] }) {
  if (!rows || rows.length === 0) {
    return <div style={{ color: 'var(--muted)', fontSize: 13 }}>暂无数据</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {rows.map(r => {
        const cross = r.cross_ms || 0
        const f2l   = r.f2l_ms   || 0
        const oll   = r.oll_ms   || 0
        const pll   = r.pll_ms   || 0
        const total = cross + f2l + oll + pll
        if (total === 0) {
          return <div key={r.solve_id} style={{ color: 'var(--muted)', fontSize: 12 }}>#{r.seq} 无数据</div>
        }
        const seg = (v: number) => (v / total * 100).toFixed(1) + '%'
        return (
          <div key={r.solve_id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 28, fontSize: 11, color: 'var(--muted)', textAlign: 'right' }}>#{r.seq}</div>
            <div style={{ flex: 1, display: 'flex', height: 22, borderRadius: 4, overflow: 'hidden', background: 'var(--panel-2)' }}>
              {cross > 0 && <div title={`Cross ${cross}ms`} style={segStyle(STAGE_COLORS.cross, seg(cross))}>{cross}</div>}
              {f2l   > 0 && <div title={`F2L ${f2l}ms`}   style={segStyle(STAGE_COLORS.f2l,   seg(f2l))}>{f2l}</div>}
              {oll   > 0 && <div title={`OLL ${oll}ms`}   style={segStyle(STAGE_COLORS.oll,   seg(oll))}>{oll}</div>}
              {pll   > 0 && <div title={`PLL ${pll}ms`}   style={segStyle(STAGE_COLORS.pll,   seg(pll))}>{pll}</div>}
            </div>
            <div style={{ width: 56, fontSize: 12, color: 'var(--muted)', textAlign: 'right' }}>
              {(total / 1000).toFixed(2)}s
            </div>
          </div>
        )
      })}
      <div style={{ display: 'flex', gap: 14, fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
        <Legend color={STAGE_COLORS.cross} label="Cross" />
        <Legend color={STAGE_COLORS.f2l}   label="F2L" />
        <Legend color={STAGE_COLORS.oll}   label="OLL" />
        <Legend color={STAGE_COLORS.pll}   label="PLL" />
      </div>
    </div>
  )
}

function segStyle(bg: string, w: string): CSSProperties {
  return {
    width: w,
    background: bg,
    color: 'rgba(0,0,0,0.75)',
    fontSize: 11, fontWeight: 600,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    overflow: 'hidden', whiteSpace: 'nowrap',
  }
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span>
      <span style={{
        display: 'inline-block', width: 10, height: 10, borderRadius: 2,
        background: color, marginRight: 4, verticalAlign: 'middle',
      }} />
      {label}
    </span>
  )
}

// ── PauseHeatmap ──────────────────────────────────────
export interface HeatmapRow {
  solve_id: number
  bins_ms: number[]   // 16 个 1s 时间窗, 累计 pause 毫秒
}

const HEAT_BINS = 16

function heatColor(v: number): string {
  if (v < 50)  return 'var(--panel-2)'
  if (v < 300) return '#3f3a66'
  if (v < 600) return '#6366f1'
  if (v < 1000) return '#ec4899'
  if (v < 1800) return '#f59e0b'
  return '#ef4444'
}

export function PauseHeatmap({ rows }: { rows: HeatmapRow[] }) {
  if (!rows || rows.length === 0) {
    return <div style={{ color: 'var(--muted)', fontSize: 13 }}>暂无停顿数据</div>
  }
  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {rows.map(r => (
          <div key={r.solve_id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 26, fontSize: 11, color: 'var(--muted)', textAlign: 'right' }}>
              #{rows.indexOf(r) + 1}
            </div>
            {(r.bins_ms || new Array(HEAT_BINS).fill(0)).slice(0, HEAT_BINS).map((v, i) => (
              <div
                key={i}
                title={`solve #${rows.indexOf(r) + 1} t=${i}~${i+1}s  pause=${v}ms`}
                style={{
                  flex: 1, height: 16, borderRadius: 2,
                  background: heatColor(v || 0),
                }}
              />
            ))}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>0s</span>
        <div style={{
          flex: 1, height: 6, borderRadius: 3,
          background: 'linear-gradient(90deg, var(--panel-2), #6366f1, #ec4899, #f59e0b, #ef4444)',
        }} />
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>15s</span>
      </div>
    </div>
  )
}

// ── TrendLine ─────────────────────────────────────────
export interface TrendPoint {
  session_id: number
  closed_at: number
  avg3_ms: number | null
  avg5_ms: number | null
}

export function TrendLine({ data }: { data: TrendPoint[] }) {
  if (!data || data.length < 2) {
    return <div style={{ color: 'var(--muted)', fontSize: 13 }}>至少需要 2 个 session 才能画趋势</div>
  }
  const W = 800, H = 140, padL = 36, padR = 12, padT = 12, padB = 24
  const xs = data.map((_, i) => padL + i * (W - padL - padR) / (data.length - 1))
  const all = data.flatMap(d => [d.avg3_ms || 0, d.avg5_ms || 0]).filter(v => v > 0)
  if (all.length === 0) {
    return <div style={{ color: 'var(--muted)', fontSize: 13 }}>趋势数据全空</div>
  }
  const minV = Math.min(...all) - 200
  const maxV = Math.max(...all) + 200
  const y = (v: number) => padT + (1 - (v - minV) / Math.max(1, maxV - minV)) * (H - padT - padB)
  const y3 = data.map(d => d.avg3_ms ? y(d.avg3_ms) : null)
  const y5 = data.map(d => d.avg5_ms ? y(d.avg5_ms) : null)
  const path = (arr: (number | null)[]) => arr
    .map((py, i) => py == null ? null : `${i === 0 ? 'M' : 'L'}${xs[i].toFixed(1)},${py.toFixed(1)}`)
    .filter(Boolean).join(' ')

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 140 }}>
      {[0, 0.25, 0.5, 0.75, 1].map(t => {
        const yy = padT + t * (H - padT - padB)
        return (
          <g key={t}>
            <line x1={padL} y1={yy} x2={W - padR} y2={yy} stroke="#262b36" strokeDasharray="2 4" />
            <text x={4} y={yy + 4} fill="#94a3b8" fontSize={10} fontFamily="monospace">
              {((maxV - t * (maxV - minV)) / 1000).toFixed(1)}s
            </text>
          </g>
        )
      })}
      <path d={path(y5)} fill="none" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 3" />
      <path d={path(y3)} fill="none" stroke="#6366f1" strokeWidth={2} />
      {xs.map((x, i) => y3[i] != null && (
        <circle key={i} cx={x} cy={y3[i] as number} r={3} fill="#6366f1" />
      ))}
      {data.map((d, i) => (
        <text key={i} x={xs[i]} y={H - 6} textAnchor="middle" fill="#94a3b8" fontSize={10} fontFamily="monospace">
          {new Date(d.closed_at).toISOString().slice(5, 10)}
        </text>
      ))}
    </svg>
  )
}
