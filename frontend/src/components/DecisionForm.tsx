import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { api, type Approval } from '../api'
import { Markdown } from './Markdown'
import { Button, ErrorNote } from './ui'

/** What the agent wants to do, and the approve / reject controls. */
export function ApprovalBody({ approval }: { approval: Approval }) {
  const { payload } = approval
  if (approval.kind === 'step_output') {
    return (
      <div className="max-h-80 overflow-y-auto rounded-xl border border-line bg-bg p-4">
        <Markdown text={payload.output ?? ''} />
      </div>
    )
  }
  const args = payload.args ?? {}
  return (
    <div className="rounded-xl border border-line bg-bg p-4 text-sm">
      <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-1.5">
        <dt className="text-muted">Action</dt>
        <dd className="font-medium">{payload.tool === 'post_slack_message' ? 'Post to Slack' : 'Send email'}</dd>
        <dt className="text-muted">{args.channel ? 'Channel' : 'To'}</dt>
        <dd>{args.channel ?? args.to}</dd>
        {args.subject && (
          <>
            <dt className="text-muted">Subject</dt>
            <dd>{args.subject}</dd>
          </>
        )}
      </dl>
      <div className="mt-3 max-h-64 overflow-y-auto border-t border-line pt-3">
        <Markdown text={args.body ?? args.text ?? ''} />
      </div>
    </div>
  )
}

export function DecisionForm({ approval }: { approval: Approval }) {
  const [comment, setComment] = useState('')
  const qc = useQueryClient()
  const decide = useMutation({
    mutationFn: (approved: boolean) => api.decide(approval.id, approved, comment),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['approvals'] })
      qc.invalidateQueries({ queryKey: ['run', approval.runId] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  const verb = approval.kind === 'tool_action' ? (approval.payload.tool === 'post_slack_message' ? 'post' : 'send') : 'continue'
  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="text-muted">Comment for the audit log (optional)</span>
        <input
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          className="min-h-10 rounded-xl border border-line bg-panel-2 px-3"
          placeholder="Why are you approving or rejecting this?"
        />
      </label>
      <ErrorNote error={decide.error} />
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled={decide.isPending} onClick={() => decide.mutate(true)}>
          <Check size={16} /> Approve and {verb}
        </Button>
        <Button variant="danger" disabled={decide.isPending} onClick={() => decide.mutate(false)}>
          <X size={16} /> Reject
        </Button>
      </div>
    </div>
  )
}
