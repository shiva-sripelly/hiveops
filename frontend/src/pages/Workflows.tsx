import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pencil, Play, Plus, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { Link } from 'react-router'
import { api } from '../api'
import { useLauncher } from '../App'
import { AgentDot, Button, Empty, ErrorNote, PageHeader } from '../components/ui'
import { useAgentMap, useWorkflows } from '../hooks'

export function Workflows() {
  const { data: workflows, isLoading } = useWorkflows()
  const agents = useAgentMap()
  const launch = useLauncher()
  const qc = useQueryClient()
  const remove = useMutation({
    mutationFn: api.deleteWorkflow,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workflows'] }),
  })

  return (
    <>
      <PageHeader
        title="Workflows"
        subtitle="Reusable pipelines of specialised agents. Add approval gates wherever a human should sign off."
        action={
          <Link to="/workflows/new">
            <Button variant="primary">
              <Plus size={16} /> New workflow
            </Button>
          </Link>
        }
      />
      <ErrorNote error={remove.error} />
      {isLoading && <p className="text-muted">Loading workflows…</p>}
      {workflows?.length === 0 && (
        <Empty title="No workflows yet" action={<Link to="/workflows/new"><Button variant="primary">Create a workflow</Button></Link>}>
          A workflow chains agents together: research, analysis, writing, review and delivery.
        </Empty>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {workflows?.map((w) => (
          <article key={w.id} className="panel flex flex-col gap-4 p-5">
            <header className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-lg font-semibold">{w.name}</h2>
                <p className="mt-1 text-sm text-muted">{w.description}</p>
              </div>
              <span className="shrink-0 rounded-full border border-line px-2.5 py-0.5 text-xs text-muted">{w.runCount ?? 0} runs</span>
            </header>

            {w.mode === 'auto' ? (
              <div className="flex items-center gap-3 rounded-xl border border-violet/30 bg-violet/10 p-3 text-sm">
                <Sparkles size={18} className="text-violet" />
                The Supervisor plans each run and routes steps to the right specialists.
              </div>
            ) : (
              <ol className="flex flex-wrap items-center gap-2">
                {w.steps.map((s, i) => (
                  <li key={i} className="flex items-center gap-2">
                    {i > 0 && <span className="h-px w-4 bg-line" aria-hidden="true" />}
                    <span className="inline-flex items-center gap-2 rounded-xl border border-line bg-panel-2 px-3 py-1.5 text-sm">
                      <AgentDot color={agents[s.agent]?.color} />
                      {agents[s.agent]?.name ?? s.agent}
                      {s.approval && <ShieldCheck size={14} className="text-warn" aria-label="Requires approval" />}
                    </span>
                  </li>
                ))}
              </ol>
            )}

            <footer className="mt-auto flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => launch(w.id)}>
                <Play size={15} /> Run
              </Button>
              <Link to={`/workflows/${w.id}`}>
                <Button>
                  <Pencil size={15} /> Edit
                </Button>
              </Link>
              <Button
                variant="ghost"
                onClick={() => {
                  if (confirm(`Delete the workflow "${w.name}"? Past runs are kept.`)) remove.mutate(w.id)
                }}
              >
                <Trash2 size={15} /> Delete
              </Button>
            </footer>
          </article>
        ))}
      </div>
    </>
  )
}
