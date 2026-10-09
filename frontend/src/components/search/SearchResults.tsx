import * as React from 'react'
import {
  Search,
  Loader2,
  Info,
  Clock,
  Layers,
  FileQuestion,
  AlertCircle,
  LayoutGrid,
  List,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SearchResultCard } from '@/components/search/SearchResultCard'
import { SearchResultGridCard } from '@/components/search/SearchResultGridCard'
import { formatDuration } from '@/lib/formatters'
import type { SearchResponse, Asset } from '@/types/api'

interface SearchResultsProps {
  response: SearchResponse | null
  loading: boolean
  error: string | null
  hasSearched: boolean
  onPreviewAsset: (asset: Asset, initialSeek?: number | null) => void
}

export function SearchResults({
  response,
  loading,
  error,
  hasSearched,
  onPreviewAsset,
}: SearchResultsProps) {
  const [viewMode, setViewMode] = React.useState<'grid' | 'list'>('grid')
  const [showQueryDetails, setShowQueryDetails] = React.useState(false)

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex animate-pulse items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin text-primary" />
          <span>Searching cross-modal embeddings and vector indexes...</span>
        </div>

        {/* Skeleton cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <div
              key={n}
              className="animate-pulse space-y-3 rounded-xl border border-border bg-card p-4"
            >
              <div className="aspect-16/10 w-full rounded-lg bg-muted/60" />
              <div className="h-4 w-3/4 rounded bg-muted" />
              <div className="h-3 w-1/2 rounded bg-muted/50" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-2 rounded-xl border border-destructive/20 bg-destructive/10 p-6 text-destructive">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <AlertCircle className="size-4" />
          <span>Search Request Failed</span>
        </div>
        <p className="text-xs leading-relaxed">{error}</p>
        <p className="text-[11px] text-destructive/80">
          Your search terms, attached query media, and weights have been
          preserved. Adjust them and try again.
        </p>
      </div>
    )
  }

  if (!hasSearched || !response) {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/80 bg-card/40 p-12 text-center">
        <div className="flex size-14 items-center justify-center rounded-2xl bg-muted/60 text-muted-foreground shadow-inner">
          <Search className="size-7" />
        </div>
        <h3 className="mt-4 text-base font-bold text-foreground">
          Ready for Multimodal Discovery
        </h3>
        <p className="mt-1.5 max-w-md text-xs leading-relaxed text-muted-foreground">
          Search with text, upload images to find visual matches, or attach
          audio/video to locate specific spoken phrases and scenes using hybrid
          vector embeddings.
        </p>
      </div>
    )
  }

  const results = response.results || []
  const hasQueryDetails =
    Boolean(response.transcript) ||
    response.query_duration_seconds !== undefined ||
    Boolean(response.pooled_modalities && response.pooled_modalities.length > 0)

  return (
    <div className="space-y-5">
      {/* Hidden-by-default Query Analysis (transcript and file details) */}
      {hasQueryDetails && (
        <div>
          <button
            type="button"
            onClick={() => setShowQueryDetails((prev) => !prev)}
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <Info className="size-3 text-muted-foreground" />
            <span>
              {showQueryDetails ? 'Hide' : 'View'} attached file query details &
              transcription
            </span>
            {showQueryDetails ? (
              <ChevronUp className="size-3" />
            ) : (
              <ChevronDown className="size-3" />
            )}
          </button>

          {showQueryDetails && (
            <div className="mt-2.5 animate-in space-y-2 rounded-xl border border-border/80 bg-muted/20 p-4 text-xs duration-150 fade-in-50">
              <div className="grid grid-cols-1 gap-3 text-muted-foreground sm:grid-cols-3">
                {response.query_duration_seconds !== undefined && (
                  <div className="flex items-center gap-1.5">
                    <Clock className="size-3 text-muted-foreground" />
                    <span>
                      Duration:{' '}
                      <strong className="text-foreground">
                        {formatDuration(response.query_duration_seconds)}
                      </strong>
                    </span>
                  </div>
                )}

                {response.query_window_count !== undefined && (
                  <div className="flex items-center gap-1.5">
                    <Layers className="size-3 text-muted-foreground" />
                    <span>
                      Windows:{' '}
                      <strong className="text-foreground">
                        {response.query_window_count}
                      </strong>
                    </span>
                  </div>
                )}

                {response.pooled_modalities &&
                  response.pooled_modalities.length > 0 && (
                    <div>
                      <span>Modalities: </span>
                      <strong className="text-foreground capitalize">
                        {response.pooled_modalities.join(', ')}
                      </strong>
                    </div>
                  )}
              </div>

              {response.transcript && (
                <div className="border-t border-border/50 pt-2">
                  <span className="font-semibold text-foreground">
                    Speech Transcript:{' '}
                  </span>
                  <span className="text-foreground/90 italic">
                    &ldquo;{response.transcript}&rdquo;
                  </span>
                </div>
              )}

              {response.covered_ranges_seconds &&
                response.covered_ranges_seconds.length > 0 && (
                  <div className="text-[11px] text-muted-foreground">
                    Covered Time Ranges:{' '}
                    {response.covered_ranges_seconds
                      .map(([s, e]) => `${s.toFixed(1)}s–${e.toFixed(1)}s`)
                      .join(', ')}
                  </div>
                )}
            </div>
          )}
        </div>
      )}

      {/* Results Header with View Mode Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <span>
            Found <strong className="text-foreground">{results.length}</strong>{' '}
            matching {results.length === 1 ? 'asset' : 'assets'}
          </span>
          <span>&bull;</span>
          <span>
            Mode:{' '}
            <strong className="text-foreground capitalize">
              {response.mode}
            </strong>
          </span>
          <span>&bull;</span>
          <span>
            Vectors:{' '}
            <strong className="text-foreground capitalize">
              {response.representation_mode}
            </strong>
          </span>
        </div>

        {/* View Switcher: Media Grid vs Detailed List */}
        <div className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-0.5">
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => setViewMode('grid')}
            className={`gap-1.5 px-2.5 py-1 text-xs font-medium transition-all ${
              viewMode === 'grid'
                ? 'bg-background text-foreground shadow-2xs'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            title="Media Gallery Grid View"
          >
            <LayoutGrid className="size-3.5" />
            <span className="hidden sm:inline">Media Grid</span>
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => setViewMode('list')}
            className={`gap-1.5 px-2.5 py-1 text-xs font-medium transition-all ${
              viewMode === 'list'
                ? 'bg-background text-foreground shadow-2xs'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            title="Detailed List View"
          >
            <List className="size-3.5" />
            <span className="hidden sm:inline">Detailed List</span>
          </Button>
        </div>
      </div>

      {/* Results Rendering */}
      {results.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/50 p-12 text-center">
          <FileQuestion className="size-10 text-muted-foreground/60" />
          <h4 className="mt-3 text-sm font-semibold text-foreground">
            No matches found
          </h4>
          <p className="mt-1 max-w-sm text-xs text-muted-foreground">
            Try adjusting your query, relaxing similarity cutoffs, or switching
            between Hybrid and Semantic modes.
          </p>
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {results.map((result, index) => (
            <SearchResultGridCard
              key={result.asset_id}
              result={result}
              rank={index + 1}
              onPreviewAsset={onPreviewAsset}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          {results.map((result, index) => (
            <SearchResultCard
              key={result.asset_id}
              result={result}
              rank={index + 1}
              onPreviewAsset={onPreviewAsset}
            />
          ))}
        </div>
      )}
    </div>
  )
}
