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

interface AssetTableProps {
  assets: Asset[]
  loading: boolean
  onPreview: (asset: Asset) => void
  onOpenStatus: (asset: Asset) => void
  onReprocess: (asset: Asset) => void
  onRetry: (asset: Asset) => void
  onCancel: (asset: Asset) => void
  onDelete: (asset: Asset) => void
}

export function AssetTable({
  assets,
  loading,
  onPreview,
  onOpenStatus,
  onReprocess,
  onRetry,
  onCancel,
  onDelete,
}: AssetTableProps) {
  const api = useWorkspaceApi()
  const [deleteTarget, setDeleteTarget] = React.useState<Asset | null>(null)
  const [activeMenuId, setActiveMenuId] = React.useState<string | null>(null)

  const renderThumbnail = (asset: Asset) => {
    const category = getMimeCategory(asset.content_type)
    const contentUrl = api.getAssetContentUrl(asset.id)

    if (category === 'image') {
      return (
        <div className="size-9 shrink-0 overflow-hidden rounded-lg border border-border/80 bg-muted/40 shadow-2xs">
          <img
            src={contentUrl}
            alt={asset.filename}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        </div>
      )
    }

    if (category === 'video') {
      return (
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-amber-500/20 bg-amber-500/10 text-amber-500">
          <Video className="size-4" />
        </div>
      )
    }

    if (category === 'audio') {
      return (
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-sky-500/20 bg-sky-500/10 text-sky-500">
          <Music className="size-4" />
        </div>
      )
    }

    if (category === 'document') {
      return (
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-sky-500/20 bg-sky-500/10 text-sky-500">
          <FileText className="size-4" />
        </div>
      )
    }

    return (
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <FileQuestion className="size-4" />
      </div>
    )
  }

  const renderStateBadge = (state: string) => {
    switch (state) {
      case 'ready':
        return (
          <Badge variant="success" className="gap-1 text-[11px] font-normal">
            <CheckCircle2 className="size-3 text-emerald-500" /> Ready
          </Badge>
        )
      case 'processing':
      case 'queued':
      case 'pending':
        return (
          <Badge variant="info" className="gap-1 text-[11px] font-normal">
            <Clock className="size-3 animate-pulse text-sky-500" /> {state}
          </Badge>
        )
      case 'failed':
        return (
          <Badge
            variant="destructive"
            className="gap-1 text-[11px] font-normal"
          >
            <XCircle className="size-3 text-destructive" /> Failed
          </Badge>
        )
      case 'cancelled':
        return (
          <Badge variant="muted" className="gap-1 text-[11px] font-normal">
            <Ban className="size-3 text-muted-foreground" /> Cancelled
          </Badge>
        )
      default:
        return (
          <Badge variant="secondary" className="text-[11px] font-normal">
            {state}
          </Badge>
        )
    }
  }

  if (loading && assets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-border bg-card p-12 text-center">
        <Clock className="size-8 animate-spin text-muted-foreground" />
        <p className="mt-3 text-sm text-muted-foreground">
          Loading library assets...
        </p>
      </div>
    )
  }

  if (assets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card/50 p-12 text-center">
        <FileQuestion className="size-10 text-muted-foreground/60" />
        <h4 className="mt-3 text-sm font-semibold text-foreground">
          No assets match the filter
        </h4>
        <p className="mt-1 max-w-sm text-xs text-muted-foreground">
          Upload documents, images, audio, or video files above to start
          indexing.
        </p>
      </div>
    )
  }

  return (
    <>
      <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-xs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-border bg-muted/40 font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3.5">Asset</th>
                <th className="px-3 py-3.5">Format</th>
                <th className="px-3 py-3.5">Size / Length</th>
                <th className="px-3 py-3.5">Status</th>
                <th className="px-3 py-3.5">Created</th>
                <th className="px-4 py-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {assets.map((asset) => {
                const isMenuOpen = activeMenuId === asset.id
                return (
                  <tr
                    key={asset.id}
                    className="transition-colors hover:bg-muted/30"
                  >
                    <td className="px-4 py-3 font-medium text-foreground">
                      <div className="flex max-w-xs items-center gap-3 md:max-w-md">
                        {renderThumbnail(asset)}
                        <div className="min-w-0">
                          <p
                            className="cursor-pointer truncate font-semibold text-foreground transition-colors hover:text-primary"
                            onClick={() => onPreview(asset)}
                            title={asset.filename}
                          >
                            {asset.filename}
                          </p>
                          <p className="font-mono text-[10px] text-muted-foreground">
                            {asset.id.slice(0, 8)}...
                          </p>
                        </div>
                      </div>
                    </td>

                    <td className="px-3 py-3 text-muted-foreground">
                      <span
                        className="inline-block max-w-[140px] truncate font-mono text-[11px]"
                        title={asset.content_type}
                      >
                        {asset.content_type}
                      </span>
                    </td>

                    <td className="px-3 py-3 text-muted-foreground">
                      <div>{formatBytes(asset.byte_size)}</div>
                      {asset.duration_seconds !== null && (
                        <div className="font-mono text-[10px] text-muted-foreground">
                          {formatDuration(asset.duration_seconds)}
                        </div>
                      )}
                      {asset.page_count !== null && (
                        <div className="text-[10px] text-muted-foreground">
                          {asset.page_count} pages
                        </div>
                      )}
                    </td>

                    <td className="px-3 py-3">
                      {renderStateBadge(asset.state)}
                    </td>

                    <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                      {formatDate(asset.created_at)}
                    </td>

                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => onPreview(asset)}
                          title="Preview content"
                        >
                          <Eye className="size-3.5 text-muted-foreground" />
                        </Button>

                        <Button
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => onOpenStatus(asset)}
                          title="View processing jobs & status"
                        >
                          <Activity className="size-3.5 text-muted-foreground" />
                        </Button>

                        <Button
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => onReprocess(asset)}
                          title="Reprocess with profile"
                        >
                          <RotateCw className="size-3.5 text-muted-foreground" />
                        </Button>

                        <div className="relative">
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() =>
                              setActiveMenuId(isMenuOpen ? null : asset.id)
                            }
                            title="More options"
                          >
                            <MoreVertical className="size-3.5 text-muted-foreground" />
                          </Button>

                          {isMenuOpen && (
                            <div className="absolute top-full right-0 z-30 mt-1 min-w-[140px] animate-in rounded-xl border border-border bg-popover p-1 text-popover-foreground shadow-lg fade-in-50 zoom-in-95">
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
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
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
