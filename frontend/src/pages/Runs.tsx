import { useState } from 'react'
import { Link } from 'react-router'
import { useLauncher } from '../App'
import { AgentChip, Button, Empty, PageHeader, StatusPill } from '../components/ui'
import { compact, duration, money, STATUS_LABEL, timeAgo } from '../format'
import { useAgentMap, useRuns } from '../hooks'

const FILTERS = ['', 'running', 'awaiting_approval', 'completed', 'failed', 'rejected']

export function Runs() {
  const [status, setStatus] = useState('')
  const { data: runs, isLoading } = useRuns(status || undefined)
  const agents = useAgentMap()
  const launch = useLauncher()

  return (
    <>
      <PageHeader title="Runs" subtitle="Every task delegated to your agents, with its route, cost and outcome." />
      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button
            key={f || 'all'}
            onClick={() => setStatus(f)}
            aria-pressed={status === f}
            className={`min-h-9 rounded-full border px-3.5 text-sm ${status === f ? 'border-violet bg-violet/15 text-ink' : 'border-line text-muted hover:text-ink'}`}
          >
            {f ? STATUS_LABEL[f] : 'All runs'}
          </button>
        ))}
      </div>
      {isLoading && <p className="text-muted">Loading runs…</p>}
      {runs?.length === 0 && (
        <Empty title={status ? 'No runs with this status' : 'No runs yet'} action={<Button variant="primary" onClick={() => launch()}>Start a run</Button>} />
      )}
      {!!runs?.length && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted">
                <th className="px-5 py-3 font-medium">Task</th>
                <th className="px-3 py-3 font-medium">Route</th>
                <th className="px-3 py-3 font-medium">Status</th>
                <th className="px-3 py-3 font-medium">Tokens</th>
                <th className="px-3 py-3 font-medium">Cost</th>
                <th className="px-3 py-3 font-medium">Active time</th>
                <th className="px-5 py-3 font-medium">Started</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {runs.map((r) => (
                <tr key={r.id} className="border-t border-line/70 hover:bg-panel-2/50">
                  <td className="max-w-[360px] px-5 py-3">
                    <Link to={`/runs/${r.id}`} className="block truncate font-medium hover:text-white">
                      {r.task}
                    </Link>
                    <span className="text-xs text-muted">{r.workflowName}</span>
                  </td>
                  <td className="px-3">
                    <div className="flex flex-wrap gap-1">
                      {r.plan.length ? r.plan.map((p, i) => <AgentChip key={i} id={p} agents={agents} />) : <span className="text-muted">Planning…</span>}
                    </div>
                  </td>
                  <td className="px-3">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="px-3">{compact(r.tokens)}</td>
                  <td className="px-3">{money(r.cost)}</td>
                  <td className="px-3">{duration(r.latencyMs)}</td>
                  <td className="whitespace-nowrap px-5 text-muted">{timeAgo(r.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
