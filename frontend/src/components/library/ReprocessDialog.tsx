import * as React from 'react'
import { RotateCw, Loader2, Info } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'
import type { Asset, Profile } from '@/types/api'

interface ReprocessDialogProps {
  asset: Asset | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: () => void
}

export function ReprocessDialog({
  asset,
  open,
  onOpenChange,
  onSuccess,
}: ReprocessDialogProps) {
  const [profiles, setProfiles] = React.useState<Profile[]>([])
  const [selectedProfile, setSelectedProfile] =
    React.useState<string>('automatic')
  const [loadingProfiles, setLoadingProfiles] = React.useState(false)
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (open) {
      setLoadingProfiles(true)
      setError(null)
      api
        .getProfiles()
        .then((data) => {
          setProfiles(data)
          if (
            data.length > 0 &&
            !data.some((p) => p.name === selectedProfile)
          ) {
            setSelectedProfile(data[0].name)
          }
        })
        .catch(() => {
          // Keep automatic as fallback
        })
        .finally(() => {
          setLoadingProfiles(false)
        })
    }
  }, [open, selectedProfile])

  const handleReprocess = async () => {
    if (!asset) return
    setSubmitting(true)
    setError(null)

    try {
      await api.reprocessAsset(asset.id, selectedProfile)
      onSuccess()
      onOpenChange(false)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.details)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Reprocessing failed to start')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (!asset) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RotateCw className="size-4 text-primary" />
            Reprocess Asset
          </DialogTitle>
          <DialogDescription>
            Choose an ingestion profile revision to reindex &quot;
            {asset.filename}&quot;.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="rounded-md border border-border/80 bg-muted/40 p-3 text-xs text-muted-foreground">
            <div className="flex gap-2">
              <Info className="size-4 shrink-0 text-primary" />
              <span>
                Reprocessing creates a new processing generation. The currently
                active generation remains searchable until indexing of the new
                generation completes successfully.
              </span>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-medium text-foreground">
              Ingestion Profile
            </label>
            {loadingProfiles ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Loading available
                profiles...
              </div>
            ) : (
              <div className="grid gap-2">
                <select
                  value={selectedProfile}
                  onChange={(e) => setSelectedProfile(e.target.value)}
                  disabled={submitting}
                  className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-xs shadow-xs focus:ring-1 focus:ring-ring focus:outline-none"
                >
                  <option value="automatic">
                    automatic (default settings)
                  </option>
                  {profiles
                    .filter((p) => p.name !== 'automatic')
                    .map((p) => (
                      <option key={p.id} value={p.name}>
                        {p.name} (rev {p.revision})
                      </option>
                    ))}
                </select>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-md border border-destructive/20 bg-destructive/10 p-2.5 text-xs text-destructive">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleReprocess}
            disabled={submitting || !selectedProfile}
            className="gap-1.5"
          >
            {submitting ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                Queuing...
              </>
            ) : (
              <>
                <RotateCw className="size-3.5" />
                Start Reprocessing
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
