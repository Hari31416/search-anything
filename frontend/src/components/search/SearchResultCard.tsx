import * as React from 'react'
import {
  FileText,
  Image as ImageIcon,
  Music,
  Video,
  FileQuestion,
  Eye,
  ChevronDown,
  ChevronUp,
  Download,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { MatchItem } from '@/components/search/MatchItem'
import { formatScore, getMimeCategory } from '@/lib/formatters'
import { api } from '@/lib/api'
import type { SearchResult, Asset } from '@/types/api'

interface SearchResultCardProps {
  result: SearchResult
  onPreviewAsset: (assetSummary: Asset, initialSeek?: number | null) => void
}

export function SearchResultCard({
  result,
  onPreviewAsset,
}: SearchResultCardProps) {
  const [showInlinePreview, setShowInlinePreview] = React.useState(true)
  const mediaRef = React.useRef<HTMLMediaElement | null>(null)

  const contentUrl = api.getAssetContentUrl(result.asset_id)
  const category = getMimeCategory(result.content_type)

  const renderTypeIcon = () => {
    switch (category) {
      case 'document':
        return <FileText className="size-4 text-sky-500" />
      case 'image':
        return <ImageIcon className="size-4 text-emerald-500" />
      case 'audio':
        return <Music className="size-4 text-violet-500" />
      case 'video':
        return <Video className="size-4 text-amber-500" />
      default:
        return <FileQuestion className="size-4 text-muted-foreground" />
    }
  }

  // Minimal asset object for full modal preview
  const asAsset: Asset = {
    id: result.asset_id,
    filename: result.filename,
    content_type: result.content_type,
    byte_size: 0,
    content_hash: '',
    state: 'ready',
    duration_seconds: null,
    page_count: null,
    created_at: new Date().toISOString(),
    active_generation_id: result.generation_id,
  }

  const handlePlayTimestamp = (seconds: number) => {
    if (mediaRef.current) {
      mediaRef.current.currentTime = seconds
      mediaRef.current.play().catch(() => {})
    } else {
      onPreviewAsset(asAsset, seconds)
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-2xs transition-shadow hover:shadow-xs">
      {/* Asset Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-muted/30 px-5 py-3.5">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-background shadow-2xs">
            {renderTypeIcon()}
          </div>

          <div className="min-w-0">
            <h3
              className="cursor-pointer truncate text-sm font-bold text-foreground transition-colors hover:text-primary"
              onClick={() => onPreviewAsset(asAsset)}
              title={result.filename}
            >
              {result.filename}
            </h3>
            <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
              <span>{result.content_type}</span>
              <span>&bull;</span>
              <span title={`Generation ${result.generation_id}`}>
                gen: {result.generation_id.slice(0, 8)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Prominent Fused Score Badge */}
          <div className="flex items-center gap-2 rounded-lg border border-primary/25 bg-primary/10 px-3 py-1.5 shadow-2xs">
            <span className="text-[10px] font-bold tracking-wider text-muted-foreground uppercase">
              Fused Score
            </span>
            <span className="font-mono text-base font-extrabold text-primary sm:text-lg">
              {formatScore(result.score)}
            </span>
          </div>

          <Button
            variant="outline"
            size="xs"
            onClick={() => setShowInlinePreview((prev) => !prev)}
            className="gap-1 text-xs"
          >
            {showInlinePreview ? (
              <>
                <ChevronUp className="size-3" /> Hide Preview
              </>
            ) : (
              <>
                <ChevronDown className="size-3" /> Show Preview
              </>
            )}
          </Button>

          <Button
            variant="outline"
            size="xs"
            onClick={() => onPreviewAsset(asAsset)}
            className="gap-1 text-xs"
            title="Open modal preview"
          >
            <Eye className="size-3" />
            Modal
          </Button>
        </div>
      </div>

      {/* Inline Preview Section (Rendered by default) */}
      {showInlinePreview && (
        <div className="border-b border-border/50 bg-muted/15 p-4 animate-in fade-in-50 duration-200">
          <div className="flex flex-col items-center justify-center overflow-hidden rounded-lg border border-border/80 bg-background/90 p-2">
            {category === 'image' ? (
              <div className="group relative flex max-h-80 w-full items-center justify-center overflow-hidden rounded bg-black/5 dark:bg-black/20">
                <img
                  src={contentUrl}
                  alt={result.filename}
                  className="max-h-72 w-auto rounded object-contain transition-transform group-hover:scale-[1.01]"
                  loading="lazy"
                />
              </div>
            ) : category === 'video' ? (
              <div className="w-full">
                <video
                  ref={(el) => {
                    mediaRef.current = el
                  }}
                  src={contentUrl}
                  controls
                  preload="metadata"
                  className="max-h-80 w-full rounded bg-black object-contain"
                >
                  Your browser does not support HTML5 video.
                </video>
              </div>
            ) : category === 'audio' ? (
              <div className="flex w-full flex-col items-center gap-2 p-3">
                <audio
                  ref={(el) => {
                    mediaRef.current = el
                  }}
                  src={contentUrl}
                  controls
                  className="w-full max-w-md"
                >
                  Your browser does not support HTML5 audio.
                </audio>
              </div>
            ) : result.content_type === 'application/pdf' ? (
              <div className="h-72 w-full">
                <iframe
                  src={`${contentUrl}#view=FitH`}
                  title={result.filename}
                  className="h-full w-full rounded border-0"
                />
              </div>
            ) : (
              <div className="flex items-center justify-between w-full p-2 text-xs text-muted-foreground">
                <span className="truncate max-w-md">
                  Original source document: <strong className="text-foreground">{result.filename}</strong>
                </span>
                <Button size="xs" variant="outline" asChild>
                  <a href={contentUrl} download={result.filename}>
                    <Download className="size-3 mr-1" /> Download
                  </a>
                </Button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Matches List */}
      <div className="space-y-3 p-5">
        <div className="flex items-center justify-between text-xs font-semibold tracking-wider text-muted-foreground uppercase">
          <span>Matching Passages &amp; Moments ({result.matches.length})</span>
        </div>

        <div className="space-y-2.5">
          {result.matches.map((match, mIdx) => (
            <MatchItem
              key={mIdx}
              match={match}
              index={mIdx}
              onPlayTimestamp={handlePlayTimestamp}
              onOpenSource={() => onPreviewAsset(asAsset)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
