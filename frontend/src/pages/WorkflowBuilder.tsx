import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Plus, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { api, type Step } from '../api'
import { AgentDot, Button, ErrorNote, PageHeader, Panel } from '../components/ui'
import { useAgents } from '../hooks'

const EMPTY_STEP: Step = { agent: 'researcher', instruction: '', approval: false }

export function WorkflowBuilder() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: agentList = [] } = useAgents()
  const specialists = agentList.filter((a) => a.id !== 'planner')
  const agents = Object.fromEntries(agentList.map((a) => [a.id, a]))
  const existing = useQuery({ queryKey: ['workflow', id], queryFn: () => api.workflow(id!), enabled: !!id })

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [mode, setMode] = useState<'custom' | 'auto'>('custom')
  const [defaultTask, setDefaultTask] = useState('')
  const [steps, setSteps] = useState<Step[]>([{ ...EMPTY_STEP }, { agent: 'writer', instruction: '', approval: false }])

  useEffect(() => {
    const w = existing.data
    if (!w) return
    setName(w.name)
    setDescription(w.description)
    setMode(w.mode)
    setDefaultTask(w.defaultTask)
    setSteps(w.steps.length ? w.steps : [{ ...EMPTY_STEP }])
  }, [existing.data])

  const save = useMutation({
    mutationFn: () => api.saveWorkflow({ name, description, mode, steps: mode === 'custom' ? steps : [], defaultTask }, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflows'] })
      navigate('/workflows')
    },
  })

  const update = (i: number, patch: Partial<Step>) => setSteps((s) => s.map((st, j) => (j === i ? { ...st, ...patch } : st)))
  const move = (i: number, d: -1 | 1) =>
    setSteps((s) => {
      const next = [...s]
      ;[next[i], next[i + d]] = [next[i + d], next[i]]
      return next
    })

  const field = 'rounded-xl border border-line bg-panel-2 px-3 py-2.5 placeholder:text-muted/70'

  return (
    <>
      <PageHeader title={id ? 'Edit workflow' : 'New workflow'} subtitle="Chain specialised agents into a pipeline, or let the Supervisor plan each run." />
      <form
        className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_380px]"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <div className="flex flex-col gap-4">
          <Panel title="Details">
            <div className="grid gap-4 md:grid-cols-2">
              <label className="flex flex-col gap-2 text-sm">
                <span className="text-muted">Name</span>
                <input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} className={`${field} min-h-11`} placeholder="e.g. Weekly sales digest" />
              </label>
              <label className="flex flex-col gap-2 text-sm">
                <span className="text-muted">Description</span>
                <input value={description} onChange={(e) => setDescription(e.target.value)} className={`${field} min-h-11`} placeholder="What this workflow is for" />
              </label>
              <label className="flex flex-col gap-2 text-sm md:col-span-2">
                <span className="text-muted">Default task</span>
                <textarea
                  rows={2}
                  value={defaultTask}
                  onChange={(e) => setDefaultTask(e.target.value)}
                  className={field}
                  placeholder="Used when a run is started without a task"
                />
              </label>
            </div>
            <fieldset className="mt-5">
              <legend className="mb-2 text-sm text-muted">How should work be routed?</legend>
              <div className="grid gap-3 md:grid-cols-2">
                {(
                  [
                    ['custom', 'Fixed pipeline', 'Steps run in the order you design, with approval gates where you choose.'],
                    ['auto', 'Supervisor autopilot', 'A Supervisor agent reads each task and decides which specialists to use.'],
                  ] as const
                ).map(([value, title, text]) => (
                  <label
                    key={value}
                    className={`flex cursor-pointer gap-3 rounded-xl border p-4 ${mode === value ? 'border-violet bg-violet/10' : 'border-line bg-panel-2'}`}
                  >
                    <input type="radio" name="mode" value={value} checked={mode === value} onChange={() => setMode(value)} className="mt-1 accent-[#8b6cff]" />
                    <span>
                      <span className="block font-medium">{title}</span>
                      <span className="text-sm text-muted">{text}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          </Panel>

          {mode === 'custom' ? (
            <Panel title="Steps" action={<span className="text-xs text-muted">{steps.length} of 12</span>}>
              <ol className="flex flex-col gap-3">
                {steps.map((s, i) => (
                  <li key={i} className="rounded-2xl border border-line bg-panel-2 p-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="tabular grid h-7 w-7 place-items-center rounded-full bg-bg text-xs text-muted">{i + 1}</span>
                      <label className="sr-only" htmlFor={`agent-${i}`}>
                        Agent for step {i + 1}
                      </label>
                      <span className="flex items-center gap-2">
                        <AgentDot color={agents[s.agent]?.color} size={10} />
                        <select id={`agent-${i}`} value={s.agent} onChange={(e) => update(i, { agent: e.target.value })} className="min-h-10 rounded-lg border border-line bg-bg px-2">
                          {specialists.map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}
                            </option>
                          ))}
                        </select>
                      </span>
                      <span className="hidden flex-1 text-sm text-muted md:block">{agents[s.agent]?.role}</span>
                      <div className="ml-auto flex gap-1">
                        <Button type="button" variant="ghost" className="px-2.5" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move step up">
                          <ArrowUp size={16} />
                        </Button>
                        <Button type="button" variant="ghost" className="px-2.5" disabled={i === steps.length - 1} onClick={() => move(i, 1)} aria-label="Move step down">
                          <ArrowDown size={16} />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          className="px-2.5"
                          disabled={steps.length === 1}
                          onClick={() => setSteps((st) => st.filter((_, j) => j !== i))}
                          aria-label="Remove step"
                        >
                          <Trash2 size={16} />
                        </Button>
                      </div>
                    </div>
                    <label className="mt-3 flex flex-col gap-1.5 text-sm">
                      <span className="text-muted">Instruction</span>
                      <textarea
                        rows={2}
                        value={s.instruction}
                        onChange={(e) => update(i, { instruction: e.target.value })}
                        className="rounded-xl border border-line bg-bg px-3 py-2"
                        placeholder={agents[s.agent]?.role}
                      />
                    </label>
                    <label className="mt-3 flex items-center gap-2.5 text-sm">
                      <input type="checkbox" checked={s.approval} onChange={(e) => update(i, { approval: e.target.checked })} className="h-4 w-4 accent-[#fbbf24]" />
                      A person must approve this step's output before the workflow continues
                    </label>
                  </li>
                ))}
              </ol>
              <Button type="button" className="mt-3" disabled={steps.length >= 12} onClick={() => setSteps((s) => [...s, { ...EMPTY_STEP }])}>
                <Plus size={16} /> Add step
              </Button>
            </Panel>
          ) : (
            <Panel title="Supervisor autopilot">
              <p className="flex items-start gap-3 text-sm text-muted">
                <Sparkles size={18} className="mt-0.5 shrink-0 text-violet" />
                For every run, the Supervisor reads the task and builds a plan using the researcher, analyst, writer, reviewer and comms agents. Sending email or Slack messages
                always pauses for human approval.
              </p>
            </Panel>
          )}
          <ErrorNote error={save.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => navigate('/workflows')}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={save.isPending || !name.trim()}>
              {save.isPending ? 'Saving…' : id ? 'Save changes' : 'Create workflow'}
            </Button>
          </div>
        </div>

        <aside className="flex flex-col gap-4">
          <Panel title="Pipeline preview">
            <ol className="relative flex flex-col gap-0">
              <li className="flex items-center gap-3 pb-4 text-sm text-muted">
                <span className="grid h-8 w-8 place-items-center rounded-full border border-line">in</span> Task arrives
              </li>
              {mode === 'auto' ? (
                <li className="flex items-center gap-3 pb-4 text-sm">
                  <AgentDot color={agents.planner?.color} size={12} /> Supervisor plans and routes the work
                </li>
              ) : (
                steps.map((s, i) => (
                  <li key={i} className="pb-4">
                    <div className="flex items-center gap-3 text-sm">
                      <span className="grid h-8 w-8 place-items-center rounded-full" style={{ background: `${agents[s.agent]?.color ?? '#8b6cff'}22` }}>
                        <AgentDot color={agents[s.agent]?.color} size={10} />
                      </span>
                      <span className="font-medium">{agents[s.agent]?.name ?? s.agent}</span>
                    </div>
                    {(s.approval || s.agent === 'communicator') && (
                      <p className="ml-11 mt-1.5 flex items-center gap-1.5 text-xs text-warn">
                        <ShieldCheck size={13} />
                        {s.agent === 'communicator' && !s.approval ? 'Messages wait for approval' : 'Human approval gate'}
                      </p>
                    )}
                  </li>
                ))
              )}
              <li className="flex items-center gap-3 text-sm text-good">
                <span className="grid h-8 w-8 place-items-center rounded-full border border-good/40">✓</span> Result delivered
              </li>
            </ol>
          </Panel>
          <Panel title="Tools each agent can use">
            <ul className="flex flex-col gap-3 text-sm">
              {specialists.map((a) => (
                <li key={a.id}>
                  <p className="flex items-center gap-2 font-medium">
                    <AgentDot color={a.color} /> {a.name}
                  </p>
                  <p className="ml-4 mt-0.5 text-xs text-muted">{a.tools.length ? a.tools.map((t) => t.name).join(', ') : 'Writes from the previous steps'}</p>
                </li>
              ))}
            </ul>
          </Panel>
        </aside>
      </form>
    </>
  )
}
