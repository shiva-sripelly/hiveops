import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  Flag,
  ListTree,
  Mail,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Wrench,
  XCircle,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { api, type RunDetail, type RunEvent } from '../api'
import { ApprovalBody, DecisionForm } from '../components/DecisionForm'
import { Markdown } from '../components/Markdown'
import { AgentDot, Button, ErrorNote, Panel, StatusPill } from '../components/ui'
import { compact, duration, money } from '../format'
import { useAgentMap } from '../hooks'

const TERMINAL = new Set(['completed', 'failed', 'rejected'])

/** Follows a run's events over Server-Sent Events, resuming after the last seen seq. */
function useRunEvents(runId: string, initial: RunEvent[] | undefined, live: boolean) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const qc = useQueryClient()
  useEffect(() => {
    if (initial) setEvents((prev) => (prev.length > initial.length ? prev : initial))
  }, [initial])

  const lastSeq = events.length ? events[events.length - 1].seq : (initial?.at(-1)?.seq ?? 0)
  const lastRef = useRef(lastSeq)
  lastRef.current = lastSeq

  useEffect(() => {
    if (!live || initial === undefined) return
    const source = new EventSource(`/api/runs/${runId}/stream?after=${lastRef.current}`)
    source.addEventListener('run_event', (msg) => {
      const ev: RunEvent = JSON.parse((msg as MessageEvent).data)
      setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev].sort((a, b) => a.seq - b.seq)))
      if (['approval_requested', 'run_finished', 'agent_output', 'plan', 'approval_decided'].includes(ev.type)) {
        qc.invalidateQueries({ queryKey: ['run', runId] })
      }
    })
    source.addEventListener('end', () => {
      source.close()
      qc.invalidateQueries({ queryKey: ['run', runId] })
    })
    return () => source.close()
    // Reconnect only when the run changes or (re)becomes live; EventSource itself retries with Last-Event-ID.
  }, [runId, live, initial === undefined, qc])

  return events
}

export function RunDetailPage() {
  const { id = '' } = useParams()
  const agents = useAgentMap()
  const qc = useQueryClient()
  const { data: run, error } = useQuery({
    queryKey: ['run', id],
    queryFn: () => api.run(id),
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.status) ? false : 4000),
  })
  const live = !!run && !TERMINAL.has(run.status)
  const events = useRunEvents(id, run?.events, live)
  const cancel = useMutation({ mutationFn: () => api.cancelRun(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['run', id] }) })

  if (error) return <ErrorNote error={error} />
  if (!run) return <p className="text-muted">Loading run…</p>
  const pending = run.approvals.find((a) => a.status === 'pending')

  return (
    <>
      <Link to="/runs" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft size={15} /> All runs
      </Link>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <StatusPill status={run.status} />
            <span className="text-sm text-muted">
              {run.workflowName} {run.mode === 'auto' ? '(Supervisor autopilot)' : ''}
            </span>
          </div>
          <h1 className="font-display text-2xl font-semibold leading-snug">{run.task}</h1>
        </div>
        {(run.status === 'queued' || run.status === 'awaiting_approval') && (
          <Button variant="ghost" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            Cancel run
          </Button>
        )}
      </header>

      <Pipeline run={run} events={events} agents={agents} />

      {pending && (
        <section className="panel mt-4 border-warn/40 p-5">
          <h2 className="mb-1 flex items-center gap-2 font-display font-semibold text-warn">
            <ShieldAlert size={18} /> Waiting for your decision
          </h2>
          <p className="mb-4 text-sm text-muted">{pending.title}</p>
          <ApprovalBody approval={pending} />
          <div className="mt-4">
            <DecisionForm approval={pending} />
          </div>
        </section>
      )}

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1fr_420px]">
        <Panel title="Result">
          {run.error && <ErrorNote error={run.error} />}
          {run.output ? <Markdown text={run.output} /> : !run.error && <p className="text-sm text-muted">The final result appears here when the run finishes.</p>}
          {run.sources.length > 0 && (
            <div className="mt-5 border-t border-line pt-4">
              <p className="mb-2 text-sm text-muted">Sources used</p>
              <div className="flex flex-wrap gap-2">
                {run.sources.map((s) => (
                  <span key={s} className="rounded-lg border border-cyan/30 bg-cyan/10 px-2.5 py-1 text-xs text-cyan">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {run.deliveries.length > 0 && (
            <div className="mt-5 border-t border-line pt-4">
              <p className="mb-2 text-sm text-muted">Deliveries</p>
              {run.deliveries.map((d, i) => (
                <p key={i} className="flex items-center gap-2 text-sm">
                  <Mail size={15} className={d.delivered ? 'text-good' : 'text-bad'} />
                  {d.channel === 'slack' ? 'Slack' : 'Email'} to {d.recipient}
                  <span className="text-xs text-muted">({d.detail})</span>
                </p>
              ))}
            </div>
          )}
        </Panel>

        <div className="flex flex-col gap-4">
          <Panel title="Run metrics">
            <dl className="tabular grid grid-cols-2 gap-3 text-sm">
              {[
                ['Tokens in', compact(run.tokensIn)],
                ['Tokens out', compact(run.tokensOut)],
                ['Cost', money(run.cost)],
                ['Active time', duration(run.latencyMs)],
                ['Model', run.model],
                ['Events', String(events.length)],
              ].map(([k, v]) => (
                <div key={k} className="rounded-xl border border-line bg-panel-2 px-3 py-2">
                  <dt className="text-xs text-muted">{k}</dt>
                  <dd className="truncate font-medium">{v}</dd>
                </div>
              ))}
            </dl>
          </Panel>
          <Panel
            title="Execution log"
            action={
              live ? (
                <span className="flex items-center gap-1.5 text-xs text-good">
                  <span className="live-dot h-1.5 w-1.5 rounded-full bg-good" /> Streaming
                </span>
              ) : undefined
            }
          >
            <EventLog events={events} agents={agents} />
          </Panel>
        </div>
      </div>
    </>
  )
}

function Pipeline({ run, events, agents }: { run: RunDetail; events: RunEvent[]; agents: ReturnType<typeof useAgentMap> }) {
  const planEvent = [...events].reverse().find((e) => e.type === 'plan')
  const steps = (planEvent?.data.steps as { agent: string }[] | undefined) ?? run.steps
  const started = events.filter((e) => e.type === 'agent_start' && e.agent !== 'planner').length
  const outputs = events.filter((e) => e.type === 'agent_output').length
  if (!steps.length) {
    return <div className="panel p-5 text-sm text-muted">The Supervisor is planning this run…</div>
  }
  return (
    <ol className="panel flex flex-wrap items-center gap-2 p-4" aria-label="Pipeline progress">
      {steps.map((s, i) => {
        const done = i < outputs
        const active = !done && i < started && !TERMINAL.has(run.status)
        const waiting = run.status === 'awaiting_approval' && i === outputs - 1
        return (
          <li key={i} className="flex items-center gap-2">
            {i > 0 && <span className={`h-px w-6 ${done || active ? 'bg-violet' : 'bg-line'}`} aria-hidden="true" />}
            <span
              className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-sm ${
                waiting ? 'border-warn/60 bg-warn/10' : active ? 'border-violet bg-violet/15' : done ? 'border-line bg-panel-2' : 'border-dashed border-line text-muted'
              }`}
            >
              <AgentDot color={agents[s.agent]?.color} size={9} />
              {agents[s.agent]?.name ?? s.agent}
              {done && !waiting && <CheckCircle2 size={14} className="text-good" />}
              {active && <span className="live-dot h-1.5 w-1.5 rounded-full bg-violet" />}
              {waiting && <ShieldCheck size={14} className="text-warn" />}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

const ICONS: Record<string, ReactNode> = {
  run_started: <Flag size={14} />,
  plan: <ListTree size={14} />,
  agent_start: <Bot size={14} />,
  llm_call: <BrainCircuit size={14} />,
  thought: <Sparkles size={14} />,
  tool_call: <Wrench size={14} />,
  tool_result: <CircleDot size={14} />,
  tool_error: <AlertTriangle size={14} />,
  agent_error: <AlertTriangle size={14} />,
  agent_output: <CheckCircle2 size={14} />,
  action_proposed: <ShieldAlert size={14} />,
  approval_requested: <ShieldAlert size={14} />,
  approval_decided: <ShieldCheck size={14} />,
  approved: <ShieldCheck size={14} />,
  rejected: <XCircle size={14} />,
  run_completed: <CheckCircle2 size={14} />,
  run_finished: <Flag size={14} />,
}

function EventLog({ events, agents }: { events: RunEvent[]; agents: ReturnType<typeof useAgentMap> }) {
  const [open, setOpen] = useState<number | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const count = events.length
  useEffect(() => bottom.current?.scrollIntoView({ block: 'nearest' }), [count])
  const visible = useMemo(() => events, [events])
  if (!count) return <p className="text-sm text-muted">Waiting for the first event…</p>

  return (
    <div className="max-h-[560px] overflow-y-auto pr-1">
      <ol className="relative flex flex-col">
        {visible.map((e) => {
          const color = e.agent ? agents[e.agent]?.color : undefined
          const tone = /error|rejected/.test(e.type) ? 'text-bad' : /approval|proposed/.test(e.type) ? 'text-warn' : e.type === 'llm_call' ? 'text-muted' : 'text-ink'
          const expandable = e.message.length > 140 || Object.keys(e.data ?? {}).length > 0
          return (
            <li key={e.seq} className="relative border-l border-line pb-3 pl-5">
              <span className="absolute -left-[9px] top-0.5 grid h-[18px] w-[18px] place-items-center rounded-full bg-panel text-muted" style={color ? { color } : undefined}>
                {ICONS[e.type] ?? <CircleDot size={14} />}
              </span>
              <button
                className="w-full text-left"
                onClick={() => expandable && setOpen(open === e.seq ? null : e.seq)}
                aria-expanded={expandable ? open === e.seq : undefined}
              >
                <p className="flex items-center gap-2 text-xs text-muted">
                  <span className="tabular">{new Date(e.ts).toLocaleTimeString()}</span>
                  {e.agent && <span style={{ color }}>{agents[e.agent]?.name ?? e.agent}</span>}
                  <span>{e.type.replace(/_/g, ' ')}</span>
                </p>
                <p className={`mt-0.5 text-sm ${tone} ${open === e.seq ? 'whitespace-pre-wrap' : 'line-clamp-2'}`}>{e.message}</p>
              </button>
              {open === e.seq && Object.keys(e.data ?? {}).length > 0 && (
                <pre className="mt-2 max-h-60 overflow-auto rounded-lg bg-bg p-2.5 text-[11px] text-muted">{JSON.stringify(e.data, null, 2)}</pre>
              )}
            </li>
          )
        })}
      </ol>
      <div ref={bottom} />
    </div>
  )
}
