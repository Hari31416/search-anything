import * as React from 'react'
import {
  Download,
  FileText,
  Clock,
  ExternalLink,
  Volume2,
  AlertTriangle,
  Image as ImageIcon,
  Video,
  Music,
} from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { pauseOtherMedia } from '@/lib/media-playback'
import { formatBytes, formatDuration, getMimeCategory } from '@/lib/formatters'
import type { Asset } from '@/types/api'

interface SourcePreviewModalProps {
  asset: Asset | null
  initialSeekSeconds?: number | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SourcePreviewModal({
  asset,
  initialSeekSeconds,
  open,
  onOpenChange,
}: SourcePreviewModalProps) {
  const mediaRef = React.useRef<HTMLMediaElement | null>(null)
  const [playbackError, setPlaybackError] = React.useState(false)
  const [presignedUrl, setPresignedUrl] = React.useState<string | null>(null)

  const contentUrl = asset ? api.getAssetContentUrl(asset.id) : ''
  const category = asset ? getMimeCategory(asset.content_type) : 'other'

  React.useEffect(() => {
    setPlaybackError(false)
    if (asset && open) {
      pauseOtherMedia()
      api
        .getPresignedUrl(asset.id)
        .then((res) => setPresignedUrl(res.url))
        .catch(() => setPresignedUrl(null))
    } else {
      setPresignedUrl(null)
    }
  }, [asset, open])

  // Seek when media loaded
  const onLoadedMetadata = () => {
    if (
      mediaRef.current &&
      initialSeekSeconds !== null &&
      initialSeekSeconds !== undefined &&
      initialSeekSeconds >= 0
    ) {
      try {
        mediaRef.current.currentTime = initialSeekSeconds
      } catch {
        // Seek failed or not ready
      }
    }
  }

  if (!asset) return null

  const renderCategoryIcon = () => {
    switch (category) {
      case 'image':
        return <ImageIcon className="size-4 text-emerald-400" />
      case 'video':
        return <Video className="size-4 text-amber-400" />
      case 'audio':
        return <Music className="size-4 text-sky-400" />
      default:
        return <FileText className="size-4 text-sky-400" />
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] max-w-4xl flex-col rounded-2xl border-border/80 bg-background/98 p-6 shadow-2xl backdrop-blur-xl">
        <DialogHeader className="pr-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-border bg-muted/60 shadow-2xs">
                {renderCategoryIcon()}
              </div>

              <div className="min-w-0">
                <DialogTitle className="truncate text-base font-bold text-foreground">
                  {asset.filename}
                </DialogTitle>
                <DialogDescription className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono">{asset.content_type}</span>
                  <span>&bull;</span>
                  <span>{formatBytes(asset.byte_size)}</span>
                  {asset.duration_seconds && (
                    <>
                      <span>&bull;</span>
                      <span className="font-mono">
                        {formatDuration(asset.duration_seconds)}
                      </span>
                    </>
                  )}
                  {asset.page_count && (
                    <>
                      <span>&bull;</span>
                      <span>{asset.page_count} pages</span>
                    </>
                  )}
                </DialogDescription>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                asChild
                className="gap-1.5 rounded-xl text-xs"
              >
                <a
                  href={contentUrl}
                  download={asset.filename}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Download className="size-3.5" /> Download
                </a>
              </Button>
              {presignedUrl && (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  asChild
                  className="rounded-xl"
                >
                  <a
                    href={presignedUrl}
                    target="_blank"
                    rel="noreferrer"
                    title="Open presigned link in new tab"
                  >
                    <ExternalLink className="size-4" />
                  </a>
                </Button>
              )}
            </div>
          </div>
        </DialogHeader>

        {/* Timestamp seek notification pill */}
        {initialSeekSeconds !== null &&
          initialSeekSeconds !== undefined &&
          initialSeekSeconds >= 0 && (
            <div className="flex animate-in items-center gap-2 rounded-xl border border-primary/30 bg-primary/10 px-3.5 py-2 text-xs font-medium text-primary fade-in-50">
              <Clock className="size-4 shrink-0" />
              <span>
                Cued to matched timestamp:{' '}
                <strong>{formatDuration(initialSeekSeconds)}</strong>
              </span>
            </div>
          )}

        {/* Theater Viewport */}
        <div className="flex min-h-[350px] flex-1 flex-col items-center justify-center overflow-auto rounded-2xl border border-border/70 bg-black/5 p-4 shadow-inner dark:bg-black/60">
          {category === 'video' ? (
            <div className="flex w-full items-center justify-center">
              <video
                ref={(el) => {
                  mediaRef.current = el
                }}
                src={contentUrl}
                controls
                onLoadedMetadata={onLoadedMetadata}
                onError={() => setPlaybackError(true)}
                className="max-h-[65vh] w-full rounded-xl bg-black object-contain shadow-xl"
              >
                Your browser does not support HTML5 video.
              </video>
            </div>
          ) : category === 'audio' ? (
            <div className="flex w-full flex-col items-center gap-6 py-10">
              <div className="flex size-20 items-center justify-center rounded-3xl bg-sky-500/15 text-sky-500 shadow-lg ring-8 ring-sky-500/10">
                <Volume2 className="size-10" />
              </div>

              {/* Animated Waveform Display */}
              <div className="flex h-12 items-center gap-1.5">
                {[
                  40, 70, 95, 30, 80, 100, 60, 45, 90, 75, 55, 85, 40, 65, 95,
                  50, 80,
                ].map((h, i) => (
                  <span
                    key={i}
                    style={{ height: `${h * 0.45}px` }}
                    className="w-1.5 rounded-full bg-sky-500/60 transition-all duration-300"
                  />
                ))}
              </div>

              <audio
                ref={(el) => {
                  mediaRef.current = el
                }}
                src={contentUrl}
                controls
                onLoadedMetadata={onLoadedMetadata}
                onError={() => setPlaybackError(true)}
                className="w-full max-w-lg"
              >
                Your browser does not support HTML5 audio.
              </audio>
            </div>
          ) : category === 'image' ? (
            <div className="relative flex max-h-[70vh] w-full items-center justify-center p-2">
              <img
                src={contentUrl}
                alt={asset.filename}
                className="max-h-[65vh] max-w-full rounded-xl object-contain shadow-2xl"
              />
            </div>
          ) : asset.content_type === 'application/pdf' ? (
            <div className="flex h-[68vh] w-full flex-col">
              <iframe
                src={`${contentUrl}#view=FitH`}
                title={asset.filename}
                className="h-full w-full rounded-xl border border-border bg-background shadow-md"
              />
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 p-8 text-center">
              <div className="flex size-16 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
                <FileText className="size-8" />
              </div>
              <h4 className="text-sm font-semibold text-foreground">
                Original document
              </h4>
              <p className="max-w-md text-xs leading-relaxed text-muted-foreground">
                Matches are extracted and searchable via text passages and OCR.
                Download the original file to view in your system application.
              </p>
              <Button size="sm" asChild className="mt-3 rounded-xl">
                <a href={contentUrl} download={asset.filename}>
                  <Download className="mr-1.5 size-4" /> Download Original (
                  {formatBytes(asset.byte_size)})
                </a>
              </Button>
            </div>
          )}

          {playbackError && (
            <div className="mt-4 flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle className="size-4 shrink-0" />
              <span>
                Your browser could not decode this media stream natively. Click
                Download to view locally.
              </span>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
