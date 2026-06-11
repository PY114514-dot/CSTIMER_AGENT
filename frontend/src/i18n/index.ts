/**
 * 极简 i18n (zh-CN / en)
 * - t('key') 取当前语言
 * - setLang('en' | 'zh')
 * - subscribe 监听变化
 *
 * 文案覆盖:
 *   - 通用 UI (按钮/标签)
 *   - 公式库: 用后端 i18n 字典 (en 来自 DB, zh 从后端 formula_i18n 同步而来)
 */
import { useSyncExternalStore } from 'react'

export type Lang = 'zh' | 'en'
const LS_KEY = 'cstimer_lang_v1'

// 同步后端 formula_i18n.py 的 zh 字典 (只列 DB 里有但前端的翻译, 缺省 en)
const ZH: Record<string, string | ((...args: any[]) => string)> = {
  // 通用
  'app.title':          'CSTIMER 智能魔方训练助手',
  'nav.dashboard':      '看板',
  'nav.timer':          '计时',
  'nav.training':       '训练',
  'nav.devices':        '魔方',
  'nav.formulas':       '公式库',
  'nav.agent':          'AGENT',
  'login.placeholder':  '用户名 (新用户自动创建)',
  'login.button':       '进入',
  'login.error.empty':  '请输入用户名',
  'logout':             '登出',
  // 看板
  'dashboard.today_goal':     '今日目标',
  'dashboard.no_goal':        '今日无目标',
  'dashboard.recommend_goal': '推荐目标',
  'dashboard.start_timer':    '开始计时',
  'dashboard.current_session':'当前 Session',
  'dashboard.no_session':     '无 open session',
  'dashboard.open_session':   '开启新 Session',
  'dashboard.close_session':  '关闭 Session',
  'dashboard.ai_latest':      'AI 教练 · 最近报告',
  'dashboard.no_ai':          '尚无 AI 报告 · 关闭一个 Session 后自动生成',
  'dashboard.training_today': '今日训练项',
  'dashboard.empty_tasks':    '还没生成训练项, 先解 12 把然后关闭 Session, AGENT 会自动出训练计划',
  'dashboard.replay':         '复盘',
  'dashboard.export_today':   '导出今日 (CSV)',
  'dashboard.export_training':'导出训练项 (CSV)',
  'dashboard.stage_breakdown': '阶段耗时分布',
  'dashboard.pause_heatmap':   '停顿热图',
  'dashboard.trend':           '历史趋势',
  'dashboard.done_count':     (n: number, total: number) => `${n} / ${total} 完成`,
  // 公式库
  'formulas.header':     '公式集合',
  'formulas.empty':      '未 seed. 在 backend 跑:',
  'formulas.cases':      'cases',
  'formulas.source':     '源',
  'formulas.detail':     '详情',
  'formulas.search':     '搜索 case (按 name/code)',
  'formulas.recognition_zh': '识别特征 (中文)',
  'formulas.recognition_en': '识别特征 (英文)',
  // 公式库 PLL 21 (zh)
  'pll.Aa.zh': '两个邻角互换',          'pll.Aa.en': 'two adjacent corners swapped',
  'pll.Ab.zh': '两个对角互换',          'pll.Ab.en': 'two diagonal corners swapped',
  'pll.E.zh':  '三条边互换 + 角块不动',  'pll.E.en':  'three edges cycled, corners untouched',
  'pll.F.zh':  '前 1 + 后 1 / 一条邻边','pll.F.en':  'front+back swap (one edge pair)',
  'pll.Ga.zh': '两角 + 两对边',          'pll.Ga.en': 'two corners + two opposite edge pairs',
  'pll.Gb.zh': '两角 + 两条邻边',        'pll.Gb.en': 'two corners + two adjacent edges',
  'pll.Gc.zh': '两角 + 两条对边',        'pll.Gc.en': 'two corners + two opposite edges',
  'pll.Gd.zh': '两角 + 两条边反向',      'pll.Gd.en': 'two corners + two edges reversed',
  'pll.H.zh':  '对边互换',                'pll.H.en':  'opposite edge swap',
  'pll.Ja.zh': '两邻角 + 一边反向',      'pll.Ja.en': 'two adjacent corners + one edge reversed',
  'pll.Jb.zh': '两邻角 + 一边',          'pll.Jb.en': 'two adjacent corners + one edge',
  'pll.Na.zh': '两角 + 两条反向边',      'pll.Na.en': 'two corners + two opposite-direction edges',
  'pll.Nb.zh': '两角 + 两条邻边',        'pll.Nb.en': 'two corners + two adjacent edges',
  'pll.Ra.zh': '一边反向 + 角块不动',    'pll.Ra.en': 'one edge reversed, corners untouched',
  'pll.Rb.zh': '一边正向 + 角块不动',    'pll.Rb.en': 'one edge forward, corners untouched',
  'pll.T.zh':  '两邻角 + 头部边反向',    'pll.T.en':  'T-shape: two adjacent corners + head edge reversed',
  'pll.Ua.zh': '三边循环正向 (逆时针)',  'pll.Ua.en': 'three edges cycle clockwise (Ua)',
  'pll.Ub.zh': '三边循环反向',           'pll.Ub.en': 'three edges cycle counter-clockwise (Ub)',
  'pll.V.zh':  '两邻角 + 头部边正向',    'pll.V.en':  'V-shape: two adjacent corners + head edge forward',
  'pll.Y.zh':  '两角 + 一条邻边 + 头部对边','pll.Y.en': 'Y-shape: two corners + adjacent + opposite edges',
  'pll.Z.zh':  '对边互换 + 一边反向',    'pll.Z.en':  'Z-shape: opposite edge swap + one edge reversed',
  // OLL 摘选
  'oll.OLL 21.zh': 'H (两条对边已定向)',   'oll.OLL 21.en': 'H: two opposite edges already oriented',
  'oll.OLL 22.zh': 'H 变体',               'oll.OLL 22.en': 'H variant',
  'oll.OLL 23.zh': 'U (两条邻边已定向)',   'oll.OLL 23.en': 'U: two adjacent edges oriented',
  'oll.OLL 45.zh': 'F (全边翻转, L 形)',   'oll.OLL 45.en': 'F: all edges flipped, L-shape',
  'oll.OLL 55.zh': '全角定向 (skip)',      'oll.OLL 55.en': 'all corners oriented (skip)',
  'oll.OLL 56.zh': '全角定向 (skip 变体)', 'oll.OLL 56.en': 'all corners oriented (skip variant)',
  'oll.OLL 57.zh': '全角定向 (skip 变体)', 'oll.OLL 57.en': 'all corners oriented (skip variant)',
  // 训练
  'training.recognition_drill': '识别刷',
  'training.slow_lookahead':    '慢拧预判',
  'training.metronome':         '节拍器',
  'training.alg_count':         (n: number) => `${n} 个算法`,
  'training.mark_done':         '完成',
  // 计时
  'timer.start': '开始 (空格)',
  'timer.stop':  '停止 (空格)',
  // 复盘
  'replay.title':        '复盘',
  'replay.solve_seq':    (n: number) => `第 ${n} 把`,
  'replay.move_seq':     (n: number) => `第 ${n} 动`,
  'replay.pause':        (ms: number) => `停顿 ${ms}ms`,
  'replay.stage':        '阶段',
  'replay.export_csv':   '导出本 session 为 CSV',
  'replay.no_session':   '选一个 session 来复盘',
  'replay.select':       '选择 session',
  // AGENT
  'agent.greeting': '你好! 我是你的魔方训练 AGENT. 你可以问我:\n• "我最近瓶颈在哪"\n• "给我列 6 个 Aa-perm 训练用的 case"\n• "基于我上次的 session 给我制定训练方案"',
  'agent.placeholder': '问点什么, 例如: 给我列 6 个 Aa-perm 训练用的 case',
  'agent.thinking': 'AGENT 思考中...',
  'agent.send': '发送',
}

const EN: Record<string, string | ((...args: any[]) => string)> = {
  'app.title':          'CSTIMER Cube Coach',
  'nav.dashboard':      'Dashboard',
  'nav.timer':          'Timer',
  'nav.training':       'Training',
  'nav.devices':        'Devices',
  'nav.formulas':       'Formulas',
  'nav.agent':          'AGENT',
  'login.placeholder':  'Username (auto-create if new)',
  'login.button':       'Sign in',
  'login.error.empty':  'Please enter a username',
  'logout':             'Logout',
  'dashboard.today_goal':     'Today\'s Goal',
  'dashboard.no_goal':        'No goal today',
  'dashboard.recommend_goal': 'Recommend goal',
  'dashboard.start_timer':    'Start timer',
  'dashboard.current_session':'Current Session',
  'dashboard.no_session':     'No open session',
  'dashboard.open_session':   'Open new session',
  'dashboard.close_session':  'Close session',
  'dashboard.ai_latest':      'AI Coach · Latest',
  'dashboard.no_ai':          'No AI report yet. Close a session to generate one.',
  'dashboard.training_today': 'Today\'s Training',
  'dashboard.empty_tasks':    'No training items yet. Solve 12 solves and close a session; AGENT will auto-generate a plan.',
  'dashboard.replay':         'Replay',
  'dashboard.export_today':   'Export today (CSV)',
  'dashboard.export_training':'Export training (CSV)',
  'dashboard.stage_breakdown': 'Stage breakdown',
  'dashboard.pause_heatmap':   'Pause heatmap',
  'dashboard.trend':           'Trend',
  'dashboard.done_count':     (n: number, total: number) => `${n} / ${total} done`,
  'formulas.header':     'Formula Sets',
  'formulas.empty':      'Not seeded. Run in backend:',
  'formulas.cases':      'cases',
  'formulas.source':     'source',
  'formulas.detail':     'Detail',
  'formulas.search':     'Search case (by name/code)',
  'formulas.recognition_zh': 'Recognition (Chinese)',
  'formulas.recognition_en': 'Recognition (English)',
  'training.recognition_drill': 'Recognition drill',
  'training.slow_lookahead':    'Slow lookahead',
  'training.metronome':         'Metronome',
  'training.alg_count':         (n: number) => `${n} algs`,
  'training.mark_done':         'Done',
  'timer.start': 'Start (Space)',
  'timer.stop':  'Stop (Space)',
  'replay.title':        'Replay',
  'replay.solve_seq':    (n: number) => `Solve #${n}`,
  'replay.move_seq':     (n: number) => `Move #${n}`,
  'replay.pause':        (ms: number) => `Pause ${ms}ms`,
  'replay.stage':        'Stage',
  'replay.export_csv':   'Export this session as CSV',
  'replay.no_session':   'Pick a session to replay',
  'replay.select':       'Select session',
  'agent.greeting': 'Hi! I\'m your cubing AGENT. Try:\n• "what\'s my bottleneck?"\n• "show me 6 Aa-perm training cases"\n• "build a training plan from my last session"',
  'agent.placeholder': 'Ask something, e.g. "show me 6 Aa-perm training cases"',
  'agent.thinking': 'AGENT thinking...',
  'agent.send': 'Send',
}

// ── store ───────────────────────────────────────────
type Listener = () => void
let lang: Lang = (() => {
  try { return (localStorage.getItem(LS_KEY) as Lang) || 'zh' } catch { return 'zh' }
})()
const listeners = new Set<Listener>()

export function getLang(): Lang { return lang }
export function setLang(l: Lang) {
  lang = l
  try { localStorage.setItem(LS_KEY, l) } catch {}
  listeners.forEach(fn => fn())
}
export function subscribe(fn: Listener): () => void {
  listeners.add(fn); return () => listeners.delete(fn)
}

// ── t: 优先查当前语言, 缺省回退到另一种, 再缺省回 key 本身 ──
export function t(key: string, ...args: any[]): string {
  const cur = lang === 'zh' ? ZH : EN
  const fallback = lang === 'zh' ? EN : ZH
  const v = cur[key] ?? fallback[key] ?? key
  if (typeof v === 'function') return (v as any)(...args)
  return v
}

/** 按公式库 code 拿双语识别 (从后端 i18n 同步过来, 不在 DB 里的返 null) */
export function tFormulaRecognition(setCode: string, caseCode: string, langOverride?: Lang): string | null {
  const l = langOverride ?? lang
  // 拼路径: 'pll.Aa.zh' / 'pll.Aa.en' / 'oll.OLL 21.zh' / 'f2l.F2L 1.zh'
  const key = `${setCode.toLowerCase()}.${caseCode}.${l}`
  const cur = l === 'zh' ? ZH : EN
  const fallback = l === 'zh' ? EN : ZH
  const v = cur[key] ?? fallback[key]
  if (typeof v === 'function') return (v as (...a: any[]) => string)()
  return v ?? null
}

// ── hook ───────────────────────────────────────────
export function useT() {
  useSyncExternalStore(subscribe, () => lang, () => lang)
  return { t, getLang, setLang, tFormulaRecognition }
}
