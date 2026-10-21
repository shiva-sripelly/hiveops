export function money(n: number | null | undefined, digits?: number): string {
  if (n == null) return '–'
  const d = digits ?? (n !== 0 && Math.abs(n) < 1 ? 4 : 2)
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`
}

export function compact(n: number | null | undefined): string {
  if (n == null) return '–'
  return Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

export function pct(n: number | null | undefined, digits = 0): string {
  return n == null ? '–' : `${n.toFixed(digits)}%`
}

export function ratio(n: number | null | undefined): string {
  return n == null ? '–' : `${Math.round(n * 100)}%`
}

export function duration(ms: number | null | undefined): string {
  if (ms == null) return '–'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '–'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  awaiting_approval: 'Needs approval',
  completed: 'Completed',
  failed: 'Failed',
  rejected: 'Rejected',
  pending: 'Pending',
  approved: 'Approved',
  cancelled: 'Cancelled',
}
