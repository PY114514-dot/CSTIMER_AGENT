/**
 * 共享 UI 原子 - 严格按 Organic / Natural design system 实现
 * 设计 token 已通过 tailwind.config.js 暴露
 */
import { type ReactNode, type ButtonHTMLAttributes, type InputHTMLAttributes } from 'react'
import { clsx } from 'clsx'
import {
  CheckCircle2, XCircle, Loader2, type LucideIcon,
} from 'lucide-react'

// ── Button ────────────────────────────────────────
type Variant = 'primary' | 'outline' | 'ghost' | 'destructive'
type Size = 'sm' | 'md' | 'lg'

export function Button({
  variant = 'primary', size = 'md', className, children, ...rest
}: { variant?: Variant; size?: Size } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={clsx(
        size === 'sm' ? 'btn-pill btn-sm'
             : size === 'lg' ? 'btn-pill btn-lg'
             : 'btn-pill',
        variant === 'primary'       ? 'btn-primary'
             : variant === 'outline' ? 'btn-outline'
             : variant === 'ghost'   ? 'btn-ghost'
             : 'btn-destructive',
        'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100',
        className
      )}
    >
      {children}
    </button>
  )
}

// ── Card (3 种不对称圆角可选) ─────────────────────
export function Card({
  children, className, asym = 0, onClick,
}: {
  children: ReactNode
  className?: string
  /** 0=标准, 1/2/3=三种不对称圆角 */
  asym?: 0 | 1 | 2 | 3
  onClick?: () => void
}) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        'card-organic',
        asym === 1 ? 'card-asym-1' : asym === 2 ? 'card-asym-2' : asym === 3 ? 'card-asym-3' : '',
        onClick && 'cursor-pointer',
        className
      )}
    >
      {children}
    </div>
  )
}

export function CardTitle({ children, icon: Icon, accent = 'moss' }: {
  children: ReactNode
  icon?: LucideIcon
  accent?: 'moss' | 'clay' | 'stone'
}) {
  const IconBox = accent === 'clay' ? 'icon-box-clay' : 'icon-box'
  return (
    <div className="flex items-center gap-3 mb-4">
      {Icon && (
        <div className={IconBox}>
          <Icon size={26} strokeWidth={1.8} />
        </div>
      )}
      <h3 className="font-serif font-semibold text-foreground m-0">{children}</h3>
    </div>
  )
}

// ── Input ────────────────────────────────────────
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={clsx('input-pill', props.className)} />
}

// ── Progress Ring (CSS 圆环, SVG) ─────────────────
export function ProgressRing({ pct, size = 100, label }: {
  pct: number   // 0-100
  size?: number
  label?: ReactNode
}) {
  const r = (size - 12) / 2
  const circ = 2 * Math.PI * r
  const off = circ - (Math.min(100, Math.max(0, pct)) / 100) * circ
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size/2} cy={size/2} r={r} stroke="#F0EBE5" strokeWidth="10" fill="none" />
        <circle
          cx={size/2} cy={size/2} r={r}
          stroke="url(#goalGrad)" strokeWidth="10" fill="none"
          strokeDasharray={circ} strokeDashoffset={off}
          strokeLinecap="round"
          className="transition-all duration-700"
        />
        <defs>
          <linearGradient id="goalGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%"  stopColor="#5D7052" />
            <stop offset="100%" stopColor="#C18C5D" />
          </linearGradient>
        </defs>
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center font-serif">
        {label ?? <span className="text-2xl font-bold">{Math.round(pct)}%</span>}
      </div>
    </div>
  )
}

// ── Progress Bar ──────────────────────────────────
export function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="progress-ring">
      <div className="progress-fill" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  )
}

// ── Badge ────────────────────────────────────────
export function Badge({
  children, variant = 'primary', icon: Icon,
}: {
  children: ReactNode
  variant?: 'primary' | 'clay' | 'stone' | 'warning' | 'danger' | 'success'
  icon?: LucideIcon
}) {
  const cls =
    variant === 'primary' ? 'badge-primary'
    : variant === 'clay'    ? 'badge-clay'
    : variant === 'stone'   ? 'badge-stone'
    : variant === 'warning' ? 'badge-warning'
    : variant === 'danger'  ? 'badge-danger'
    : 'badge-success'
  return (
    <span className={clsx('badge', cls)}>
      {Icon && <Icon size={12} />}
      {children}
    </span>
  )
}

// ── IconBox (图标的方/圆底) ──────────────────────
export function IconBox({
  icon: Icon, accent = 'moss',
}: { icon: LucideIcon; accent?: 'moss' | 'clay' }) {
  return (
    <div className={accent === 'clay' ? 'icon-box-clay' : 'icon-box'}>
      <Icon size={26} strokeWidth={1.8} />
    </div>
  )
}

// ── Spinner / Done / Error (任务态) ──────────────
export function Status({ state }: { state: 'pending' | 'doing' | 'done' | 'skipped' }) {
  if (state === 'done') return <CheckCircle2 size={18} className="text-primary" />
  if (state === 'skipped') return <XCircle size={18} className="text-muted-foreground" />
  return <Loader2 size={18} className="text-muted-foreground animate-spin" />
}

// ── Blob (大型背景装饰) ──────────────────────────
export function Blob({
  className, color = 'moss', style,
}: { className?: string; color?: 'moss' | 'clay' | 'sand'; style?: React.CSSProperties }) {
  const grad = color === 'clay'
    ? 'from-secondary/30 to-accent/20'
    : color === 'sand'
    ? 'from-accent/40 to-muted/20'
    : 'from-primary/30 to-accent/20'
  return <div className={clsx('blob', `bg-gradient-to-br ${grad}`, className)} style={style} />
}
