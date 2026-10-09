import * as React from 'react'
import { Plus, RefreshCw, AlertCircle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ProfileCard } from '@/components/profiles/ProfileCard'
import { ProfileEditorModal } from '@/components/profiles/ProfileEditorModal'
import { ApiError } from '@/lib/api'
import { useWorkspaceApi } from '@/lib/workspaces'
import type { Profile } from '@/types/api'

export function ProfilesTab() {
  const api = useWorkspaceApi()
  const [profiles, setProfiles] = React.useState<Profile[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  const [editorOpen, setEditorOpen] = React.useState(false)
  const [editingProfile, setEditingProfile] = React.useState<Profile | null>(
    null
  )

  const loadProfiles = React.useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getProfiles()
      setProfiles(data)
      setError(null)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.details)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to fetch ingestion profiles')
      }
    } finally {
      setLoading(false)
    }
  }, [api])

  React.useEffect(() => {
    loadProfiles()
  }, [loadProfiles])

  const handleCreateNew = () => {
    setEditingProfile(null)
    setEditorOpen(true)
  }

  const handleEdit = (profile: Profile) => {
    setEditingProfile(profile)
    setEditorOpen(true)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground">
            Ingestion Profiles
          </h2>
          <p className="text-xs text-muted-foreground">
            Configure segmentation limits, audio/video windowing, sampling FPS,
            and OCR settings.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={loadProfiles}
            disabled={loading}
            className="gap-1.5"
          >
            <RefreshCw
              className={`size-3.5 ${loading ? 'animate-spin' : ''}`}
            />
            Refresh
          </Button>

          <Button size="sm" onClick={handleCreateNew} className="gap-1.5">
            <Plus className="size-3.5" />
            New Profile
          </Button>
        </div>
      </div>

      <div className="flex gap-2.5 rounded-xl border border-border/80 bg-muted/20 p-4 text-xs text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0 text-primary" />
        <div className="space-y-1">
          <p className="font-semibold text-foreground">
            Saved Profile Revisions vs. Asset Snapshot
          </p>
          <p>
            Uploads always index content using the latest revision of the{' '}
            <code>automatic</code> profile. Saving a new profile revision does
            not alter already-indexed assets; to apply a new configuration,
            navigate to the Library and click <strong>Reprocess</strong> on
            target assets.
          </p>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-xs text-destructive">
          <AlertCircle className="size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading && profiles.length === 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {[1, 2].map((n) => (
            <div
              key={n}
              className="h-48 animate-pulse rounded-xl border border-border bg-card p-5"
            />
          ))}
        </div>
      ) : profiles.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-12 text-center text-xs text-muted-foreground">
          No profiles found. Click &quot;New Profile&quot; to configure your
          first ingestion profile.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {profiles.map((profile) => (
            <ProfileCard
              key={profile.id}
              profile={profile}
              onEdit={handleEdit}
            />
          ))}
        </div>
      )}

      <ProfileEditorModal
        initialProfile={editingProfile}
        open={editorOpen}
        onOpenChange={setEditorOpen}
        onSuccess={loadProfiles}
      />
    </div>
  )
}
