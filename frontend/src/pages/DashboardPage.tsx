import { useQuery, useQueryClient } from '@tanstack/react-query'
import { DashboardAPI, SessionsAPI } from '@/api/client'
import { useAppStore } from '@/store/app'
import { useNavigate } from 'react-router-dom'
import { useT } from '@/i18n'
import { useWebSocketEvents } from '@/hooks/useWebSocketEvents'
import { Card, CardTitle, Button, ProgressRing, ProgressBar, Badge, Blob } from '@/components/ui'
import {
  Target, Activity, Sparkles, Layers, Play, Square, RotateCcw,
  Download, Hourglass, ChevronRight, Bot, Trophy,
} from 'lucide-react'
import { type TrainingTask } from '@/types/api'

function downloadCsv(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
}

export default function DashboardPage() {
  const user = useAppStore(s => s.user)!
  const nav = useNavigate()
  const qc = useQueryClient()
  const { t } = useT()

  useWebSocketEvents({ userId: user.id }, {})

  const dashQ = useQuery({
    queryKey: ['dashboard', user.id],
    queryFn: () => DashboardAPI.today(user.id),
    refetchInterval: 5000,
  })
  const today = dashQ.data
  const tasks: TrainingTask[] = today?.training_tasks ?? []
  const doneCount = tasks.filter(t => t.status === 'done').length
  const total = tasks.length
  const goalPct = total > 0 ? (doneCount / total) * 100 : 0
  const aiReport = today?.latest_ai_report
  const curSess = today?.current_session

  return (
    <div className="space-y-8">
      {/* Hero greeting */}
      <section className="text-center py-6 animate-fade-in">
        <Badge variant="clay" icon={Sparkles}>
          {curSess ? 'Active session' : 'No active session'}
        </Badge>
        <h1 className="mt-4 text-3xl md:text-5xl font-serif text-foreground text-balance">
          {t('nav.dashboard')}
        </h1>
        <p className="mt-2 text-muted-foreground max-w-xl mx-auto text-balance">
          Track your solves, master your technique, train with intention.
        </p>
      </section>

      {/* 3 卡片主区 */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card asym={1}>
          <CardTitle icon={Target}>{t('dashboard.today_goal')}</CardTitle>
          {today?.daily_goal ? (
            <div className="flex items-center gap-6">
              <ProgressRing pct={goalPct} size={96}
                label={<span className="font-serif text-xl font-bold text-foreground">{doneCount}/{total}</span>} />
              <div className="flex-1">
                <div className="text-xs text-muted-foreground mb-1">Completed / Target</div>
                <ProgressBar pct={goalPct} />
                <Button onClick={() => nav('/timer')} variant="primary" size="sm" className="w-full mt-4">
                  <Play size={14} /> {t('dashboard.start_timer')}
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <div className="text-muted-foreground text-sm mb-4">{t('dashboard.no_goal')}</div>
              <Button onClick={() => DashboardAPI.recommendGoal(user.id).then(() => qc.invalidateQueries())}
                      variant="primary" className="w-full">
                <Sparkles size={14} /> {t('dashboard.recommend_goal')}
              </Button>
            </div>
          )}
        </Card>

        <Card asym={2}>
          <CardTitle icon={Activity} accent="clay">{t('dashboard.current_session')}</CardTitle>
          {curSess ? (
            <div>
              <div className="flex items-end gap-2 mb-4">
                <span className="text-4xl font-serif font-bold text-foreground">
                  {curSess.cube_count}
                </span>
                <span className="text-muted-foreground text-lg mb-1">/ {curSess.target_size}</span>
              </div>
              <ProgressBar pct={(curSess.cube_count / curSess.target_size) * 100} />
              <div className="grid grid-cols-2 gap-2 mt-4">
                <Button onClick={() => SessionsAPI.close(curSess.id).then(() => qc.invalidateQueries())}
                        variant="outline" size="sm">
                  <Square size={12} /> {t('dashboard.close_session')}
                </Button>
                <Button onClick={() => nav(`/replay?session=${curSess.id}`)} variant="primary" size="sm">
                  <RotateCcw size={12} /> {t('dashboard.replay')}
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <div className="text-muted-foreground text-sm mb-4">{t('dashboard.no_session')}</div>
              <Button onClick={() => nav('/timer')} variant="primary" className="w-full">
                <Play size={14} /> {t('dashboard.open_session')}
              </Button>
            </div>
          )}
        </Card>

        <Card asym={3}>
          <CardTitle icon={Bot}>{t('dashboard.ai_latest')}</CardTitle>
          {aiReport ? (
            <div className="space-y-3">
              <p className="text-sm text-foreground/80 leading-relaxed line-clamp-4">
                {aiReport.parsed?.summary || '—'}
              </p>
              {aiReport.parsed?.bottlenecks?.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {aiReport.parsed.bottlenecks.map((b: string) => (
                    <Badge key={b} variant="warning" icon={Hourglass}>⚠ {b}</Badge>
                  ))}
                </div>
              ) : null}
              <div className="text-xs text-muted-foreground pt-2 border-t border-border/40">
                model <code className="text-foreground">{aiReport.model}</code> · conf {Math.round((aiReport.confidence || 0) * 100)}%
              </div>
            </div>
          ) : (
            <div className="text-muted-foreground text-sm">{t('dashboard.no_ai')}</div>
          )}
        </Card>
      </section>

      <section>
        <Card asym={2} className="p-8">
          <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
            <CardTitle icon={Trophy}>{t('dashboard.training_today')}</CardTitle>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm"
                      onClick={() => downloadCsv(`/api/dashboard/export/today.csv?user_id=${user.id}`)}>
                <Download size={14} /> {t('dashboard.export_today')}
              </Button>
              <Button variant="ghost" size="sm"
                      onClick={() => downloadCsv(`/api/training-export.csv?user_id=${user.id}`)}>
                <Download size={14} /> {t('dashboard.export_training')}
              </Button>
            </div>
          </div>

          {total === 0 ? (
            <div className="text-center py-12">
              <div className="inline-flex items-center justify-center h-20 w-20 rounded-full bg-muted/60 mb-4">
                <Layers size={32} className="text-muted-foreground" />
              </div>
              <p className="text-muted-foreground max-w-md mx-auto">{t('dashboard.empty_tasks')}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {tasks.map((task) => (
                <TrainingTaskCard key={task.id} task={task} onClick={() => nav(`/training/${task.id}`)} />
              ))}
            </div>
          )}
        </Card>
      </section>
    </div>
  )
}

function TrainingTaskCard({ task, onClick }: { task: TrainingTask; onClick: () => void }) {
  const isDone = task.status === 'done'
  return (
    <div onClick={onClick}
         className="group flex items-center gap-4 px-5 py-4 rounded-[1.5rem] bg-muted/30 hover:bg-muted/60
                    border border-border/30 hover:border-primary/30 transition-all duration-300
                    hover:shadow-soft cursor-pointer">
      <div className={`h-10 w-10 rounded-full flex items-center justify-center text-sm font-semibold
                       ${isDone ? 'bg-primary text-white' : 'bg-background border border-border'}`}>
        {isDone ? '✓' : task.category.charAt(0).toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-foreground truncate">{task.title}</div>
        <div className="text-xs text-muted-foreground truncate">{task.description}</div>
      </div>
      <Badge variant="stone">{task.duration_min} min</Badge>
      <ChevronRight size={16} className="text-muted-foreground group-hover:text-primary transition-colors" />
    </div>
  )
}
