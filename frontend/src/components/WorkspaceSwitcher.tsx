import * as React from 'react'
import { FolderOpen, Plus, Pencil, Loader2 } from 'lucide-react'
import { useWorkspace } from '@/lib/workspaces'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export function WorkspaceSwitcher() {
  const { workspaces, workspace, loading, select, create, rename } =
    useWorkspace()
  const [mode, setMode] = React.useState<'create' | 'rename' | null>(null)
  const [name, setName] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const open = (next: 'create' | 'rename') => {
    setMode(next)
    setName(next === 'rename' ? (workspace?.name ?? '') : '')
    setError(null)
  }
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!name.trim() || saving) return
    setSaving(true)
    setError(null)
    try {
      if (mode === 'create') await create(name.trim())
      else await rename(name.trim())
      setMode(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save workspace')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <FolderOpen
        className="hidden size-4 shrink-0 text-muted-foreground sm:block"
        aria-hidden="true"
      />
      <select
        aria-label="Workspace"
        value={workspace?.id ?? ''}
        disabled={loading || !workspace}
        onChange={(event) => select(event.target.value)}
        className="h-8 max-w-32 rounded-lg border border-border bg-background px-2 text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring sm:max-w-44"
      >
        {!workspace && (
          <option value="">{loading ? 'Loading...' : 'No workspace'}</option>
        )}
        {workspaces.map((row) => (
          <option key={row.id} value={row.id}>
            {row.name}
          </option>
        ))}
      </select>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Create workspace"
        title="Create workspace"
        onClick={() => open('create')}
        disabled={loading || !workspace}
      >
        <Plus className="size-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Rename workspace"
        title="Rename workspace"
        onClick={() => open('rename')}
        disabled={loading || !workspace}
      >
        <Pencil className="size-3.5" />
      </Button>
      <Dialog
        open={mode !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen && !saving) setMode(null)
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <form onSubmit={submit} className="space-y-5">
            <DialogHeader>
              <DialogTitle>
                {mode === 'create' ? 'New workspace' : 'Rename workspace'}
              </DialogTitle>
              <DialogDescription>
                {mode === 'create'
                  ? 'Keep a separate library, search results, and ingestion profiles for this collection.'
                  : 'Give this collection a name you recognize.'}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-2">
              <label htmlFor="workspace-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="workspace-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Apollo 11"
                maxLength={160}
                required
                disabled={saving}
                autoFocus
              />
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setMode(null)}
                disabled={saving}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saving || !name.trim()}>
                {saving && <Loader2 className="size-4 animate-spin" />}
                {mode === 'create' ? 'Create workspace' : 'Save name'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
