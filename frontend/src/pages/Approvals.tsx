import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { ApprovalBody, DecisionForm } from '../components/DecisionForm'
import { AgentDot, Empty, PageHeader, StatusPill } from '../components/ui'
import { timeAgo } from '../format'
import { useAgentMap, usePendingApprovals } from '../hooks'

export function Approvals() {
  const [tab, setTab] = useState<'pending' | 'history'>('pending')
  const agents = useAgentMap()
  const { data: pending = [], isLoading } = usePendingApprovals()
  const history = useQuery({ queryKey: ['approvals', 'all'], queryFn: () => api.approvals(), enabled: tab === 'history', refetchInterval: 5000 })

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Agents never send messages or skip a review gate on their own. Every decision here is recorded in the run's audit log."
      />
      <div className="mb-5 flex gap-2" role="tablist">
        {(
          [
            ['pending', `Waiting (${pending.length})`],
            ['history', 'History'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`min-h-10 rounded-xl px-4 text-sm ${tab === key ? 'bg-panel-2 text-ink shadow-[inset_0_0_0_1px_#262b52]' : 'text-muted hover:text-ink'}`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'pending' && (
        <>
          {isLoading && <p className="text-muted">Loading…</p>}
          {!isLoading && pending.length === 0 && <Empty title="Nothing needs your review">New requests appear here as soon as an agent reaches an approval gate.</Empty>}
          <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
            {pending.map((a) => (
              <article key={a.id} className="panel flex flex-col gap-4 p-5">
                <header className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-sm text-muted">
                      <AgentDot color={agents[a.agent]?.color} /> {agents[a.agent]?.name ?? a.agent}, {timeAgo(a.createdAt)}
                    </p>
                    <h2 className="mt-1 font-display text-lg font-semibold">{a.title}</h2>
                    <Link to={`/runs/${a.runId}`} className="mt-1 block truncate text-sm text-[#a99bff] hover:text-white">
                      {a.workflowName}: {a.task}
                    </Link>
                  </div>
                  <span className="rounded-full border border-line px-2.5 py-0.5 text-xs text-muted">
                    {a.kind === 'tool_action' ? 'Outbound action' : 'Output review'}
                  </span>
                </header>
                <ApprovalBody approval={a} />
                <DecisionForm approval={a} />
              </article>
            ))}
          </div>
        </>
      )}

      {tab === 'history' && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted">
                <th className="px-5 py-3 font-medium">Request</th>
                <th className="px-3 py-3 font-medium">Agent</th>
                <th className="px-3 py-3 font-medium">Decision</th>
                <th className="px-3 py-3 font-medium">Comment</th>
                <th className="px-5 py-3 font-medium">Decided</th>
              </tr>
            </thead>
            <tbody>
              {history.data?.map((a) => (
                <tr key={a.id} className="border-t border-line/70">
                  <td className="px-5 py-3">
                    <Link to={`/runs/${a.runId}`} className="font-medium hover:text-white">
                      {a.title}
                    </Link>
                    <p className="text-xs text-muted">{a.workflowName}</p>
                  </td>
                  <td className="px-3">
                    <span className="flex items-center gap-2">
                      <AgentDot color={agents[a.agent]?.color} /> {agents[a.agent]?.name ?? a.agent}
                    </span>
                  </td>
                  <td className="px-3">
                    <StatusPill status={a.status} />
                  </td>
                  <td className="max-w-[280px] truncate px-3 text-muted">{a.comment || '–'}</td>
                  <td className="whitespace-nowrap px-5 text-muted">{a.decidedAt ? timeAgo(a.decidedAt) : 'Waiting'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
