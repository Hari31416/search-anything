import * as React from 'react'
import {
  FileText,
  Music,
  Video,
  FileQuestion,
  Eye,
  Activity,
  RotateCw,
  Trash2,
  RotateCcw,
  Ban,
  CheckCircle2,
  Clock,
  XCircle,
  MoreVertical,
  Download,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  formatBytes,
  formatDate,
  formatDuration,
  getMimeCategory,
} from '@/lib/formatters'
import { useWorkspaceApi } from '@/lib/workspaces'
import type { Asset } from '@/types/api'

interface AssetGridProps {
  assets: Asset[]
  loading: boolean
  onPreview: (asset: Asset) => void
  onOpenStatus: (asset: Asset) => void
  onReprocess: (asset: Asset) => void
  onRetry: (asset: Asset) => void
  onCancel: (asset: Asset) => void
  onDelete: (asset: Asset) => void
}

export function AssetGrid({
  assets,
  loading,
  onPreview,
  onOpenStatus,
  onReprocess,
  onRetry,
  onCancel,
  onDelete,
}: AssetGridProps) {
  const api = useWorkspaceApi()
  const [deleteTarget, setDeleteTarget] = React.useState<Asset | null>(null)
  const [activeMenuId, setActiveMenuId] = React.useState<string | null>(null)

  const renderStateBadge = (state: string) => {
    switch (state) {
      case 'ready':
        return (
          <Badge
            variant="success"
            className="gap-1 border-emerald-500/30 bg-emerald-500/20 text-[10px] text-emerald-400 backdrop-blur-md"
          >
            <CheckCircle2 className="size-2.5" /> Ready
          </Badge>
        )
      case 'processing':
      case 'queued':
      case 'pending':
        return (
          <Badge
            variant="info"
            className="gap-1 border-sky-500/30 bg-sky-500/20 text-[10px] text-sky-400 backdrop-blur-md"
          >
            <Clock className="size-2.5 animate-pulse" /> {state}
          </Badge>
        )
      case 'failed':
        return (
          <Badge
            variant="destructive"
            className="gap-1 text-[10px] backdrop-blur-md"
          >
            <XCircle className="size-2.5" /> Failed
          </Badge>
        )
      case 'cancelled':
        return (
          <Badge variant="muted" className="gap-1 text-[10px] backdrop-blur-md">
            <Ban className="size-2.5" /> Cancelled
          </Badge>
        )
      default:
        return (
          <Badge variant="secondary" className="text-[10px] backdrop-blur-md">
            {state}
          </Badge>
        )
    }
  }

  if (loading && assets.length === 0) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
        {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
          <div
            key={n}
            className="aspect-square animate-pulse rounded-2xl border border-border bg-card p-4"
          />
        ))}
      </div>
    )
  }

  if (assets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card/40 p-12 text-center">
        <FileQuestion className="size-10 text-muted-foreground/60" />
        <h4 className="mt-3 text-sm font-semibold text-foreground">
          No assets match the filter
        </h4>
        <p className="mt-1 max-w-sm text-xs text-muted-foreground">
          Upload media files above or clear filters to view your indexed
          library.
        </p>
      </div>
    )
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
        {assets.map((asset) => {
          const category = getMimeCategory(asset.content_type)
          const contentUrl = api.getAssetContentUrl(asset.id)
          const isMenuOpen = activeMenuId === asset.id

          return (
            <div
              key={asset.id}
              className="group relative flex flex-col overflow-hidden rounded-2xl border border-border/80 bg-card shadow-xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md"
            >
              {/* Media Thumbnail Container */}
              <div
                className="relative flex aspect-16/10 w-full cursor-pointer items-center justify-center overflow-hidden bg-muted/40"
                onClick={() => onPreview(asset)}
              >
                {category === 'image' ? (
                  <div className="relative h-full w-full overflow-hidden bg-black/5 dark:bg-black/30">
                    <img
                      src={contentUrl}
                      alt={asset.filename}
                      loading="lazy"
                      className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
                  </div>
                ) : category === 'video' ? (
                  <div className="relative h-full w-full bg-black">
                    <video
                      src={contentUrl}
                      preload="metadata"
                      className="h-full w-full object-cover"
                    />
                    <div className="absolute inset-0 flex items-center justify-center bg-black/30 transition-colors group-hover:bg-black/10">
                      <div className="flex size-10 items-center justify-center rounded-full bg-white/90 text-black shadow-md backdrop-blur-xs">
                        <Video className="size-5" />
                      </div>
                    </div>
                  </div>
                ) : category === 'audio' ? (
                  <div className="flex h-full w-full flex-col items-center justify-center bg-gradient-to-br from-sky-950/20 via-background to-sky-950/10 p-4 text-center">
                    <div className="mb-2 flex size-11 items-center justify-center rounded-full bg-sky-500/15 text-sky-500">
                      <Music className="size-5" />
                    </div>
                    {/* Simulated Waveform Graphic */}
                    <div className="flex items-center gap-1">
                      {[30, 60, 90, 40, 75, 100, 50, 80, 35].map((h, i) => (
                        <span
                          key={i}
                          style={{ height: `${h * 0.22}px` }}
                          className="w-1 rounded-full bg-sky-500/50 transition-colors group-hover:bg-sky-500"
                        />
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="flex h-full w-full flex-col items-center justify-center bg-muted/30 p-4 text-center">
                    <div className="mb-1 flex size-11 items-center justify-center rounded-xl bg-sky-500/10 text-sky-500">
                      <FileText className="size-5" />
                    </div>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {asset.page_count
                        ? `${asset.page_count} pages`
                        : 'Document'}
                    </span>
                  </div>
                )}

                {/* Status Badge in Top Left */}
                <div className="absolute top-2.5 left-2.5 z-10">
                  {renderStateBadge(asset.state)}
                </div>

                {/* Duration Badge in Bottom Left */}
                {asset.duration_seconds !== null && (
                  <div className="absolute bottom-2.5 left-2.5 z-10 rounded-md bg-black/70 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white backdrop-blur-md">
                    {formatDuration(asset.duration_seconds)}
                  </div>
                )}

                {/* Page Count Badge in Bottom Left for Docs */}
                {asset.page_count !== null && (
                  <div className="absolute bottom-2.5 left-2.5 z-10 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-md">
                    {asset.page_count} pages
                  </div>
                )}

                {/* Quick Actions overlay on hover */}
                <div className="absolute right-2.5 bottom-2.5 z-10 flex items-center gap-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                  <Button
                    size="icon-xs"
                    variant="secondary"
                    className="size-7 rounded-md bg-black/75 text-white shadow-md backdrop-blur-xs hover:bg-black/90"
                    onClick={(e) => {
                      e.stopPropagation()
                      onPreview(asset)
                    }}
                    title="Preview content"
                  >
                    <Eye className="size-3.5" />
                  </Button>
                  <Button
                    size="icon-xs"
                    variant="secondary"
                    asChild
                    className="size-7 rounded-md bg-black/75 text-white shadow-md backdrop-blur-xs hover:bg-black/90"
                    onClick={(e) => e.stopPropagation()}
                    title="Download original"
                  >
                    <a href={contentUrl} download={asset.filename}>
                      <Download className="size-3.5" />
                    </a>
                  </Button>
                </div>
              </div>

              {/* Asset Card Footer */}
              <div className="flex flex-1 flex-col justify-between p-3">
                <div>
                  <h4
                    onClick={() => onPreview(asset)}
                    title={asset.filename}
                    className="cursor-pointer truncate text-xs font-semibold text-foreground transition-colors hover:text-primary"
                  >
                    {asset.filename}
                  </h4>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>{formatBytes(asset.byte_size)}</span>
                    <span className="font-mono text-[10px]">
                      {formatDate(asset.created_at)}
                    </span>
                  </div>
                </div>

                {/* Action Buttons Row */}
                <div className="mt-2.5 flex items-center justify-between border-t border-border/50 pt-2">
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      onClick={() => onOpenStatus(asset)}
                      title="View processing jobs & status"
                    >
                      <Activity className="size-3.5 text-muted-foreground hover:text-foreground" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      onClick={() => onReprocess(asset)}
                      title="Reprocess with profile"
                    >
                      <RotateCw className="size-3.5 text-muted-foreground hover:text-foreground" />
                    </Button>
                  </div>

                  {/* Context Menu */}
                  <div className="relative">
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      onClick={() =>
                        setActiveMenuId(isMenuOpen ? null : asset.id)
                      }
                      title="More actions"
                    >
                      <MoreVertical className="size-3.5 text-muted-foreground hover:text-foreground" />
                    </Button>

                    {isMenuOpen && (
                      <div className="absolute right-0 bottom-full z-30 mb-1 min-w-[140px] animate-in rounded-xl border border-border bg-popover p-1 text-popover-foreground shadow-lg fade-in-50 zoom-in-95">
                        {asset.state === 'failed' && (
                          <button
                            type="button"
                            onClick={() => {
                              setActiveMenuId(null)
                              onRetry(asset)
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
                          >
                            <RotateCcw className="size-3 text-amber-500" />
                            Retry Failed
                          </button>
                        )}

                        {(asset.state === 'processing' ||
                          asset.state === 'queued') && (
                          <button
                            type="button"
                            onClick={() => {
                              setActiveMenuId(null)
                              onCancel(asset)
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-foreground hover:bg-muted"
                          >
                            <Ban className="size-3 text-muted-foreground" />
                            Cancel Processing
                          </button>
                        )}

                        <button
                          type="button"
                          onClick={() => {
                            setActiveMenuId(null)
                            setDeleteTarget(asset)
                          }}
                          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-destructive hover:bg-destructive/10"
                        >
                          <Trash2 className="size-3 text-destructive" />
                          Delete Asset
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Delete confirmation dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <Trash2 className="size-5" />
              Delete Asset
            </DialogTitle>
            <DialogDescription>
              Are you sure you want to delete &quot;{deleteTarget?.filename}
              &quot;?
            </DialogDescription>
          </DialogHeader>
          <div className="py-2 text-xs text-muted-foreground">
            This will cancel running processing, remove the asset from search
            indexing, and asynchronously delete all stored artifacts.
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeleteTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                if (deleteTarget) {
                  onDelete(deleteTarget)
                  setDeleteTarget(null)
                }
              }}
            >
              Confirm Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
