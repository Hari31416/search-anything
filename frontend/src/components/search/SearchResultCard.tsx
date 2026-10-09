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
import { getMimeCategory } from '@/lib/formatters'
import { useWorkspaceApi } from '@/lib/workspaces'
import type { SearchResult, Asset } from '@/types/api'

interface SearchResultCardProps {
  result: SearchResult
  rank: number
  showMediaText: boolean
  onPreviewAsset: (assetSummary: Asset, initialSeek?: number | null) => void
}

export function SearchResultCard({
  result,
  rank,
  showMediaText,
  onPreviewAsset,
}: SearchResultCardProps) {
  const api = useWorkspaceApi()
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
        return <Music className="size-4 text-sky-500" />
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
    <div className="overflow-hidden rounded-xl border border-border/80 bg-card shadow-xs transition-all duration-200 hover:border-border hover:shadow-md">
      {/* Asset Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-muted/20 px-5 py-3.5">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border/60 bg-background shadow-2xs">
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
              <span className="capitalize">{category}</span>
              <span>&bull;</span>
              <span>{result.content_type}</span>
              <span>&bull;</span>
              <span title={`Generation ${result.generation_id}`}>
                gen: {result.generation_id.slice(0, 8)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Result rank */}
          <div
            className="flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 shadow-2xs"
            aria-label={`Result rank ${rank}`}
          >
            <div className="flex flex-col">
              <span className="text-[9px] leading-none font-bold tracking-wider text-muted-foreground uppercase">
                Rank
              </span>
              <span className="font-mono text-sm leading-tight font-extrabold text-primary sm:text-base">
                #{rank}
              </span>
            </div>
          </div>

          <Button
            variant="outline"
            size="xs"
            onClick={() => setShowInlinePreview((prev) => !prev)}
            className="gap-1 text-xs"
          >
            {showInlinePreview ? (
              <>
                <ChevronUp className="size-3" /> Hide Media
              </>
            ) : (
              <>
                <ChevronDown className="size-3" /> Show Media
              </>
            )}
          </Button>

          <Button
            variant="outline"
            size="xs"
            onClick={() => onPreviewAsset(asAsset)}
            className="gap-1 text-xs"
            title="Open theater modal preview"
          >
            <Eye className="size-3" />
            Theater View
          </Button>

          <Button variant="ghost" size="icon-xs" asChild title="Download file">
            <a href={contentUrl} download={result.filename}>
              <Download className="size-3.5 text-muted-foreground" />
            </a>
          </Button>
        </div>
      </div>

      {/* Prominent Media Display Section */}
      {showInlinePreview && (
        <div className="animate-in border-b border-border/50 bg-black/5 p-4 duration-200 fade-in-50 dark:bg-black/30">
          <div className="flex flex-col items-center justify-center overflow-hidden rounded-xl border border-border/70 bg-background/80 shadow-inner">
            {category === 'image' ? (
              <div
                className="group relative flex max-h-96 w-full cursor-pointer items-center justify-center overflow-hidden bg-black/10 p-2 dark:bg-black/40"
                onClick={() => onPreviewAsset(asAsset)}
              >
                <img
                  src={contentUrl}
                  alt={result.filename}
                  className="max-h-80 w-auto rounded-lg object-contain transition-transform duration-300 group-hover:scale-[1.02]"
                  loading="lazy"
                />
                <div className="absolute inset-0 flex items-center justify-center bg-black/20 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                  <span className="flex items-center gap-1.5 rounded-full bg-black/70 px-3 py-1 text-xs font-medium text-white backdrop-blur-xs">
                    <Eye className="size-3.5" /> Click for Theater View
                  </span>
                </div>
              </div>
            ) : category === 'video' ? (
              <div className="w-full bg-black p-2">
                <video
                  ref={(el) => {
                    mediaRef.current = el
                  }}
                  src={contentUrl}
                  controls
                  preload="metadata"
                  className="max-h-96 w-full rounded-lg bg-black object-contain shadow-md"
                >
                  Your browser does not support HTML5 video.
                </video>
              </div>
            ) : category === 'audio' ? (
              <div className="flex w-full flex-col items-center gap-3 bg-gradient-to-r from-sky-950/15 via-background to-sky-950/15 p-6">
                <div className="flex items-center gap-3">
                  <div className="flex size-11 items-center justify-center rounded-full bg-sky-500/15 text-sky-500">
                    <Music className="size-5" />
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-foreground">
                      {result.filename}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      Audio Stream &bull; Select matched moments below to jump
                      to timestamp
                    </p>
                  </div>
                </div>
                <audio
                  ref={(el) => {
                    mediaRef.current = el
                  }}
                  src={contentUrl}
                  controls
                  className="w-full max-w-xl"
                >
                  Your browser does not support HTML5 audio.
                </audio>
              </div>
            ) : result.content_type === 'application/pdf' ? (
              <div className="h-80 w-full">
                <iframe
                  src={`${contentUrl}#view=FitH`}
                  title={result.filename}
                  className="h-full w-full rounded-lg border-0"
                />
              </div>
            ) : (
              <div className="flex w-full items-center justify-between p-4 text-xs text-muted-foreground">
                <span className="max-w-md truncate">
                  Source document:{' '}
                  <strong className="text-foreground">{result.filename}</strong>
                </span>
                <Button size="xs" variant="outline" asChild>
                  <a href={contentUrl} download={result.filename}>
                    <Download className="mr-1 size-3" /> Download
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
          <span>Matching Moments &amp; Passages ({result.matches.length})</span>
        </div>

        <div className="space-y-2.5">
          {result.matches.map((match, mIdx) => (
            <MatchItem
              key={mIdx}
              match={match}
              index={mIdx}
              showText={
                showMediaText || category === 'document' || category === 'other'
              }
              onPlayTimestamp={handlePlayTimestamp}
              onOpenSource={() => onPreviewAsset(asAsset)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
