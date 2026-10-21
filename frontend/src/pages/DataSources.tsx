import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Hash, Mail, MessageSquare, Table2, Trash2, Type, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { api } from '../api'
import { Button, Empty, ErrorNote, PageHeader, Panel } from '../components/ui'
import { timeAgo } from '../format'

export function DataSources() {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: api.datasets })
  const outbox = useQuery({ queryKey: ['outbox'], queryFn: api.outbox, refetchInterval: 5000 })
  const [selected, setSelected] = useState<string | null>(null)
  const current = selected ?? datasets.data?.[0]?.id ?? null
  const detail = useQuery({ queryKey: ['dataset', current], queryFn: () => api.dataset(current!), enabled: !!current })

  const upload = useMutation({
    mutationFn: api.uploadDataset,
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ['datasets'] })
      setSelected(d.id)
    },
  })
  const remove = useMutation({
    mutationFn: api.deleteDataset,
    onSuccess: () => {
      setSelected(null)
      qc.invalidateQueries({ queryKey: ['datasets'] })
    },
  })

  return (
    <>
      <PageHeader
        title="Data and integrations"
        subtitle="Tables the Data Analyst can query, and the channels the Comms Agent can deliver to after approval."
        action={
          <>
            <input
              ref={input}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) upload.mutate(f)
                e.target.value = ''
              }}
            />
            <Button variant="primary" onClick={() => input.current?.click()} disabled={upload.isPending}>
              <Upload size={16} /> {upload.isPending ? 'Importing…' : 'Import CSV'}
            </Button>
          </>
        }
      />
      <ErrorNote error={upload.error ?? remove.error} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[320px_1fr]">
        <Panel title="Datasets">
          {datasets.data?.length === 0 && <Empty title="No datasets">Import a CSV and the Data Analyst can aggregate, filter and compare it.</Empty>}
          <ul className="flex flex-col gap-2">
            {datasets.data?.map((d) => (
              <li key={d.id}>
                <button
                  onClick={() => setSelected(d.id)}
                  className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left ${current === d.id ? 'border-violet bg-violet/10' : 'border-line bg-panel-2 hover:border-violet/50'}`}
                >
                  <Table2 size={18} className="text-good" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{d.name}</span>
                    <span className="text-xs text-muted">
                      {d.rows} rows, {d.columns.length} columns, {timeAgo(d.createdAt)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title={detail.data ? detail.data.name : 'Preview'}
          action={
            detail.data && (
              <Button variant="ghost" className="px-2.5" onClick={() => confirm(`Delete ${detail.data.name}?`) && remove.mutate(detail.data.id)}>
                <Trash2 size={16} /> Delete
              </Button>
            )
          }
        >
          {detail.data ? (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                {detail.data.columns.map((c) => (
                  <span key={c.name} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel-2 px-2.5 py-1 text-xs">
                    {c.type === 'number' ? <Hash size={12} className="text-good" /> : <Type size={12} className="text-cyan" />}
                    {c.name}
                  </span>
                ))}
              </div>
              <div className="max-h-[420px] overflow-auto rounded-xl border border-line">
                <table className="tabular w-full text-sm">
                  <thead className="sticky top-0 bg-panel-2">
                    <tr>
                      {detail.data.columns.map((c) => (
                        <th key={c.name} className={`px-3 py-2 font-medium text-muted ${c.type === 'number' ? 'text-right' : 'text-left'}`}>
                          {c.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {detail.data.preview.map((row, i) => (
                      <tr key={i} className="border-t border-line/60">
                        {detail.data.columns.map((c) => (
                          <td key={c.name} className={`px-3 py-1.5 ${c.type === 'number' ? 'text-right' : ''}`}>
                            {typeof row[c.name] === 'number' ? (row[c.name] as number).toLocaleString('en-US') : String(row[c.name] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-muted">
                Showing {detail.data.preview.length} of {detail.data.rows} rows
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">Select a dataset to preview it.</p>
          )}
        </Panel>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[320px_1fr]">
        <Panel title="Integrations">
          <ul className="flex flex-col gap-3 text-sm">
            <li className="flex gap-3 rounded-xl border border-line bg-panel-2 p-3">
              <Mail size={18} className="mt-0.5 text-violet" />
              <span>
                <span className="block font-medium">Email</span>
                <span className="text-muted">Delivered to the outbox below. Connect an SMTP relay to send externally.</span>
              </span>
            </li>
            <li className="flex gap-3 rounded-xl border border-line bg-panel-2 p-3">
              <MessageSquare size={18} className="mt-0.5 text-violet" />
              <span>
                <span className="block font-medium">Slack</span>
                <span className="text-muted">Set SLACK_WEBHOOK_URL on the server to post to a real workspace.</span>
              </span>
            </li>
          </ul>
        </Panel>
        <Panel title="Delivery log">
          {outbox.data?.length === 0 && <Empty title="Nothing delivered yet">Approved emails and Slack posts are recorded here.</Empty>}
          <ul className="divide-y divide-line/70">
            {outbox.data?.map((o) => (
              <li key={o.id} className="py-3">
                <details>
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1">
                    {o.channel === 'slack' ? <MessageSquare size={16} className="text-violet" /> : <Mail size={16} className="text-violet" />}
                    <span className="font-medium">{o.subject || `Message to ${o.recipient}`}</span>
                    <span className="text-sm text-muted">to {o.recipient}</span>
                    <span className={`ml-auto text-xs ${o.delivered ? 'text-good' : 'text-bad'}`}>{o.delivered ? 'Delivered' : 'Failed'}</span>
                    <span className="text-xs text-muted">{timeAgo(o.createdAt)}</span>
                  </summary>
                  <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-bg p-3 text-xs text-muted">{o.body}</pre>
                </details>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </>
  )
}
