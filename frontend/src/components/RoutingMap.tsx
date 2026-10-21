import type { Agent } from '../api'

/** How work flowed through the agent team over the last 30 days.
 *  Each column is a stage; ribbons are run transitions, thicker = more runs. */

const COLUMNS: { id: string; label: string }[] = [
  { id: 'intake', label: 'Intake' },
  { id: 'researcher', label: 'Research' },
  { id: 'analyst', label: 'Analysis' },
  { id: 'writer', label: 'Writing' },
  { id: 'reviewer', label: 'Review' },
  { id: 'communicator', label: 'Delivery' },
  { id: 'deliver', label: 'Done' },
]
const TERMINALS: Record<string, { label: string; color: string }> = {
  awaiting_approval: { label: 'Awaiting approval', color: '#fbbf24' },
  failed: { label: 'Failed', color: '#f87171' },
  rejected: { label: 'Rejected', color: '#f87171' },
  running: { label: 'In progress', color: '#4f7dff' },
  queued: { label: 'Queued', color: '#9ba1c9' },
}

const W = 760
const H = 280
const TOP = 46
const BOTTOM = 250

export function RoutingMap({
  edges,
  stages,
  agents,
}: {
  edges: { from: string; to: string; count: number }[]
  stages: Record<string, number>
  agents: Record<string, Agent>
}) {
  const total = stages.intake ?? 0
  if (!total) {
    return <p className="py-16 text-center text-sm text-muted">Run a workflow to see how work moves between your agents.</p>
  }
  const colX = (i: number) => 40 + i * ((W - 80) / (COLUMNS.length - 1))
  const index = Object.fromEntries(COLUMNS.map((c, i) => [c.id, i]))
  const max = Math.max(...edges.map((e) => e.count))
  const terminalEdges = edges.filter((e) => e.to in TERMINALS)
  const mainEdges = edges.filter((e) => e.from in index && e.to in index)

  // Spread parallel ribbons leaving the same node so they read as separate flows.
  const outOrder: Record<string, number> = {}
  const lanes = mainEdges.map((e) => {
    const k = (outOrder[e.from] = (outOrder[e.from] ?? -1) + 1)
    return k
  })
  const laneY = (k: number) => (TOP + BOTTOM) / 2 + (k === 0 ? 0 : (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 34)

  const color = (id: string) => agents[id]?.color ?? (id === 'deliver' ? '#34d399' : '#8b6cff')

  return (
    <div>
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Agent routing map">
      <defs>
        {mainEdges.map((e, i) => (
          <linearGradient key={i} id={`rg-${i}`} gradientUnits="userSpaceOnUse" x1={colX(index[e.from])} x2={colX(index[e.to])} y1="0" y2="0">
            <stop offset="0%" stopColor={color(e.from)} stopOpacity="0.9" />
            <stop offset="100%" stopColor={color(e.to)} stopOpacity="0.9" />
          </linearGradient>
        ))}
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {mainEdges.map((e, i) => {
        const x1 = colX(index[e.from])
        const x2 = colX(index[e.to])
        const centre = (TOP + BOTTOM) / 2
        const lane = laneY(lanes[i])
        const dx = (x2 - x1) * 0.45
        const width = 3 + (e.count / max) * 14
        const d = `M ${x1} ${centre} C ${x1 + dx} ${lane}, ${x2 - dx} ${lane}, ${x2} ${centre}`
        const peak = 0.25 * centre + 0.75 * lane // the curve's height at its midpoint
        // A ribbon that skips an even number of stages has its midpoint on a pill: nudge its label aside.
        const span = index[e.to] - index[e.from]
        const labelX = (x1 + x2) / 2 + (span % 2 === 0 ? (x2 - x1) / span / 2 : 0)
        return (
          <g key={i}>
            <path d={d} fill="none" stroke={`url(#rg-${i})`} strokeWidth={width} strokeOpacity={0.28} strokeLinecap="round" />
            <path d={d} fill="none" stroke={`url(#rg-${i})`} strokeWidth={1.6} strokeDasharray="6 14" className="flow-dash" filter="url(#glow)" />
            <text x={labelX} y={peak - width / 2 - 6} textAnchor="middle" className="fill-[#c9cdf0] text-[11px]">
              {Math.round((e.count / total) * 100)}%
            </text>
          </g>
        )
      })}

      {COLUMNS.map((c, i) => {
        const x = colX(i)
        const n = stages[c.id] ?? 0
        const active = n > 0
        return (
          <g key={c.id} opacity={active ? 1 : 0.35}>
            <text x={x} y={22} textAnchor="middle" className="fill-[#e8eaff] text-[12px] font-medium">
              {c.label}
            </text>
            <rect x={x - 9} y={TOP} width={18} height={BOTTOM - TOP} rx={9} fill="#171b38" stroke={active ? color(c.id) : '#262b52'} strokeOpacity={0.7} />
            {active && <rect x={x - 3} y={TOP + 8} width={6} height={BOTTOM - TOP - 16} rx={3} fill={color(c.id)} opacity={0.85} filter="url(#glow)" />}
            <text x={x} y={BOTTOM + 22} textAnchor="middle" className="tabular fill-[#9ba1c9] text-[11px]">
              {n} {n === 1 ? 'run' : 'runs'}
            </text>
          </g>
        )
      })}

    </svg>
      {terminalEdges.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs">
          {terminalEdges.map((e) => (
            <li key={`${e.from}-${e.to}`} className="flex items-center gap-1.5" style={{ color: TERMINALS[e.to].color }}>
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              {e.count} {TERMINALS[e.to].label.toLowerCase()} after {agents[e.from]?.name ?? e.from}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
