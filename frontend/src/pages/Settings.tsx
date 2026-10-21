import { PageHeader, Panel } from '../components/ui'
import { useHealth } from '../hooks'

export function Settings() {
  const { data: h } = useHealth()
  const rows: [string, string, boolean | null][] = h
    ? [
        ['Language model', h.llm.simulated ? 'Simulated (offline, deterministic)' : `${h.llm.provider}: ${h.llm.model}`, !h.llm.simulated || null],
        ['Database', h.database === 'postgresql' ? 'PostgreSQL' : 'SQLite (local development)', h.databaseOk],
        ['Vector search', h.vectorStore, true],
        ['Job queue and live events', h.redis == null ? 'In-process (set REDIS_URL to scale out)' : h.redis ? 'Redis' : 'Redis unreachable', h.redis ?? null],
        ['Workers in this process', String(h.workers), true],
        ['Version', h.version, null],
      ]
    : []

  return (
    <>
      <PageHeader title="Settings" subtitle="Configuration is read from environment variables when the server starts." />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Platform">
          <dl className="divide-y divide-line/70">
            {rows.map(([k, v, ok]) => (
              <div key={k} className="flex items-center justify-between gap-4 py-3 text-sm">
                <dt className="text-muted">{k}</dt>
                <dd className="flex items-center gap-2 text-right">
                  {ok !== null && <span className={`h-2 w-2 rounded-full ${ok ? 'bg-good' : 'bg-bad'}`} />}
                  {v}
                </dd>
              </div>
            ))}
          </dl>
        </Panel>
        <Panel title="Use a real model">
          <p className="text-sm text-muted">
            HiveOps runs with a deterministic simulated LLM until you add a key. Set one of these on the server and restart it:
          </p>
          <pre className="mt-3 overflow-x-auto rounded-xl bg-bg p-4 text-xs leading-relaxed text-ink/90">
            {`# Claude
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-5-5

# OpenAI, or any OpenAI-compatible API (Ollama, Groq, vLLM…)
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1`}
          </pre>
          <p className="mt-3 text-sm text-muted">Optional: SLACK_WEBHOOK_URL posts approved Slack messages to a real channel.</p>
        </Panel>
      </div>
    </>
  )
}
