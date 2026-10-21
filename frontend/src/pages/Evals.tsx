import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, FlaskConical, XCircle } from 'lucide-react'
import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type EvalMetrics, type EvalRun } from '../api'
import { Button, Empty, ErrorNote, PageHeader, Panel } from '../components/ui'
import { duration, money, ratio, timeAgo } from '../format'

export function Evals() {
  const qc = useQueryClient()
  const suites = useQuery({ queryKey: ['evalSuites'], queryFn: api.evalSuites })
  const runs = useQuery({
    queryKey: ['evalRuns'],
    queryFn: api.evalRuns,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running') ? 1000 : false),
  })
  const start = useMutation({ mutationFn: api.runEval, onSuccess: () => qc.invalidateQueries({ queryKey: ['evalRuns'] }) })
  const [openCase, setOpenCase] = useState<number | null>(null)

  const latest = runs.data?.find((r) => r.status !== 'running')
  const running = runs.data?.some((r) => r.status === 'running')
  const m = latest?.metrics as EvalMetrics | undefined
  const history = [...(runs.data ?? [])]
    .filter((r) => r.status === 'completed')
    .reverse()
    .map((r, i) => ({
      n: `#${i + 1}`,
      pass: Math.round(((r.metrics as EvalMetrics).passRate ?? 0) * 100),
      grounded: Math.round(((r.metrics as EvalMetrics).avgGroundedness ?? 0) * 100),
      hit: Math.round(((r.metrics as EvalMetrics).retrievalHitRate ?? 0) * 100),
    }))

  return (
    <>
      <PageHeader
        title="Evaluations"
        subtitle="Test retrieval and answer quality against known questions before you trust the agents with real work."
      />
      <ErrorNote error={start.error} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[360px_1fr]">
        <div className="flex flex-col gap-4">
          {suites.data?.map((s) => (
            <Panel key={s.id} title={s.name}>
              <p className="text-sm text-muted">{s.description}</p>
              <p className="mt-2 text-sm">{s.cases.length} test questions with expected facts and source documents.</p>
              <Button variant="primary" className="mt-4 w-full" disabled={running || start.isPending} onClick={() => start.mutate(s.id)}>
                <FlaskConical size={16} /> {running ? 'Evaluating…' : 'Run evaluation'}
              </Button>
            </Panel>
          ))}
          <Panel title="How cases are scored">
            <dl className="flex flex-col gap-3 text-sm">
              {[
                ['Retrieval hit', 'The expected source document is among the top 4 passages.'],
                ['Answer recall', 'Share of the expected key facts that appear in the answer.'],
                ['Groundedness', 'Share of answer sentences supported by the retrieved passages.'],
                ['Pass', 'Retrieval hit, recall of at least 60% and groundedness of at least 60%.'],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt className="font-medium">{k}</dt>
                  <dd className="text-muted">{v}</dd>
                </div>
              ))}
            </dl>
          </Panel>
        </div>

        <div className="flex flex-col gap-4">
          {!latest && !running && <Empty title="No evaluations yet">Run the suite to measure your knowledge base and model.</Empty>}
          {m && latest && (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {[
                  ['Pass rate', ratio(m.passRate)],
                  ['Retrieval hit rate', ratio(m.retrievalHitRate)],
                  ['Answer recall', ratio(m.avgRecall)],
                  ['Groundedness', ratio(m.avgGroundedness)],
                ].map(([k, v]) => (
                  <div key={k} className="panel p-4">
                    <p className="text-sm text-muted">{k}</p>
                    <p className="tabular font-display text-3xl font-semibold">{v}</p>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted">
                Latest run {timeAgo(latest.createdAt)} on {latest.model}: {m.cases} cases, average {duration(m.avgLatencyMs)} per answer, {money(m.totalCost)} total.
              </p>
            </>
          )}
          {history.length > 1 && (
            <Panel title="Quality over time">
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={history} margin={{ left: -20, right: 8, top: 4 }}>
                    <CartesianGrid stroke="#262b52" strokeDasharray="3 6" vertical={false} />
                    <XAxis dataKey="n" tick={{ fill: '#9ba1c9', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} tick={{ fill: '#9ba1c9', fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: '#171b38', border: '1px solid #262b52', borderRadius: 12, color: '#e8eaff' }} />
                    <Line dataKey="pass" name="Pass rate" stroke="#8b6cff" strokeWidth={2} dot />
                    <Line dataKey="hit" name="Retrieval hit" stroke="#2dd4e6" strokeWidth={2} dot />
                    <Line dataKey="grounded" name="Groundedness" stroke="#34d399" strokeWidth={2} dot />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          )}
          {latest && <CaseTable run={latest} openCase={openCase} setOpenCase={setOpenCase} />}
        </div>
      </div>
    </>
  )
}

function CaseTable({ run, openCase, setOpenCase }: { run: EvalRun; openCase: number | null; setOpenCase: (n: number | null) => void }) {
  return (
    <Panel title="Results by question">
      <ul className="divide-y divide-line/70">
        {run.results.map((r, i) => (
          <li key={i} className="py-3">
            <button className="flex w-full items-start gap-3 text-left" onClick={() => setOpenCase(openCase === i ? null : i)} aria-expanded={openCase === i}>
              {r.passed ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-good" /> : <XCircle size={18} className="mt-0.5 shrink-0 text-bad" />}
              <span className="flex-1">
                <span className="block font-medium">{r.question}</span>
                <span className="tabular mt-1 flex flex-wrap gap-x-4 text-xs text-muted">
                  <span className={r.retrievalHit ? 'text-good' : 'text-bad'}>{r.retrievalHit ? 'Source found' : 'Source missed'}</span>
                  <span>Recall {ratio(r.recall)}</span>
                  <span>Groundedness {ratio(r.groundedness)}</span>
                  <span>{duration(r.latencyMs)}</span>
                </span>
              </span>
            </button>
            {openCase === i && (
              <div className="ml-8 mt-3 rounded-xl bg-bg p-3 text-sm">
                {r.error ? <p className="text-bad">{r.error}</p> : <p className="whitespace-pre-wrap text-ink/90">{r.answer}</p>}
                <p className="mt-2 text-xs text-muted">
                  Expected source: {r.expectedSource}. Retrieved: {r.retrieved.join(', ')}
                </p>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  )
}
