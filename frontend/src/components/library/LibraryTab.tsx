import * as React from 'react'
import {
  RefreshCw,
  AlertCircle,
  Plus,
  LayoutGrid,
  List,
  Search,
  Image as ImageIcon,
  Video,
  Music,
  FileText,
  Layers,
  HardDrive,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { UploadDropzone } from '@/components/library/UploadDropzone'
import { AssetTable } from '@/components/library/AssetTable'
import { AssetGrid } from '@/components/library/AssetGrid'
import { AssetStatusSheet } from '@/components/library/AssetStatusSheet'
import { ReprocessDialog } from '@/components/library/ReprocessDialog'
import { SourcePreviewModal } from '@/components/search/SourcePreviewModal'
import { api, ApiError } from '@/lib/api'
import { formatBytes, getMimeCategory } from '@/lib/formatters'
import type { Asset } from '@/types/api'

type CategoryFilter = 'all' | 'image' | 'video' | 'audio' | 'document'

export function LibraryTab() {
  const [assets, setAssets] = React.useState<Asset[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [showUpload, setShowUpload] = React.useState(false)

  // View & Filter states
  const [viewMode, setViewMode] = React.useState<'grid' | 'table'>('grid')
  const [categoryFilter, setCategoryFilter] =
    React.useState<CategoryFilter>('all')
  const [searchFilter, setSearchFilter] = React.useState('')

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

  // Calculate counts & stats
  const stats = React.useMemo(() => {
    let images = 0
    let videos = 0
    let audio = 0
    let documents = 0
    let totalBytes = 0

    for (const a of assets) {
      totalBytes += a.byte_size
      const cat = getMimeCategory(a.content_type)
      if (cat === 'image') images++
      else if (cat === 'video') videos++
      else if (cat === 'audio') audio++
      else if (cat === 'document') documents++
    }

    return {
      images,
      videos,
      audio,
      documents,
      totalBytes,
      total: assets.length,
    }
  }, [assets])

  // Filtered assets
  const filteredAssets = React.useMemo(() => {
    return assets.filter((asset) => {
      const matchCategory =
        categoryFilter === 'all' ||
        getMimeCategory(asset.content_type) === categoryFilter
      const matchSearch =
        !searchFilter.trim() ||
        asset.filename.toLowerCase().includes(searchFilter.trim().toLowerCase())
      return matchCategory && matchSearch
    })
  }, [assets, categoryFilter, searchFilter])

  return (
    <div className="space-y-6">
      {/* Top Header & Actions */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground">
            Asset Library
          </h2>
          <p className="text-xs text-muted-foreground">
            Visual media collection indexed with local embeddings, Whisper, and
            OCR.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadAssets(false)}
            disabled={loading}
            className="gap-1.5 rounded-xl text-xs"
          >
            <RefreshCw
              className={`size-3.5 ${loading ? 'animate-spin' : ''}`}
            />
            Refresh
          </Button>

          <Button
            size="sm"
            onClick={() => setShowUpload((prev) => !prev)}
            className="gap-1.5 rounded-xl text-xs font-semibold shadow-xs"
          >
            <Plus className="size-3.5" />
            {showUpload ? 'Hide Uploader' : 'Upload Assets'}
          </Button>
        </div>
      </div>

      {/* Summary Stats Overview */}
      {assets.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
          <div className="flex items-center gap-3 rounded-2xl border border-border/70 bg-card p-3 shadow-2xs">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Layers className="size-5" />
            </div>
            <div>
              <p className="text-[11px] font-medium text-muted-foreground">
                Total Assets
              </p>
              <p className="text-base font-bold text-foreground">
                {stats.total}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-2xl border border-border/70 bg-card p-3 shadow-2xs">
            <div className="flex size-10 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-500">
              <ImageIcon className="size-5" />
            </div>
            <div>
              <p className="text-[11px] font-medium text-muted-foreground">
                Images
              </p>
              <p className="text-base font-bold text-foreground">
                {stats.images}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-2xl border border-border/70 bg-card p-3 shadow-2xs">
            <div className="flex size-10 items-center justify-center rounded-xl bg-amber-500/10 text-amber-500">
              <Video className="size-5" />
            </div>
            <div>
              <p className="text-[11px] font-medium text-muted-foreground">
                Videos
              </p>
              <p className="text-base font-bold text-foreground">
                {stats.videos}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-2xl border border-border/70 bg-card p-3 shadow-2xs">
            <div className="flex size-10 items-center justify-center rounded-xl bg-violet-500/10 text-violet-500">
              <Music className="size-5" />
            </div>
            <div>
              <p className="text-[11px] font-medium text-muted-foreground">
                Audio
              </p>
              <p className="text-base font-bold text-foreground">
                {stats.audio}
              </p>
            </div>
          </div>

          <div className="col-span-2 flex items-center gap-3 rounded-2xl border border-border/70 bg-card p-3 shadow-2xs sm:col-span-1">
            <div className="flex size-10 items-center justify-center rounded-xl bg-sky-500/10 text-sky-500">
              <HardDrive className="size-5" />
            </div>
            <div>
              <p className="text-[11px] font-medium text-muted-foreground">
                Storage Used
              </p>
              <p className="font-mono text-base font-bold text-foreground">
                {formatBytes(stats.totalBytes)}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Uploader Section */}
      {showUpload && (
        <div className="animate-in rounded-2xl border border-border bg-card p-5 shadow-sm duration-200 fade-in-50">
          <UploadDropzone onUploadSuccess={handleUploadSuccess} />
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-xs text-destructive">
          <AlertCircle className="size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Filter and View Controls Bar */}
      <div className="flex flex-col gap-3 rounded-2xl border border-border/80 bg-card/60 p-3 shadow-2xs backdrop-blur-xs sm:flex-row sm:items-center sm:justify-between">
        {/* Category Filter Tabs */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setCategoryFilter('all')}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all ${
              categoryFilter === 'all'
                ? 'bg-primary text-primary-foreground shadow-2xs'
                : 'border border-border/80 bg-muted/30 text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <Layers className="size-3.5" />
            <span>All ({stats.total})</span>
          </button>

          <button
            type="button"
            onClick={() => setCategoryFilter('image')}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all ${
              categoryFilter === 'image'
                ? 'bg-primary text-primary-foreground shadow-2xs'
                : 'border border-border/80 bg-muted/30 text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <ImageIcon className="size-3.5" />
            <span>Images ({stats.images})</span>
          </button>

          <button
            type="button"
            onClick={() => setCategoryFilter('video')}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all ${
              categoryFilter === 'video'
                ? 'bg-primary text-primary-foreground shadow-2xs'
                : 'border border-border/80 bg-muted/30 text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <Video className="size-3.5" />
            <span>Videos ({stats.videos})</span>
          </button>

          <button
            type="button"
            onClick={() => setCategoryFilter('audio')}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all ${
              categoryFilter === 'audio'
                ? 'bg-primary text-primary-foreground shadow-2xs'
                : 'border border-border/80 bg-muted/30 text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <Music className="size-3.5" />
            <span>Audio ({stats.audio})</span>
          </button>

          <button
            type="button"
            onClick={() => setCategoryFilter('document')}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all ${
              categoryFilter === 'document'
                ? 'bg-primary text-primary-foreground shadow-2xs'
                : 'border border-border/80 bg-muted/30 text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <FileText className="size-3.5" />
            <span>Documents ({stats.documents})</span>
          </button>
        </div>

        {/* Search & View Mode Switcher */}
        <div className="flex items-center gap-2">
          {/* Quick Filename Search */}
          <div className="relative flex items-center">
            <Search className="absolute left-2.5 size-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Filter by name..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="h-8 w-36 rounded-xl border border-input bg-background pr-2.5 pl-8 text-xs text-foreground placeholder:text-muted-foreground focus:ring-1 focus:ring-ring focus:outline-none sm:w-48"
            />
          </div>

          {/* View Mode Buttons */}
          <div className="flex items-center rounded-xl border border-border bg-muted/40 p-0.5">
            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={() => setViewMode('grid')}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-all ${
                viewMode === 'grid'
                  ? 'bg-background text-foreground shadow-2xs'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              title="Media Gallery View"
            >
              <LayoutGrid className="size-3.5" />
              <span className="ml-1 hidden sm:inline">Gallery</span>
            </Button>

            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={() => setViewMode('table')}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-all ${
                viewMode === 'table'
                  ? 'bg-background text-foreground shadow-2xs'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              title="Table View"
            >
              <List className="size-3.5" />
              <span className="ml-1 hidden sm:inline">Table</span>
            </Button>
          </div>
        </div>
      </div>

      {/* Asset Display */}
      {viewMode === 'grid' ? (
        <AssetGrid
          assets={filteredAssets}
          loading={loading}
          onPreview={(asset) => setPreviewAsset(asset)}
          onOpenStatus={(asset) => setStatusAsset(asset)}
          onReprocess={(asset) => setReprocessAsset(asset)}
          onRetry={handleRetry}
          onCancel={handleCancel}
          onDelete={handleDelete}
        />
      ) : (
        <AssetTable
          assets={filteredAssets}
          loading={loading}
          onPreview={(asset) => setPreviewAsset(asset)}
          onOpenStatus={(asset) => setStatusAsset(asset)}
          onReprocess={(asset) => setReprocessAsset(asset)}
          onRetry={handleRetry}
          onCancel={handleCancel}
          onDelete={handleDelete}
        />
      )}

      {/* Modals */}
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
