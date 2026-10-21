import { Activity, Bot, CircleDollarSign, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useLauncher } from '../App'
import { RoutingMap } from '../components/RoutingMap'
import { AgentChip, AgentDot, Button, Change, Empty, Kpi, PageHeader, Panel, StatusPill, TextLink } from '../components/ui'
import { compact, duration, money, pct, ratio, timeAgo } from '../format'
import { useAgentMap, useDashboard } from '../hooks'

export function Overview() {
  const { data, isLoading } = useDashboard()
  const agents = useAgentMap()
  const launch = useLauncher()

  if (isLoading || !data) return <p className="text-muted">Loading the command center…</p>
  const k = data.kpis
  const doneRuns = Object.entries(data.statusCounts).filter(([s]) => ['completed', 'failed', 'rejected'].includes(s))
  const finished = doneRuns.reduce((n, [, c]) => n + c, 0)

  return (
    <>
      <PageHeader
        title="AI workflow command center"
        subtitle="Routing, quality, approvals, cost and agent health across every workflow, in one place."
        action={
          <Link to="/workflows/new">
            <Button>Build a workflow</Button>
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={<CircleDollarSign size={22} />} label="LLM spend, last 30 days" value={money(k.spend)} detail={<Change value={k.spendChange} invert />} />
        <Kpi
          icon={<Activity size={22} />}
          tone="cyan"
          label="Run success rate"
          value={pct(k.successRate, 1)}
          detail={`${finished} finished of ${k.runs} runs`}
        />
        <Kpi
          icon={<ShieldCheck size={22} />}
          tone="good"
          label="Approval rate"
          value={pct(k.approvalRate)}
          detail={k.pendingApprovals ? `${k.pendingApprovals} waiting for review` : 'Nothing waiting for review'}
        />
        <Kpi icon={<Bot size={22} />} tone="warn" label="Active agents" value={`${k.activeAgents} / ${k.totalAgents}`} detail="Used in the last 7 days" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel
          className="xl:col-span-2"
          title="Agent routing map"
          action={
            <span className="flex items-center gap-1.5 text-xs text-good">
              <span className="live-dot h-1.5 w-1.5 rounded-full bg-good" /> Live
            </span>
          }
        >
          <RoutingMap edges={data.routing.edges} stages={data.routing.stages} agents={agents} />
        </Panel>

        <Panel title={`Approval queue (${k.pendingApprovals})`} action={<TextLink to="/approvals">View all</TextLink>}>
          {data.pendingApprovals.length === 0 ? (
            <Empty title="All clear">Agents pause here when an action or a draft needs a human decision.</Empty>
          ) : (
            <ul className="flex flex-col gap-2">
              {data.pendingApprovals.map((a) => (
                <li key={a.id}>
                  <Link to="/approvals" className="flex items-center gap-3 rounded-xl border border-line bg-panel-2 p-3 hover:border-violet/50">
                    <AgentDot color={agents[a.agent]?.color} size={10} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{a.title}</p>
                      <p className="text-xs text-muted">
                        {agents[a.agent]?.name ?? a.agent}, {timeAgo(a.createdAt)}
                      </p>
                    </div>
                    <StatusPill status="pending" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel title="Cost pulse" action={<span className="text-xs text-muted">Last 14 days</span>}>
          <p className="tabular font-display text-2xl font-semibold">{money(k.spend)}</p>
          <p className="mb-3 text-xs text-muted">
            {compact(k.tokens)} tokens, average run {duration(k.avgLatencyMs)}
          </p>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data.daily} margin={{ left: -18, right: 4, top: 4, bottom: 0 }}>
                <defs>
                  <linearGradient id="costFill" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="#8b6cff" stopOpacity={0.6} />
                    <stop offset="100%" stopColor="#8b6cff" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#262b52" strokeDasharray="3 6" vertical={false} />
                <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fill: '#9ba1c9', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(v: number) => `$${v < 0.1 ? v.toFixed(3) : v.toFixed(2)}`} tick={{ fill: '#9ba1c9', fontSize: 11 }} axisLine={false} tickLine={false} width={56} />
                <Tooltip
                  contentStyle={{ background: '#171b38', border: '1px solid #262b52', borderRadius: 12, color: '#e8eaff' }}
                  formatter={(v) => [money(Number(v)), 'Spend']}
                />
                <Area type="monotone" dataKey="cost" stroke="#a48cff" strokeWidth={2} fill="url(#costFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Agent health" className="xl:col-span-2" action={<TextLink to="/agents">View agents</TextLink>}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th className="pb-2 font-medium">Agent</th>
                  <th className="pb-2 font-medium">LLM calls</th>
                  <th className="pb-2 font-medium">Avg latency</th>
                  <th className="pb-2 font-medium">Tokens</th>
                  <th className="pb-2 font-medium">Cost</th>
                  <th className="pb-2 font-medium">Error rate</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {data.agents.map((a) => (
                  <tr key={a.id} className="border-t border-line/70">
                    <td className="py-2.5">
                      <span className="flex items-center gap-2">
                        <AgentDot color={a.color} /> {a.name}
                      </span>
                    </td>
                    <td>{a.calls}</td>
                    <td>{duration(a.avgLatencyMs)}</td>
                    <td>{compact(a.tokens)}</td>
                    <td>{money(a.cost)}</td>
                    <td className={a.errorRate > 5 ? 'text-bad' : 'text-good'}>{pct(a.errorRate, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel title="Recent runs" className="xl:col-span-2" action={<TextLink to="/runs">View all</TextLink>}>
          {data.recentRuns.length === 0 ? (
            <Empty title="No runs yet" action={<Button variant="primary" onClick={() => launch()}>Start your first run</Button>}>
              Delegate a task to a workflow and watch the agents work in real time.
            </Empty>
          ) : (
            <ul className="divide-y divide-line/70">
              {data.recentRuns.map((r) => (
                <li key={r.id}>
                  <Link to={`/runs/${r.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3 hover:bg-panel-2/40">
                    <div className="min-w-0 flex-1 basis-64">
                      <p className="truncate font-medium">{r.task}</p>
                      <p className="text-xs text-muted">
                        {r.workflowName}, {timeAgo(r.createdAt)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {r.plan.map((p, i) => (
                        <AgentChip key={i} id={p} agents={agents} />
                      ))}
                    </div>
                    <StatusPill status={r.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="RAG quality" action={<TextLink to="/evals">Evaluations</TextLink>}>
          {data.latestEval ? (
            <div className="grid grid-cols-2 gap-3">
              {[
                ['Pass rate', ratio(data.latestEval.metrics.passRate)],
                ['Retrieval hit rate', ratio(data.latestEval.metrics.retrievalHitRate)],
                ['Answer recall', ratio(data.latestEval.metrics.avgRecall)],
                ['Groundedness', ratio(data.latestEval.metrics.avgGroundedness)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-line bg-panel-2 p-3">
                  <p className="text-xs text-muted">{label}</p>
                  <p className="tabular font-display text-xl font-semibold">{value}</p>
                </div>
              ))}
              <p className="col-span-2 text-xs text-muted">Last evaluated {timeAgo(data.latestEval.createdAt)}</p>
            </div>
          ) : (
            <Empty title="Not evaluated yet" action={<Link to="/evals"><Button>Run an evaluation</Button></Link>}>
              Score retrieval and answer quality against a test set before trusting the agents.
            </Empty>
          )}
        </Panel>
      </div>
    </>
  )
}
