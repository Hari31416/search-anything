import {
  Search,
  Sparkles,
  Info,
  Clock,
  Layers,
  FileQuestion,
  AlertCircle,
} from 'lucide-react'
import { SearchResultCard } from '@/components/search/SearchResultCard'
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
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="flex animate-pulse items-center gap-2 text-xs text-muted-foreground">
          <Sparkles className="size-3.5 text-primary" />
          <span>Searching vector embeddings and full-text indexes...</span>
        </div>

        {/* Skeleton cards */}
        {[1, 2, 3].map((n) => (
          <div
            key={n}
            className="animate-pulse space-y-4 rounded-xl border border-border bg-card p-5"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="size-8 rounded-lg bg-muted" />
                <div className="space-y-1.5">
                  <div className="h-4 w-48 rounded bg-muted" />
                  <div className="h-3 w-32 rounded bg-muted/60" />
                </div>
              </div>
              <div className="h-8 w-16 rounded bg-muted" />
            </div>
            <div className="h-16 w-full rounded bg-muted/40" />
          </div>
        ))}
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
          Your search terms, attached query file, and weights have been
          preserved. You may adjust them and try again.
        </p>
      </div>
    )
  }

  if (!hasSearched || !response) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/40 p-12 text-center">
        <Search className="size-10 text-muted-foreground/50" />
        <h3 className="mt-3 text-sm font-semibold text-foreground">
          Ready to Search
        </h3>
        <p className="mt-1 max-w-md text-xs text-muted-foreground">
          Enter keywords, concepts, or attach an image or audio/video recording.
          Hybrid retrieval aligns candidate spans across dense embeddings and
          text channels.
        </p>
      </div>
    )
  }

  const results = response.results || []

  return (
    <div className="space-y-6">
      {/* Media Query Preparation Metadata Banner */}
      {(response.transcript ||
        response.query_duration_seconds !== undefined ||
        response.pooled_modalities) && (
        <div className="space-y-2 rounded-xl border border-primary/20 bg-primary/5 p-4 text-xs">
          <div className="flex items-center gap-2 font-semibold text-primary">
            <Info className="size-3.5" />
            <span>Multimodal Query Analysis</span>
          </div>

          <div className="grid grid-cols-1 gap-3 text-muted-foreground sm:grid-cols-3">
            {response.query_duration_seconds !== undefined && (
              <div className="flex items-center gap-1.5">
                <Clock className="size-3 text-primary" />
                <span>
                  Query Duration:{' '}
                  <strong className="text-foreground">
                    {formatDuration(response.query_duration_seconds)}
                  </strong>
                </span>
              </div>
            )}

            {response.query_window_count !== undefined && (
              <div className="flex items-center gap-1.5">
                <Layers className="size-3 text-primary" />
                <span>
                  Query Windows:{' '}
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
            <div className="border-t border-primary/10 pt-2">
              <span className="font-semibold text-foreground">
                Query Speech Transcript:{' '}
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

      {/* Results Header */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Found <strong className="text-foreground">{results.length}</strong>{' '}
          matching {results.length === 1 ? 'asset' : 'assets'} &bull; Mode:{' '}
          <strong className="text-foreground capitalize">
            {response.mode}
          </strong>{' '}
          &bull; Vectors:{' '}
          <strong className="text-foreground capitalize">
            {response.representation_mode}
          </strong>
        </span>
      </div>

      {/* Results list */}
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
      ) : (
        <div className="space-y-4">
          {results.map((result) => (
            <SearchResultCard
              key={result.asset_id}
              result={result}
              onPreviewAsset={onPreviewAsset}
            />
          ))}
        </div>
      )}
    </div>
  )
}
