import { useMutation, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { api, type Workflow } from '../api'
import { useAgentMap, useWorkflows } from '../hooks'
import { AgentChip, Button, ErrorNote } from './ui'

/** Dialog to delegate a task to a workflow. */
export function RunLauncher({ open, onClose, workflowId }: { open: boolean; onClose: () => void; workflowId?: string }) {
  const { data: workflows = [] } = useWorkflows()
  const agents = useAgentMap()
  const [selected, setSelected] = useState<string | undefined>(workflowId)
  const [task, setTask] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const wf: Workflow | undefined = workflows.find((w) => w.id === (selected ?? workflows[0]?.id))

  useEffect(() => {
    const d = dialog.current
    if (!d) return
    if (open && !d.open) {
      setSelected(workflowId)
      setTask('')
      d.showModal()
    }
    if (!open && d.open) d.close()
  }, [open, workflowId])

  const run = useMutation({
    mutationFn: () => api.runWorkflow(wf!.id, task),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['runs'] })
      onClose()
      navigate(`/runs/${r.id}`)
    },
  })

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      className="m-auto w-[min(640px,calc(100%-32px))] rounded-2xl border border-line bg-panel p-0 text-ink backdrop:bg-black/60 backdrop:backdrop-blur-sm"
    >
      <form
        className="flex flex-col gap-5 p-6"
        onSubmit={(e) => {
          e.preventDefault()
          if (wf) run.mutate()
        }}
      >
        <header className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-xl font-semibold">Delegate a task</h2>
            <p className="mt-1 text-sm text-muted">Pick a workflow and describe the outcome you want.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-muted hover:bg-panel-2 hover:text-ink" aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <label className="flex flex-col gap-2 text-sm">
          <span className="text-muted">Workflow</span>
          <select
            value={wf?.id ?? ''}
            onChange={(e) => setSelected(e.target.value)}
            className="min-h-11 rounded-xl border border-line bg-panel-2 px-3"
          >
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
        {wf && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
            {wf.mode === 'auto' ? (
              <span>The Supervisor plans the steps for this task.</span>
            ) : (
              wf.steps.map((s, i) => <AgentChip key={i} id={s.agent} agents={agents} />)
            )}
          </div>
        )}

        <label className="flex flex-col gap-2 text-sm">
          <span className="text-muted">Task</span>
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            rows={4}
            placeholder={wf?.defaultTask || 'Describe what the agents should do'}
            className="rounded-xl border border-line bg-panel-2 px-3 py-2.5 leading-relaxed placeholder:text-muted/70"
          />
          {wf?.defaultTask && <span className="text-xs text-muted">Leave empty to use the workflow's default task.</span>}
        </label>

        <ErrorNote error={run.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!wf || run.isPending || (!task.trim() && !wf.defaultTask)}>
            {run.isPending ? 'Starting…' : 'Start run'}
          </Button>
        </div>
      </form>
    </dialog>
  )
}
