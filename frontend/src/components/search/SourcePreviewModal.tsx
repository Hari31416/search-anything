import * as React from 'react'
import {
  Download,
  FileText,
  Clock,
  ExternalLink,
  Volume2,
  AlertTriangle,
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
      initialSeekSeconds > 0
    ) {
      try {
        mediaRef.current.currentTime = initialSeekSeconds
      } catch {
        // Seek failed or not ready
      }
    }
  }

  if (!asset) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] max-w-3xl flex-col p-6">
        <DialogHeader className="pr-6">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <DialogTitle className="truncate text-base font-semibold">
                {asset.filename}
              </DialogTitle>
              <DialogDescription className="flex items-center gap-2 text-xs">
                <span className="font-mono">{asset.content_type}</span>
                <span>&bull;</span>
                <span>{formatBytes(asset.byte_size)}</span>
                {asset.duration_seconds && (
                  <>
                    <span>&bull;</span>
                    <span>{formatDuration(asset.duration_seconds)}</span>
                  </>
                )}
              </DialogDescription>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button variant="outline" size="xs" asChild>
                <a
                  href={contentUrl}
                  download={asset.filename}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Download className="mr-1 size-3.5" /> Download
                </a>
              </Button>
              {presignedUrl && (
                <Button variant="ghost" size="xs" asChild>
                  <a
                    href={presignedUrl}
                    target="_blank"
                    rel="noreferrer"
                    title="Open presigned link"
                  >
                    <ExternalLink className="size-3.5" />
                  </a>
                </Button>
              )}
            </div>
          </div>
        </DialogHeader>

        {initialSeekSeconds !== null &&
          initialSeekSeconds !== undefined &&
          initialSeekSeconds > 0 && (
            <div className="flex items-center gap-1.5 rounded bg-primary/10 px-3 py-1.5 text-xs text-primary">
              <Clock className="size-3.5" />
              <span>
                Seeking to matching timestamp:{' '}
                {formatDuration(initialSeekSeconds)}
              </span>
            </div>
          )}

        <div className="flex min-h-[300px] flex-1 flex-col items-center justify-center overflow-auto rounded-lg border border-border bg-muted/20 p-4">
          {category === 'video' ? (
            <video
              ref={(el) => {
                mediaRef.current = el
              }}
              src={contentUrl}
              controls
              onLoadedMetadata={onLoadedMetadata}
              onError={() => setPlaybackError(true)}
              className="max-h-[60vh] w-full rounded bg-black object-contain"
            >
              Your browser does not support HTML5 video.
            </video>
          ) : category === 'audio' ? (
            <div className="flex flex-col items-center gap-4 py-8">
              <div className="flex size-16 items-center justify-center rounded-full bg-primary/10 text-primary">
                <Volume2 className="size-8" />
              </div>
              <audio
                ref={(el) => {
                  mediaRef.current = el
                }}
                src={contentUrl}
                controls
                onLoadedMetadata={onLoadedMetadata}
                onError={() => setPlaybackError(true)}
                className="w-full max-w-md"
              >
                Your browser does not support HTML5 audio.
              </audio>
            </div>
          ) : category === 'image' ? (
            <img
              src={contentUrl}
              alt={asset.filename}
              className="max-h-[65vh] max-w-full rounded object-contain shadow-xs"
            />
          ) : asset.content_type === 'application/pdf' ? (
            <div className="flex h-[65vh] w-full flex-col">
              <iframe
                src={`${contentUrl}#view=FitH`}
                title={asset.filename}
                className="h-full w-full rounded border-0 bg-background"
              />
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 p-8 text-center">
              <div className="flex size-14 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <FileText className="size-7" />
              </div>
              <h4 className="text-sm font-semibold text-foreground">
                Original file preview
              </h4>
              <p className="max-w-md text-xs text-muted-foreground">
                Preview for this document format is handled via extracted
                passage evidence. You can download the full original file to
                view in your local application.
              </p>
              <Button size="sm" asChild className="mt-2">
                <a href={contentUrl} download={asset.filename}>
                  <Download className="mr-1.5 size-3.5" /> Download Original (
                  {formatBytes(asset.byte_size)})
                </a>
              </Button>
            </div>
          )}

          {playbackError && (
            <div className="mt-4 flex items-center gap-2 rounded border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle className="size-4 shrink-0" />
              <span>
                Your browser could not decode this media stream. Use the
                Download button above to open it locally.
              </span>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
