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

  // Options & Settings
  const [showSettings, setShowSettings] = React.useState(false)
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

  const hasCustomSettings =
    mode !== 'hybrid' ||
    representationMode !== 'separate' ||
    selectedTypes.length > 0 ||
    Object.keys(weights).length > 0 ||
    Object.keys(similarityCutoffs).length > 0

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
    <div className="space-y-8">
      {/* Centered, restrained search container */}
      <div className="mx-auto w-full max-w-2xl space-y-3 pt-2 sm:pt-4">
        <SearchInput
          query={query}
          onChangeQuery={setQuery}
          queryFile={queryFile}
          onChangeQueryFile={setQueryFile}
          onSearch={handleSearch}
          loading={loading}
          showSettings={showSettings}
          onToggleSettings={() => setShowSettings((prev) => !prev)}
          hasCustomSettings={hasCustomSettings}
        />

        {showSettings && (
          <div className="animate-in duration-200 fade-in-50">
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
        )}
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
