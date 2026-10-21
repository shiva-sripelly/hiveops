import { useQuery } from '@tanstack/react-query'
import { api, type Agent } from './api'

export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30_000 })
export const useDashboard = () => useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard, refetchInterval: 5_000 })
export const useWorkflows = () => useQuery({ queryKey: ['workflows'], queryFn: api.workflows })
export const useRuns = (status?: string) =>
  useQuery({ queryKey: ['runs', status ?? 'all'], queryFn: () => api.runs(status), refetchInterval: 3_000 })
export const usePendingApprovals = () =>
  useQuery({ queryKey: ['approvals', 'pending'], queryFn: () => api.approvals('pending'), refetchInterval: 4_000 })

export function useAgents() {
  return useQuery({ queryKey: ['agents'], queryFn: api.agents, staleTime: Infinity })
}

/** id → agent, for colours and names. */
export function useAgentMap(): Record<string, Agent> {
  const { data } = useAgents()
  return Object.fromEntries((data ?? []).map((a) => [a.id, a]))
}
