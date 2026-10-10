import * as React from 'react'
import {
  FileText,
  Image as ImageIcon,
  Music,
  Video,
  FileQuestion,
  Eye,
  Play,
  Download,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { HighlightedText } from '@/components/search/HighlightedText'
import {
  formatDuration,
  formatTimeRange,
  getMimeCategory,
} from '@/lib/formatters'
import { getMatchPreview } from '@/lib/match-preview'
import { useWorkspaceApi } from '@/lib/workspaces'
import type { SearchResult, Asset } from '@/types/api'

interface SearchResultGridCardProps {
  result: SearchResult
  rank: number
  showMediaText: boolean
  searchQuery?: string | null
  onPreviewAsset: (asset: Asset, initialSeek?: number | null) => void
}

export function SearchResultGridCard({
  result,
  rank,
  showMediaText,
  searchQuery,
  onPreviewAsset,
}: SearchResultGridCardProps) {
  const api = useWorkspaceApi()
  const [imageError, setImageError] = React.useState(false)
  const [showCardText, setShowCardText] = React.useState<boolean | null>(null)
  const mediaRef = React.useRef<HTMLMediaElement | null>(null)

  const contentUrl = api.getAssetContentUrl(result.asset_id)
  const category = getMimeCategory(result.content_type)

  const previews = result.matches.map(getMatchPreview)
  const primarySnippet = previews.find((preview) => preview.text)?.text ?? null
  const timeMarkers =
    category === 'audio' || category === 'video'
      ? previews
          .filter(
            (preview): preview is typeof preview & { start: number } =>
              preview.start !== null
          )
          .slice(0, 4)
      : []

  const firstTimestamp = timeMarkers[0]?.start ?? null
  const [activeTimestamp, setActiveTimestamp] = React.useState<number | null>(
    firstTimestamp
  )

  // Identify whether snippet is primarily transcript, OCR, or general text
  const textRep = result.matches
    .flatMap((m) => m.representations)
    .find((r) => r.text?.trim())
  const textKindLabel =
    textRep?.kind === 'transcript'
      ? 'Transcript'
      : textRep?.kind === 'ocr'
        ? 'OCR Text'
        : 'Matched Text'

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

  const handleMediaLoaded = (e: React.SyntheticEvent<HTMLMediaElement>) => {
    if (typeof firstTimestamp === 'number' && firstTimestamp > 0) {
      e.currentTarget.currentTime = firstTimestamp
    }
  }

  const handlePlayFrom = (e: React.MouseEvent, seconds: number) => {
    e.stopPropagation()
    setActiveTimestamp(seconds)
    if (mediaRef.current) {
      mediaRef.current.currentTime = seconds
      mediaRef.current.play().catch(() => {})
    } else {
      onPreviewAsset(asAsset, seconds)
    }
  }

  const isTextVisible =
    showCardText !== null
      ? showCardText
      : showMediaText || category === 'document' || category === 'other'

  const renderBadgeIcon = () => {
    switch (category) {
      case 'image':
        return <ImageIcon className="size-3 text-emerald-400" />
      case 'video':
        return <Video className="size-3 text-amber-400" />
      case 'audio':
        return <Music className="size-3 text-sky-400" />
      case 'document':
        return <FileText className="size-3 text-sky-400" />
      default:
        return <FileQuestion className="size-3 text-muted-foreground" />
    }
  }

  return (
    <div className="group relative flex flex-col overflow-hidden rounded-xl border border-border/80 bg-card shadow-xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-md">
      {/* Visual Media Canvas */}
      <div
        className="relative flex aspect-16/10 w-full cursor-pointer items-center justify-center overflow-hidden bg-muted/40"
        onClick={() =>
          onPreviewAsset(asAsset, activeTimestamp ?? firstTimestamp)
        }
      >
        {category === 'image' && !imageError ? (
          <div className="relative h-full w-full overflow-hidden bg-black/5 dark:bg-black/30">
            <img
              src={contentUrl}
              alt={result.filename}
              loading="lazy"
              onError={() => setImageError(true)}
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
          </div>
        ) : category === 'video' ? (
          <div
            className="relative h-full w-full bg-black"
            onClick={(e) => e.stopPropagation()}
          >
            <video
              ref={(el) => {
                mediaRef.current = el
              }}
              src={contentUrl}
              preload="metadata"
              playsInline
              controls
              onLoadedMetadata={handleMediaLoaded}
              className="h-full w-full object-cover"
            />
          </div>
        ) : category === 'audio' ? (
          <div className="flex h-full w-full flex-col items-center justify-center bg-gradient-to-br from-sky-950/20 via-background to-sky-950/10 p-4 text-center">
            <div className="mb-2 flex size-12 items-center justify-center rounded-full bg-sky-500/15 text-sky-500 ring-4 ring-sky-500/10">
              <Music className="size-6" />
            </div>
            {/* Animated Waveform Bars */}
            <div className="flex items-center gap-1">
              {[40, 70, 90, 50, 80, 100, 60, 85, 45, 95, 30].map((h, i) => (
                <span
                  key={i}
                  style={{ height: `${h * 0.25}px` }}
                  className="w-1 rounded-full bg-sky-500/60 transition-all duration-300 group-hover:bg-sky-500"
                />
              ))}
            </div>
            <audio
              ref={(el) => {
                mediaRef.current = el
              }}
              src={contentUrl}
              preload="metadata"
              controls
              onLoadedMetadata={handleMediaLoaded}
              aria-label={`Play ${result.filename}`}
              className="mt-4 h-8 w-full"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center bg-muted/30 p-4 text-center">
            <div className="mb-2 flex size-12 items-center justify-center rounded-xl bg-sky-500/10 text-sky-500">
              <FileText className="size-6" />
            </div>
            <span className="font-mono text-[11px] text-muted-foreground">
              {result.content_type}
            </span>
          </div>
        )}

        {/* Top Floating Badges */}
        <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5">
          <span className="flex items-center gap-1 rounded-md bg-black/60 px-2 py-0.5 text-[10px] font-semibold text-white backdrop-blur-md">
            {renderBadgeIcon()}
            <span className="capitalize">{category}</span>
          </span>
        </div>

        {/* Result rank */}
        <div
          className="absolute top-2.5 right-2.5 flex items-center gap-1 rounded-md border border-white/20 bg-black/70 px-2 py-0.5 text-[11px] font-bold text-white shadow-xs backdrop-blur-md"
          aria-label={`Result rank ${rank}`}
          title={`Result rank ${rank}`}
        >
          <span className="font-mono">#{rank}</span>
        </div>

        {/* Hover Quick Action Buttons */}
        <div className="absolute right-2.5 bottom-2.5 flex items-center gap-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
          <Button
            size="icon-xs"
            variant="secondary"
            className="size-7 rounded-md bg-black/75 text-white shadow-md backdrop-blur-xs hover:bg-black/90"
            onClick={(e) => {
              e.stopPropagation()
              onPreviewAsset(asAsset, activeTimestamp ?? firstTimestamp)
            }}
            title="Open modal preview"
          >
            <Eye className="size-3.5" />
          </Button>
          <Button
            size="icon-xs"
            variant="secondary"
            asChild
            className="size-7 rounded-md bg-black/75 text-white shadow-md backdrop-blur-xs hover:bg-black/90"
            onClick={(e) => e.stopPropagation()}
            title="Download original file"
          >
            <a href={contentUrl} download={result.filename}>
              <Download className="size-3.5" />
            </a>
          </Button>
        </div>
      </div>

      {/* Card Content & Metadata */}
      <div className="space-y-2.5 p-3">
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <h4
              onClick={() =>
                onPreviewAsset(asAsset, activeTimestamp ?? firstTimestamp)
              }
              title={result.filename}
              className="cursor-pointer truncate text-xs font-semibold text-foreground transition-colors hover:text-primary"
            >
              {result.filename}
            </h4>
            {primarySnippet && (
              <button
                type="button"
                onClick={() =>
                  setShowCardText((prev) =>
                    prev === null ? !showMediaText : !prev
                  )
                }
                className="flex shrink-0 items-center gap-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:text-primary"
                title={`${isTextVisible ? 'Hide' : 'Show'} ${textKindLabel}`}
              >
                <span>{textKindLabel}</span>
                {isTextVisible ? (
                  <ChevronUp className="size-2.5" />
                ) : (
                  <ChevronDown className="size-2.5" />
                )}
              </button>
            )}
          </div>

          {/* Matched Snippet (OCR / Speech transcript / text) with query highlights */}
          {primarySnippet && isTextVisible ? (
            <div className="animate-in rounded-lg border border-border/60 bg-muted/30 p-2 text-[11px] leading-relaxed text-muted-foreground duration-150 fade-in-50 select-text">
              <span className="mb-0.5 block text-[9px] font-bold tracking-wider text-muted-foreground/80 uppercase">
                {textKindLabel}
              </span>
              &ldquo;
              <HighlightedText text={primarySnippet} query={searchQuery} />
              &rdquo;
            </div>
          ) : null}
        </div>

        {/* Polished Temporal Timestamps (for video and audio matches) */}
        {timeMarkers.length > 0 && (
          <div role="group" aria-label="Matching moments" className="space-y-1">
            <div className="flex flex-wrap gap-1">
              {timeMarkers.map((m, idx) => {
                const isActive = activeTimestamp === m.start
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={(e) => handlePlayFrom(e, m.start)}
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium shadow-2xs backdrop-blur-md transition-all duration-150 ${
                      isActive
                        ? 'border border-primary/70 bg-primary/20 font-semibold text-primary ring-1 ring-primary/30'
                        : 'border border-border/70 bg-secondary/70 text-secondary-foreground hover:border-primary/40 hover:bg-secondary hover:text-foreground'
                    }`}
                    title={`Jump to ${formatDuration(m.start)}`}
                  >
                    <Play
                      className={`size-2 transition-transform ${
                        isActive
                          ? 'scale-110 fill-current'
                          : 'fill-muted-foreground'
                      }`}
                    />
                    <span className="font-mono">
                      {formatTimeRange(m.start, m.end)}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
