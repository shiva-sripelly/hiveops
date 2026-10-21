import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router'
import { STATUS_LABEL } from '../format'

export function Panel({ title, action, children, className = '' }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel p-5 ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="font-display text-[15px] font-semibold text-ink">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

const STATUS_STYLE: Record<string, string> = {
  queued: 'bg-[#232850] text-muted',
  running: 'bg-blue/15 text-[#9fb6ff]',
  awaiting_approval: 'bg-warn/15 text-warn',
  completed: 'bg-good/15 text-good',
  approved: 'bg-good/15 text-good',
  failed: 'bg-bad/15 text-bad',
  rejected: 'bg-bad/15 text-bad',
  cancelled: 'bg-[#232850] text-muted',
  pending: 'bg-warn/15 text-warn',
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLE[status] ?? 'bg-panel-2 text-muted'}`}>
      {status === 'running' && <span className="live-dot h-1.5 w-1.5 rounded-full bg-current" />}
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

type Variant = 'primary' | 'ghost' | 'danger' | 'subtle'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-violet text-white hover:bg-[#9d84ff] shadow-[0_0_24px_rgba(139,108,255,0.35)]',
  subtle: 'bg-panel-2 text-ink border border-line hover:border-violet/60',
  ghost: 'text-muted hover:text-ink hover:bg-panel-2',
  danger: 'bg-bad/15 text-bad border border-bad/30 hover:bg-bad/25',
}

export function Button({ variant = 'subtle', className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  )
}

export function Kpi({ icon, label, value, detail, tone = 'violet' }: { icon: ReactNode; label: string; value: ReactNode; detail?: ReactNode; tone?: 'violet' | 'cyan' | 'good' | 'warn' }) {
  const ring = { violet: 'text-violet bg-violet/12', cyan: 'text-cyan bg-cyan/12', good: 'text-good bg-good/12', warn: 'text-warn bg-warn/12' }[tone]
  return (
    <div className="panel flex items-center gap-4 p-5">
      <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${ring}`}>{icon}</span>
      <div className="min-w-0">
        <p className="text-sm text-muted">{label}</p>
        <p className="tabular font-display text-[26px] font-semibold leading-tight">{value}</p>
        {detail && <p className="mt-0.5 text-xs text-muted">{detail}</p>}
      </div>
    </div>
  )
}

export function Change({ value, invert = false }: { value: number | null | undefined; invert?: boolean }) {
  if (value == null) return <span className="text-muted">No previous period</span>
  const good = invert ? value <= 0 : value >= 0
  return (
    <span className={good ? 'text-good' : 'text-bad'}>
      {value >= 0 ? '▲' : '▼'} {Math.abs(value)}% <span className="text-muted">vs previous 30 days</span>
    </span>
  )
}

export function AgentDot({ color, size = 8 }: { color?: string; size?: number }) {
  return <span className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: color ?? '#9ba1c9', boxShadow: `0 0 10px ${color ?? 'transparent'}` }} />
}

export function AgentChip({ id, agents }: { id: string; agents: Record<string, { name: string; color: string }> }) {
  const a = agents[id]
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-panel-2 px-2 py-0.5 text-xs">
      <AgentDot color={a?.color} size={7} />
      {a?.name ?? id}
    </span>
  )
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-line px-6 py-10 text-center">
      <p className="font-display font-semibold">{title}</p>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-[28px] font-semibold leading-tight tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-muted">{subtitle}</p>}
      </div>
      {action}
    </header>
  )
}

export function TextLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="text-sm text-[#a99bff] hover:text-white">
      {children}
    </Link>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  return <p className="rounded-xl border border-bad/30 bg-bad/10 px-4 py-3 text-sm text-bad">{error instanceof Error ? error.message : String(error)}</p>
}
