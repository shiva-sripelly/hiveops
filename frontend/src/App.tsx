import {
  Bot,
  CheckCircle2,
  Database,
  FileText,
  FlaskConical,
  Gauge,
  Hexagon,
  Menu,
  Play,
  Settings as SettingsIcon,
  Workflow as WorkflowIcon,
  X,
} from 'lucide-react'
import { createContext, useContext, useState, type ReactNode } from 'react'
import { NavLink, Route, Routes } from 'react-router'
import { RunLauncher } from './components/RunLauncher'
import { Button } from './components/ui'
import { useHealth, usePendingApprovals } from './hooks'
import { Agents } from './pages/Agents'
import { Approvals } from './pages/Approvals'
import { DataSources } from './pages/DataSources'
import { Evals } from './pages/Evals'
import { Knowledge } from './pages/Knowledge'
import { Overview } from './pages/Overview'
import { RunDetailPage } from './pages/RunDetail'
import { Runs } from './pages/Runs'
import { Settings } from './pages/Settings'
import { WorkflowBuilder } from './pages/WorkflowBuilder'
import { Workflows } from './pages/Workflows'

const LauncherContext = createContext<(workflowId?: string) => void>(() => {})
export const useLauncher = () => useContext(LauncherContext)

const NAV = [
  { to: '/', label: 'Overview', icon: Gauge, end: true },
  { to: '/workflows', label: 'Workflows', icon: WorkflowIcon },
  { to: '/runs', label: 'Runs', icon: Play },
  { to: '/approvals', label: 'Approvals', icon: CheckCircle2, badge: true },
  { to: '/knowledge', label: 'Knowledge base', icon: FileText },
  { to: '/data', label: 'Data & integrations', icon: Database },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/evals', label: 'Evaluations', icon: FlaskConical },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
]

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { data: pending = [] } = usePendingApprovals()
  const { data: health } = useHealth()
  return (
    <nav className="flex h-full flex-col gap-1 p-4" aria-label="Main">
      <div className="mb-6 flex items-center gap-2.5 px-2 pt-2">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet to-blue shadow-[0_0_24px_rgba(139,108,255,0.5)]">
          <Hexagon size={18} className="text-white" />
        </span>
        <span className="font-display text-lg font-semibold">HiveOps</span>
      </div>
      {NAV.map(({ to, label, icon: Icon, end, badge }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex min-h-11 items-center gap-3 rounded-xl px-3 text-[15px] transition-colors ${
              isActive ? 'bg-panel-2 text-ink shadow-[inset_0_0_0_1px_#262b52]' : 'text-muted hover:bg-panel hover:text-ink'
            }`
          }
        >
          <Icon size={18} />
          <span className="flex-1">{label}</span>
          {badge && pending.length > 0 && (
            <span className="tabular rounded-full bg-warn/20 px-2 py-0.5 text-xs font-semibold text-warn">{pending.length}</span>
          )}
        </NavLink>
      ))}
      <div className="mt-auto rounded-2xl border border-line bg-panel p-4 text-sm">
        <p className="flex items-center gap-2 font-medium">
          <span className={`h-2 w-2 rounded-full ${health?.databaseOk ? 'bg-good' : 'bg-bad'}`} />
          Platform status
        </p>
        <p className="mt-1 text-muted">
          {health ? (health.databaseOk ? 'All systems operational' : 'Database unreachable') : 'Checking…'}
        </p>
        {health && (
          <p className="mt-2 text-xs text-muted">
            {health.llm.simulated ? 'Simulated LLM (offline mode)' : `${health.llm.provider} · ${health.llm.model}`}
          </p>
        )}
      </div>
    </nav>
  )
}

function Shell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [launcher, setLauncher] = useState<{ open: boolean; workflowId?: string }>({ open: false })
  const { data: health } = useHealth()

  return (
    <LauncherContext.Provider value={(workflowId) => setLauncher({ open: true, workflowId })}>
      <div className="flex min-h-full">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-line bg-[#0c0f22] lg:block">
          <Sidebar />
        </aside>
        {menuOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <button className="absolute inset-0 bg-black/60" onClick={() => setMenuOpen(false)} aria-label="Close menu" />
            <aside className="relative h-full w-72 border-r border-line bg-[#0c0f22]">
              <Sidebar onNavigate={() => setMenuOpen(false)} />
            </aside>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-bg/85 px-4 py-3 backdrop-blur md:px-8">
            <button className="rounded-lg p-2 text-muted hover:bg-panel lg:hidden" onClick={() => setMenuOpen((o) => !o)} aria-label="Open menu">
              {menuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            <div className="flex-1" />
            {health?.llm.simulated && (
              <span className="hidden rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1 text-xs text-cyan sm:inline">
                Simulated LLM: add an API key for real models
              </span>
            )}
            <Button variant="primary" onClick={() => setLauncher({ open: true })}>
              <Play size={16} /> New run
            </Button>
          </div>
          <main className="mx-auto w-full max-w-[1440px] px-4 py-6 md:px-8 md:py-8">{children}</main>
        </div>
      </div>
      <RunLauncher open={launcher.open} workflowId={launcher.workflowId} onClose={() => setLauncher({ open: false })} />
    </LauncherContext.Provider>
  )
}

export function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/workflows" element={<Workflows />} />
        <Route path="/workflows/new" element={<WorkflowBuilder />} />
        <Route path="/workflows/:id" element={<WorkflowBuilder />} />
        <Route path="/runs" element={<Runs />} />
        <Route path="/runs/:id" element={<RunDetailPage />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/data" element={<DataSources />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/evals" element={<Evals />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<p className="text-muted">Page not found.</p>} />
      </Routes>
    </Shell>
  )
}
