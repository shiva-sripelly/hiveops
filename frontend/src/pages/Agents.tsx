import { ShieldCheck, Wrench } from 'lucide-react'
import { PageHeader } from '../components/ui'
import { compact, duration, money, pct } from '../format'
import { useAgents, useDashboard } from '../hooks'

export function Agents() {
  const { data: agents = [] } = useAgents()
  const { data: dash } = useDashboard()
  const health = Object.fromEntries((dash?.agents ?? []).map((a) => [a.id, a]))

  return (
    <>
      <PageHeader title="Agents" subtitle="Each specialist has one job, a fixed set of tools, and its own prompt. Statistics cover the last 30 days." />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {agents.map((a) => {
          const h = health[a.id]
          return (
            <article key={a.id} className="panel flex flex-col gap-4 p-5">
              <header className="flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl font-display text-lg font-semibold" style={{ background: `${a.color}22`, color: a.color }}>
                  {a.name[0]}
                </span>
                <div>
                  <h2 className="font-display text-lg font-semibold">{a.name}</h2>
                  <p className="text-sm text-muted">{a.role}</p>
                </div>
              </header>
              <dl className="tabular grid grid-cols-4 gap-2 text-center">
                {[
                  ['Calls', h ? String(h.calls) : '–'],
                  ['Latency', duration(h?.avgLatencyMs)],
                  ['Tokens', compact(h?.tokens)],
                  ['Errors', pct(h?.errorRate, 1)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-xl bg-panel-2 px-2 py-2">
                    <dt className="text-[11px] text-muted">{k}</dt>
                    <dd className="text-sm font-medium">{v}</dd>
                  </div>
                ))}
              </dl>
              <div>
                <p className="mb-2 text-sm text-muted">Tools</p>
                {a.tools.length === 0 ? (
                  <p className="text-sm text-muted">No tools. Works only from the task and the previous steps.</p>
                ) : (
                  <ul className="flex flex-col gap-1.5">
                    {a.tools.map((t) => (
                      <li key={t.name} className="flex items-start gap-2 text-sm">
                        {t.requiresApproval ? <ShieldCheck size={15} className="mt-0.5 shrink-0 text-warn" /> : <Wrench size={15} className="mt-0.5 shrink-0 text-muted" />}
                        <span>
                          <code className="text-[13px]">{t.name}</code>
                          {t.requiresApproval && <span className="ml-1.5 text-xs text-warn">needs approval</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <details className="mt-auto text-sm">
                <summary className="cursor-pointer text-[#a99bff] hover:text-white">System prompt</summary>
                <p className="mt-2 rounded-xl bg-bg p-3 leading-relaxed text-muted">{a.system}</p>
              </details>
              {h && h.cost > 0 && <p className="text-xs text-muted">Spend: {money(h.cost)}</p>}
            </article>
          )
        })}
      </div>
    </>
  )
}
