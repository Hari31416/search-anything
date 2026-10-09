import * as React from 'react'
import { RefreshCw, AlertCircle, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { UploadDropzone } from '@/components/library/UploadDropzone'
import { AssetTable } from '@/components/library/AssetTable'
import { AssetStatusSheet } from '@/components/library/AssetStatusSheet'
import { ReprocessDialog } from '@/components/library/ReprocessDialog'
import { SourcePreviewModal } from '@/components/search/SourcePreviewModal'
import { api, ApiError } from '@/lib/api'
import type { Asset } from '@/types/api'

export function LibraryTab() {
  const [assets, setAssets] = React.useState<Asset[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [showUpload, setShowUpload] = React.useState(false)

  // Modals state
  const [statusAsset, setStatusAsset] = React.useState<Asset | null>(null)
  const [reprocessAsset, setReprocessAsset] = React.useState<Asset | null>(null)
  const [previewAsset, setPreviewAsset] = React.useState<Asset | null>(null)

  const pollIntervalRef = React.useRef<number | null>(null)

  const loadAssets = React.useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const data = await api.getAssets(100, 0)
      setAssets(data)
      setError(null)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.details)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to fetch library assets')
      }
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    loadAssets()
  }, [loadAssets])

  // Polling management: poll while any asset is pending, queued, or processing
  React.useEffect(() => {
    const hasPendingWork = assets.some(
      (a) =>
        a.state === 'pending' ||
        a.state === 'queued' ||
        a.state === 'processing'
    )

    if (hasPendingWork) {
      if (pollIntervalRef.current === null) {
        pollIntervalRef.current = window.setInterval(() => {
          loadAssets(true)
        }, 3000)
      }
    } else {
      if (pollIntervalRef.current !== null) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }

    return () => {
      if (pollIntervalRef.current !== null) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
  }, [assets, loadAssets])

  const handleUploadSuccess = () => {
    loadAssets(true)
    setShowUpload(false)
  }

  const handleRetry = async (asset: Asset) => {
    try {
      await api.retryAsset(asset.id)
      loadAssets(true)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Retry failed')
    }
  }

  const handleCancel = async (asset: Asset) => {
    try {
      await api.cancelAsset(asset.id)
      loadAssets(true)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Cancel failed')
    }
  }

  const handleDelete = async (asset: Asset) => {
    try {
      await api.deleteAsset(asset.id)
      loadAssets(true)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground">
            Asset Library
          </h2>
          <p className="text-xs text-muted-foreground">
            Manage indexed documents, images, audio, and video files in this
            workspace.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadAssets(false)}
            disabled={loading}
            className="gap-1.5"
          >
            <RefreshCw
              className={`size-3.5 ${loading ? 'animate-spin' : ''}`}
            />
            Refresh
          </Button>

          <Button
            size="sm"
            onClick={() => setShowUpload((prev) => !prev)}
            className="gap-1.5"
          >
            <Plus className="size-3.5" />
            {showUpload ? 'Hide Uploader' : 'Upload Asset'}
          </Button>
        </div>
      </div>

      {showUpload && (
        <div className="animate-in rounded-xl border border-border bg-card p-4 shadow-xs duration-200 fade-in-50">
          <UploadDropzone onUploadSuccess={handleUploadSuccess} />
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-xs text-destructive">
          <AlertCircle className="size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <AssetTable
        assets={assets}
        loading={loading}
        onPreview={(asset) => setPreviewAsset(asset)}
        onOpenStatus={(asset) => setStatusAsset(asset)}
        onReprocess={(asset) => setReprocessAsset(asset)}
        onRetry={handleRetry}
        onCancel={handleCancel}
        onDelete={handleDelete}
      />

      <AssetStatusSheet
        asset={statusAsset}
        open={!!statusAsset}
        onOpenChange={(open) => !open && setStatusAsset(null)}
        onAssetUpdated={() => loadAssets(true)}
      />

      <ReprocessDialog
        asset={reprocessAsset}
        open={!!reprocessAsset}
        onOpenChange={(open) => !open && setReprocessAsset(null)}
        onSuccess={() => loadAssets(true)}
      />

      <SourcePreviewModal
        asset={previewAsset}
        open={!!previewAsset}
        onOpenChange={(open) => !open && setPreviewAsset(null)}
      />
    </div>
  )
}
