import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Search, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { api } from '../api'
import { Button, Empty, ErrorNote, PageHeader, Panel } from '../components/ui'
import { bytes, timeAgo } from '../format'

export function Knowledge() {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.documents })
  const [query, setQuery] = useState('')
  const [notice, setNotice] = useState('')

  const uploadAll = useMutation({
    mutationFn: async (files: File[]) => {
      const done = []
      for (const f of files) done.push(await api.uploadDocument(f))
      return done
    },
    onSuccess: (done) => {
      setNotice(`Indexed ${done.map((d) => `${d.name} (${d.chunks} chunks)`).join(', ')}`)
      qc.invalidateQueries({ queryKey: ['documents'] })
    },
  })
  const remove = useMutation({ mutationFn: api.deleteDocument, onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }) })
  const search = useMutation({ mutationFn: (q: string) => api.search(q, 5) })

  return (
    <>
      <PageHeader
        title="Knowledge base"
        subtitle="Documents the Research Agent can search. Files are split into passages, embedded and indexed for semantic plus keyword search."
        action={
          <>
            <input
              ref={input}
              type="file"
              multiple
              accept=".pdf,.md,.markdown,.txt"
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? [])
                if (files.length) uploadAll.mutate(files)
                e.target.value = ''
              }}
            />
            <Button variant="primary" onClick={() => input.current?.click()} disabled={uploadAll.isPending}>
              <Upload size={16} /> {uploadAll.isPending ? 'Indexing…' : 'Upload documents'}
            </Button>
          </>
        }
      />
      <ErrorNote error={uploadAll.error ?? remove.error} />
      {notice && !uploadAll.error && <p className="mb-4 rounded-xl border border-good/30 bg-good/10 px-4 py-3 text-sm text-good">{notice}</p>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1fr]">
        <Panel title={`Documents (${docs.data?.length ?? 0})`} action={<span className="text-xs text-muted">PDF, Markdown or text, up to 15 MB</span>}>
          {docs.data?.length === 0 ? (
            <Empty title="No documents yet" action={<Button onClick={() => input.current?.click()}>Upload a document</Button>}>
              Upload policies, reports or contracts so agents can answer from them with citations.
            </Empty>
          ) : (
            <ul className="divide-y divide-line/70">
              {docs.data?.map((d) => (
                <li key={d.id} className="flex items-center gap-3 py-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-cyan/10 text-cyan">
                    <FileText size={17} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{d.name}</p>
                    <p className="text-xs text-muted">
                      {d.kind.toUpperCase()}, {bytes(d.size)}, {d.chunks} passages, added {timeAgo(d.createdAt)}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    className="px-2.5"
                    aria-label={`Delete ${d.name}`}
                    onClick={() => confirm(`Remove ${d.name} from the knowledge base?`) && remove.mutate(d.id)}
                  >
                    <Trash2 size={16} />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Test retrieval">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (query.trim()) search.mutate(query)
            }}
          >
            <label htmlFor="kb-query" className="sr-only">
              Search query
            </label>
            <input
              id="kb-query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. Who approves expenses over $5,000?"
              className="min-h-11 flex-1 rounded-xl border border-line bg-panel-2 px-3 placeholder:text-muted/70"
            />
            <Button type="submit" disabled={search.isPending}>
              <Search size={16} /> Search
            </Button>
          </form>
          <ErrorNote error={search.error} />
          <ol className="mt-4 flex flex-col gap-3">
            {search.data?.map((h, i) => (
              <li key={h.chunkId} className="rounded-xl border border-line bg-panel-2 p-4">
                <div className="mb-2 flex items-center justify-between gap-3 text-xs">
                  <span className="text-cyan">
                    {i + 1}. {h.document}
                  </span>
                  <span className="flex items-center gap-2 text-muted">
                    <span className="h-1.5 w-20 overflow-hidden rounded-full bg-bg">
                      <span className="block h-full rounded-full bg-violet" style={{ width: `${Math.min(100, h.score * 100)}%` }} />
                    </span>
                    <span className="tabular">{h.score.toFixed(3)}</span>
                  </span>
                </div>
                <p className="line-clamp-5 whitespace-pre-line text-sm text-ink/90">{h.text}</p>
              </li>
            ))}
            {search.data?.length === 0 && <p className="text-sm text-muted">No passages matched. Upload documents first.</p>}
          </ol>
          {!search.data && <p className="mt-4 text-sm text-muted">Check what the Research Agent will find before you run a workflow.</p>}
        </Panel>
      </div>
    </>
  )
}
