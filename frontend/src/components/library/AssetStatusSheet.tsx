import * as React from 'react'
import {
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Clock,
  XCircle,
  Play,
  RotateCcw,
  Ban,
  Layers,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { api, ApiError } from '@/lib/api'
import { formatDate } from '@/lib/formatters'
import type {
  Asset,
  AssetStatus,
  GenerationStatus,
  JobStatus,
} from '@/types/api'

interface AssetStatusSheetProps {
  asset: Asset | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onAssetUpdated: () => void
}

export function AssetStatusSheet({
  asset,
  open,
  onOpenChange,
  onAssetUpdated,
}: AssetStatusSheetProps) {
  const [statusData, setStatusData] = React.useState<AssetStatus | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [actionInProgress, setActionInProgress] = React.useState(false)
  const [actionError, setActionError] = React.useState<string | null>(null)
  const [expandedGenerations, setExpandedGenerations] = React.useState<
    Record<string, boolean>
  >({})

  const fetchStatus = React.useCallback(async () => {
    if (!asset) return
    try {
      setLoading(true)
      const data = await api.getAssetStatus(asset.id)
      setStatusData(data)
      setError(null)
      // Auto expand latest generation
      if (data.generations.length > 0) {
        setExpandedGenerations((prev) => ({
          ...prev,
          [data.generations[0].id]: true,
        }))
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.details)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to fetch status')
      }
    } finally {
      setLoading(false)
    }
  }, [asset])

  React.useEffect(() => {
    if (open && asset) {
      fetchStatus()
      // Polling while open if status is not ready or has running jobs
      const interval = setInterval(() => {
        api
          .getAssetStatus(asset.id)
          .then((data) => {
            setStatusData(data)
            // If all done, we can update parent
            const anyActive = data.generations.some(
              (g) => g.state === 'queued' || g.state === 'processing'
            )
            if (!anyActive) {
              onAssetUpdated()
            }
          })
          .catch(() => {})
      }, 3000)
      return () => clearInterval(interval)
    } else {
      setStatusData(null)
      setError(null)
      setActionError(null)
    }
  }, [open, asset, fetchStatus, onAssetUpdated])

  const toggleGenExpanded = (genId: string) => {
    setExpandedGenerations((prev) => ({
      ...prev,
      [genId]: !prev[genId],
    }))
  }

  const handleRetry = async () => {
    if (!asset) return
    setActionInProgress(true)
    setActionError(null)
    try {
      await api.retryAsset(asset.id)
      await fetchStatus()
      onAssetUpdated()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Retry failed')
    } finally {
      setActionInProgress(false)
    }
  }

  const handleCancel = async (generationId?: string) => {
    if (!asset) return
    setActionInProgress(true)
    setActionError(null)
    try {
      await api.cancelAsset(asset.id, generationId)
      await fetchStatus()
      onAssetUpdated()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Cancel failed')
    } finally {
      setActionInProgress(false)
    }
  }

  const renderJobBadge = (job: JobStatus) => {
    switch (job.status) {
      case 'completed':
        return (
          <Badge variant="success" className="gap-1 text-[10px]">
            <CheckCircle2 className="size-2.5 text-emerald-500" /> Done
          </Badge>
        )
      case 'running':
      case 'leased':
        return (
          <Badge variant="info" className="gap-1 text-[10px]">
            <Play className="size-2.5 animate-pulse text-sky-500" /> Running
          </Badge>
        )
      case 'queued':
      case 'pending':
        return (
          <Badge variant="secondary" className="gap-1 text-[10px]">
            <Clock className="size-2.5 text-muted-foreground" /> Queued
          </Badge>
        )
      case 'retry':
        return (
          <Badge variant="warning" className="gap-1 text-[10px]">
            <RotateCcw className="size-2.5 text-amber-500" /> Retrying
          </Badge>
        )
      case 'failed':
        return (
          <Badge variant="destructive" className="gap-1 text-[10px]">
            <XCircle className="size-2.5 text-destructive" /> Failed
          </Badge>
        )
      case 'cancelled':
        return (
          <Badge variant="muted" className="gap-1 text-[10px]">
            <Ban className="size-2.5 text-muted-foreground" /> Cancelled
          </Badge>
        )
      default:
        return (
          <Badge variant="secondary" className="text-[10px]">
            {job.status}
          </Badge>
        )
    }
  }

  if (!asset) return null

  const hasFailedJob = statusData?.generations.some((g) =>
    g.jobs.some((j) => j.status === 'failed')
  )
  const hasRunningJob = statusData?.generations.some(
    (g) =>
      g.state === 'processing' ||
      g.state === 'queued' ||
      g.jobs.some((j) => j.status === 'running' || j.status === 'queued')
  )

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="overflow-y-auto">
        <SheetHeader>
          <div className="flex items-center justify-between pr-6">
            <SheetTitle className="truncate text-base font-semibold">
              {asset.filename}
            </SheetTitle>
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={fetchStatus}
              disabled={loading}
              title="Refresh status"
            >
              <RefreshCw
                className={`size-3.5 ${loading ? 'animate-spin' : ''}`}
              />
            </Button>
          </div>
          <SheetDescription className="text-xs">
            ID: <span className="font-mono text-[11px]">{asset.id}</span>
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 space-y-6">
          {actionError && (
            <div className="rounded-md border border-destructive/20 bg-destructive/10 p-3 text-xs text-destructive">
              {actionError}
            </div>
          )}

          {/* Quick Action Bar */}
          <div className="flex flex-wrap items-center gap-2">
            {hasFailedJob && (
              <Button
                variant="default"
                size="xs"
                onClick={handleRetry}
                disabled={actionInProgress}
                className="gap-1.5"
              >
                <RotateCcw className="size-3" /> Retry Failed
              </Button>
            )}
            {hasRunningJob && (
              <Button
                variant="destructive"
                size="xs"
                onClick={() => handleCancel()}
                disabled={actionInProgress}
                className="gap-1.5"
              >
                <Ban className="size-3" /> Cancel Work
              </Button>
            )}
          </div>

          {error && (
            <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-xs text-destructive">
              <div className="flex items-center gap-2">
                <AlertCircle className="size-4" />
                <span>{error}</span>
              </div>
            </div>
          )}

          {/* Overall Asset Status Summary */}
          {statusData && (
            <div className="grid grid-cols-2 gap-3 rounded-lg border border-border/80 bg-muted/20 p-3 text-xs">
              <div>
                <span className="text-muted-foreground">Asset State:</span>
                <div className="mt-0.5 font-medium text-foreground uppercase">
                  {statusData.state}
                </div>
              </div>
              <div>
                <span className="text-muted-foreground">
                  Active Generation:
                </span>
                <div
                  className="mt-0.5 truncate font-mono text-[11px] text-foreground"
                  title={statusData.active_generation_id || 'None'}
                >
                  {statusData.active_generation_id
                    ? statusData.active_generation_id.slice(0, 8) + '...'
                    : 'None yet'}
                </div>
              </div>
            </div>
          )}

          {/* Generations list */}
          <div className="space-y-4">
            <h4 className="flex items-center gap-2 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
              <Layers className="size-3.5" /> Processing Generations (
              {statusData?.generations.length || 0})
            </h4>

            {statusData?.generations.map(
              (gen: GenerationStatus, idx: number) => {
                const isCurrent = gen.id === statusData.current_generation_id
                const isActive = gen.id === statusData.active_generation_id
                const isExpanded = !!expandedGenerations[gen.id]

                return (
                  <div
                    key={gen.id}
                    className="overflow-hidden rounded-lg border border-border bg-card shadow-2xs"
                  >
                    <div
                      onClick={() => toggleGenExpanded(gen.id)}
                      className="flex cursor-pointer items-center justify-between p-3.5 transition-colors hover:bg-muted/40"
                    >
                      <div className="flex items-center gap-2">
                        {isExpanded ? (
                          <ChevronDown className="size-4 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="size-4 text-muted-foreground" />
                        )}
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-semibold text-foreground">
                              Gen #{statusData.generations.length - idx}
                            </span>
                            <span className="font-mono text-[10px] text-muted-foreground">
                              ({gen.id.slice(0, 8)})
                            </span>
                            {isActive && (
                              <Badge
                                variant="success"
                                className="px-1.5 py-0 text-[9px]"
                              >
                                Active in Search
                              </Badge>
                            )}
                            {isCurrent && !isActive && (
                              <Badge
                                variant="info"
                                className="px-1.5 py-0 text-[9px]"
                              >
                                Current Target
                              </Badge>
                            )}
                          </div>
                          <div className="mt-0.5 text-[11px] text-muted-foreground">
                            {formatDate(gen.created_at)} &bull; State:{' '}
                            <span className="font-medium text-foreground">
                              {gen.state}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="space-y-4 border-t border-border/60 bg-muted/10 p-3.5">
                        {/* Profile snapshot information */}
                        {gen.profile_snapshot &&
                          Object.keys(gen.profile_snapshot).length > 0 && (
                            <div className="space-y-1.5 rounded-md border border-border/60 bg-background p-2.5 text-[11px]">
                              <span className="text-[10px] font-semibold text-muted-foreground uppercase">
                                Profile Snapshot
                              </span>
                              <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-muted-foreground">
                                {Object.entries(gen.profile_snapshot).map(
                                  ([key, val]) => (
                                    <div
                                      key={key}
                                      className="flex justify-between"
                                    >
                                      <span>{key}:</span>
                                      <span
                                        className="max-w-[120px] truncate font-medium text-foreground"
                                        title={String(val)}
                                      >
                                        {String(val)}
                                      </span>
                                    </div>
                                  )
                                )}
                              </div>
                            </div>
                          )}

                        {/* Jobs list */}
                        <div className="space-y-2">
                          <span className="text-[10px] font-semibold text-muted-foreground uppercase">
                            Stages & Pipeline Jobs ({gen.jobs.length})
                          </span>

                          {gen.jobs.length === 0 ? (
                            <p className="text-xs text-muted-foreground italic">
                              No jobs recorded for this generation
                            </p>
                          ) : (
                            <div className="space-y-2">
                              {gen.jobs.map((job: JobStatus) => (
                                <div
                                  key={job.id}
                                  className="space-y-2 rounded-md border border-border/70 bg-card p-3 text-xs"
                                >
                                  <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                      <span className="font-semibold tracking-wide text-foreground uppercase">
                                        {job.stage}
                                      </span>
                                      <span className="text-[11px] text-muted-foreground">
                                        attempt {job.attempts}/
                                        {job.max_attempts}
                                      </span>
                                    </div>
                                    <div>{renderJobBadge(job)}</div>
                                  </div>

                                  {/* Progress bar if running or partial */}
                                  {(job.status === 'running' ||
                                    (job.progress > 0 && job.progress < 1)) && (
                                    <div className="space-y-1">
                                      <div className="flex justify-between text-[10px] text-muted-foreground">
                                        <span>Progress</span>
                                        <span>
                                          {Math.round(job.progress * 100)}%
                                        </span>
                                      </div>
                                      <Progress
                                        value={job.progress * 100}
                                        className="h-1.5"
                                      />
                                    </div>
                                  )}

                                  {/* Error message if failed */}
                                  {job.error_message && (
                                    <div className="space-y-0.5 rounded bg-destructive/10 p-2 text-[11px] text-destructive">
                                      {job.error_code && (
                                        <div className="text-[10px] font-semibold uppercase">
                                          Code: {job.error_code}
                                        </div>
                                      )}
                                      <div className="break-words">
                                        {job.error_message}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )
              }
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
