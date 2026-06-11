import { useQuery } from '@tanstack/react-query'
import { TrainingAPI } from '@/api/client'
import { useAppStore } from '@/store/app'
import { useNavigate } from 'react-router-dom'
import { useT } from '@/i18n'
import { useWebSocketEvents } from '@/hooks/useWebSocketEvents'
import { Card, CardTitle, Badge, Button } from '@/components/ui'
import { Sparkles, ChevronRight, Clock, Zap } from 'lucide-react'
import { type TrainingTask } from '@/types/api'

const CAT_COLOR: Record<string, 'primary' | 'clay' | 'stone' | 'warning' | 'danger' | 'success'> = {
  pll: 'success', oll: 'warning', f2l: 'clay', f1: 'primary', lookahead: 'primary',
  fingers: 'stone', metronome: 'stone', cross: 'success', default: 'stone',
}

export default function TrainingListPage() {
  const user = useAppStore(s => s.user)!
  const nav = useNavigate()
  const { t } = useT()
  useWebSocketEvents({ userId: user.id }, {})

  const { data, isLoading } = useQuery<TrainingTask[]>({
    queryKey: ['training-today', user.id],
    queryFn: () => TrainingAPI.today(user.id),
  })

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="font-serif text-3xl md:text-4xl text-foreground">{t('nav.training')}</h1>
        <p className="text-muted-foreground mt-1">Today's training plan, tailored by your AGENT</p>
      </div>

      {isLoading && <div className="text-center text-muted-foreground">Loading…</div>}

      {data && data.length === 0 && (
        <Card asym={2} className="text-center py-12">
          <div className="inline-flex items-center justify-center h-20 w-20 rounded-full bg-muted/60 mb-4">
            <Sparkles size={32} className="text-muted-foreground" />
          </div>
          <p className="text-muted-foreground max-w-md mx-auto">{t('dashboard.empty_tasks')}</p>
          <Button onClick={() => nav('/timer')} variant="primary" className="mt-6">Go to Timer</Button>
        </Card>
      )}

      <div className="space-y-4">
        {data?.map((t) => (
          <div key={t.id}
               onClick={() => nav(`/training/${t.id}`)}
               className="group card-organic card-asym-2 cursor-pointer p-5 sm:p-6 flex items-center gap-4">
            <div className="h-12 w-12 rounded-2xl bg-primary/10 text-primary inline-flex items-center justify-center font-bold flex-shrink-0">
              {t.category.charAt(0).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <Badge variant={CAT_COLOR[t.category] || 'stone'}>{t.category.toUpperCase()}</Badge>
                {t.status === 'done' && <Badge variant="success">✓ done</Badge>}
              </div>
              <div className="font-medium text-foreground truncate">{t.title}</div>
              <div className="text-xs text-muted-foreground line-clamp-1 mt-0.5">{t.description}</div>
            </div>
            <div className="flex flex-col items-end gap-1 flex-shrink-0">
              <Badge variant="stone" icon={Clock}>{t.duration_min} min</Badge>
            </div>
            <ChevronRight size={18} className="text-muted-foreground group-hover:text-primary transition-colors flex-shrink-0" />
          </div>
        ))}
      </div>
    </div>
  )
}
