/** 与后端 Pydantic schema 对齐的类型 */
export interface User {
  id: number
  username: string
  display_name?: string
  timezone: string
  avg_level?: string
  created_at: number
}

export interface FormulaAlg {
  id: number
  seq: number
  alg_text: string
  fingertricks?: string
  move_count?: number
  is_canonical: boolean
  notes?: string
}

export interface FormulaCase {
  id: number
  name: string
  code: string
  recognition?: string
  mirror_of?: string
  position_in_set: number
  is_symmetric: boolean
  algs: FormulaAlg[]
}

export interface FormulaSetSummary {
  id: number
  code: string
  puzzle: string
  display_name: string
  case_count: number
  source: string
  fetched_at: number
}

export interface FormulaSetDetail extends FormulaSetSummary {
  cases: FormulaCase[]
}

export interface TrainingTask {
  id: number
  rule_id?: string
  category: string
  title: string
  description?: string
  target_metric?: string
  duration_min?: number
  status: 'pending' | 'doing' | 'done' | 'skipped'
  scheduled_for?: number
  completed_at?: number
  config: Record<string, any>   // 含 pll_case_ids / f2l_case_ids / oll_case_ids / ...
  result: Record<string, any>
}

export interface AIReport {
  id: number
  session_id: number
  user_id: number
  model: string
  prompt_version: string
  bottleneck?: string
  confidence?: number
  parsed: {
    bottlenecks?: string[]
    root_causes?: string[]
    speed_pattern?: string
    recommendations?: any[]
    summary?: string
  }
  created_at: number
}

export interface DailyGoal {
  id: number
  goal_date: number
  target_kind: string
  target_value: number
  completed_value: number
  is_achieved: boolean
  recommended: boolean
  achievement_ratio: number
}
