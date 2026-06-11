import { useQuery } from '@tanstack/react-query'
import { FormulasAPI } from '@/api/client'
import { Card, CardTitle, Badge } from '@/components/ui'
import { BookOpen, Layers } from 'lucide-react'
import { useT } from '@/i18n'
import { type FormulaSetSummary } from '@/types/api'

export default function FormulasPage() {
  const { t } = useT()
  const { data: sets, isLoading } = useQuery<FormulaSetSummary[]>({
    queryKey: ['formula-sets'],
    queryFn: () => FormulasAPI.sets(),
  })

  const setColors = [
    'card-asym-1', 'card-asym-2', 'card-asym-3', '',
  ] as const

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="font-serif text-3xl md:text-4xl text-foreground">{t('nav.formulas')}</h1>
        <p className="text-muted-foreground mt-1">Browse 1042 cases across 8 alg sets</p>
      </div>

      {isLoading && <div className="text-center text-muted-foreground">Loading…</div>}

      {sets && sets.length === 0 && (
        <Card className="text-center py-12">
          <BookOpen size={40} className="mx-auto text-muted-foreground mb-4" />
          <p className="text-muted-foreground mb-4">{t('formulas.empty')}</p>
          <code className="block text-xs bg-muted/60 px-4 py-2 rounded-full inline-block font-mono">
            python -m scripts.import_formulas PLL OLL F2L
          </code>
        </Card>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {sets?.map((fs, i) => (
          <Card key={fs.code} asym={(i % 3 + 1) as 1 | 2 | 3}
                className="hover:scale-[1.02] transition-transform">
            <div className="h-12 w-12 rounded-2xl bg-secondary/15 text-secondary inline-flex items-center justify-center mb-3">
              <Layers size={22} />
            </div>
            <div className="font-serif font-bold text-lg text-foreground">{fs.code}</div>
            <div className="text-xs text-muted-foreground line-clamp-2 mb-3">{fs.display_name}</div>
            <div className="flex items-center justify-between">
              <Badge variant="clay">{fs.case_count} cases</Badge>
              <span className="text-[10px] text-muted-foreground/70 font-mono">{fs.source.split('/').pop()}</span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
