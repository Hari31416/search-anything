import * as React from 'react'
import { SearchInput } from '@/components/search/SearchInput'
import { SearchOptions } from '@/components/search/SearchOptions'
import { SearchResults } from '@/components/search/SearchResults'
import { SourcePreviewModal } from '@/components/search/SourcePreviewModal'
import { api, ApiError } from '@/lib/api'
import { getMimeCategory } from '@/lib/formatters'
import type {
  Asset,
  ChannelName,
  DenseChannelName,
  SearchMode,
  RepresentationMode,
  SearchResponse,
} from '@/types/api'

export function SearchTab() {
  const [query, setQuery] = React.useState('')
  const [queryFile, setQueryFile] = React.useState<File | null>(null)

  // Options
  const [mode, setMode] = React.useState<SearchMode>('hybrid')
  const [representationMode, setRepresentationMode] =
    React.useState<RepresentationMode>('separate')
  const [limit, setLimit] = React.useState(12)
  const [candidateLimit, setCandidateLimit] = React.useState(60)
  const [selectedTypes, setSelectedTypes] = React.useState<string[]>([])
  const [weights, setWeights] = React.useState<
    Partial<Record<ChannelName, number>>
  >({})
  const [similarityCutoffs, setSimilarityCutoffs] = React.useState<
    Partial<Record<DenseChannelName, number>>
  >({})

  // Execution state
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [response, setResponse] = React.useState<SearchResponse | null>(null)
  const [hasSearched, setHasSearched] = React.useState(false)

  // Preview state
  const [previewAsset, setPreviewAsset] = React.useState<Asset | null>(null)
  const [previewSeek, setPreviewSeek] = React.useState<number | null>(null)

  // Abort controller ref to cancel obsolete queries
  const abortControllerRef = React.useRef<AbortController | null>(null)

  const handleSearch = async () => {
    if (!query.trim() && !queryFile) return

    // Cancel in-flight search
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    setLoading(true)
    setError(null)
    setHasSearched(true)

    try {
      let result: SearchResponse

      const searchOptions = {
        mode,
        representation_mode: representationMode,
        limit,
        candidate_limit: candidateLimit,
        content_types: selectedTypes.length > 0 ? selectedTypes : null,
        weights: Object.keys(weights).length > 0 ? weights : null,
        similarity_cutoffs:
          Object.keys(similarityCutoffs).length > 0 ? similarityCutoffs : null,
      }

      if (queryFile) {
        const category = getMimeCategory(queryFile.type)
        if (category === 'image') {
          result = await api.searchImage(
            queryFile,
            {
              ...searchOptions,
              query: query.trim(),
            },
            controller.signal
          )
        } else {
          result = await api.searchMedia(
            queryFile,
            {
              ...searchOptions,
              query: query.trim(),
            },
            controller.signal
          )
        }
      } else {
        result = await api.searchText(
          {
            ...searchOptions,
            query: query.trim(),
          },
          controller.signal
        )
      }

      // Check if this request was aborted
      if (!controller.signal.aborted) {
        setResponse(result)
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // Request was intentionally superseded by a newer one
        return
      }
      if (err instanceof ApiError) {
        setError(err.details)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Search request failed')
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }

  const handleOpenPreview = (asset: Asset, initialSeek?: number | null) => {
    setPreviewAsset(asset)
    setPreviewSeek(initialSeek ?? null)
  }

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-xl font-bold tracking-tight text-foreground">
              Multimodal Search
            </h2>
            <p className="text-xs text-muted-foreground">
              Semantic vector discovery across images, videos, audio speech,
              OCR, and documents.
            </p>
          </div>
          <div className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
            <span className="inline-block size-2 animate-pulse rounded-full bg-emerald-500" />
            <span>Dense Embeddings Active</span>
          </div>
        </div>

        <SearchInput
          query={query}
          onChangeQuery={setQuery}
          queryFile={queryFile}
          onChangeQueryFile={setQueryFile}
          onSearch={handleSearch}
          loading={loading}
        />

        <SearchOptions
          mode={mode}
          onChangeMode={setMode}
          representationMode={representationMode}
          onChangeRepresentationMode={setRepresentationMode}
          limit={limit}
          onChangeLimit={setLimit}
          candidateLimit={candidateLimit}
          onChangeCandidateLimit={setCandidateLimit}
          selectedTypes={selectedTypes}
          onChangeSelectedTypes={setSelectedTypes}
          weights={weights}
          onChangeWeights={setWeights}
          similarityCutoffs={similarityCutoffs}
          onChangeSimilarityCutoffs={setSimilarityCutoffs}
        />
      </div>

      <SearchResults
        response={response}
        loading={loading}
        error={error}
        hasSearched={hasSearched}
        onPreviewAsset={handleOpenPreview}
      />

      <SourcePreviewModal
        asset={previewAsset}
        initialSeekSeconds={previewSeek}
        open={!!previewAsset}
        onOpenChange={(open) => !open && setPreviewAsset(null)}
      />
    </div>
  )
}
