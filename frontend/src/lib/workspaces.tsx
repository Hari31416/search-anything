import * as React from 'react'
import { createApi, workspaceApi } from '@/lib/api'
import type { Workspace } from '@/types/api'

const storageKey = 'search-anything-workspace'

interface WorkspaceContextValue {
  workspaces: Workspace[]
  workspace: Workspace | null
  loading: boolean
  error: string | null
  reload: () => Promise<void>
  select: (id: string) => void
  create: (name: string) => Promise<void>
  rename: (name: string) => Promise<void>
  api: ReturnType<typeof createApi>
}

const WorkspaceContext = React.createContext<WorkspaceContextValue | null>(null)

function savedWorkspace(): string | null {
  try {
    return localStorage.getItem(storageKey)
  } catch {
    return null
  }
}

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [workspaces, setWorkspaces] = React.useState<Workspace[]>([])
  const [selectedId, setSelectedId] = React.useState<string | null>(
    savedWorkspace
  )
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const mounted = React.useRef(false)

  const reload = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const rows = await workspaceApi.list()
      if (!mounted.current) return
      setWorkspaces(rows)
      setSelectedId((id) =>
        rows.some((row) => row.id === id) ? id : (rows[0]?.id ?? null)
      )
    } catch (err) {
      if (mounted.current)
        setError(
          err instanceof Error ? err.message : 'Could not load workspaces'
        )
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    mounted.current = true
    void reload()
    return () => {
      mounted.current = false
    }
  }, [reload])

  React.useEffect(() => {
    if (!selectedId) return
    try {
      localStorage.setItem(storageKey, selectedId)
    } catch {
      // Workspace switching still works when browser persistence is disabled.
    }
  }, [selectedId])

  const workspace = workspaces.find((row) => row.id === selectedId) ?? null
  const api = React.useMemo(
    () => createApi(selectedId ?? undefined),
    [selectedId]
  )
  const select = (id: string) => {
    if (workspaces.some((row) => row.id === id)) setSelectedId(id)
  }
  const create = async (name: string) => {
    const row = await workspaceApi.create(name)
    setWorkspaces((rows) => [...rows, row])
    setSelectedId(row.id)
  }
  const rename = async (name: string) => {
    if (!workspace) return
    const row = await workspaceApi.rename(workspace.id, name)
    setWorkspaces((rows) =>
      rows.map((current) => (current.id === row.id ? row : current))
    )
  }

  return (
    <WorkspaceContext.Provider
      value={{
        workspaces,
        workspace,
        loading,
        error,
        reload,
        select,
        create,
        rename,
        api,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  const context = React.useContext(WorkspaceContext)
  if (!context) throw new Error('WorkspaceProvider is required')
  return context
}

export function useWorkspaceApi() {
  return useWorkspace().api
}
