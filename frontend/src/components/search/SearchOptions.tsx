import * as React from 'react'
import {
  SlidersHorizontal,
  RotateCcw,
  Info,
  ChevronDown,
  ChevronUp,
  FileText,
  Image as ImageIcon,
  Music,
  Video,
  Layers,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import type {
  ChannelName,
  DenseChannelName,
  SearchMode,
  RepresentationMode,
} from '@/types/api'

interface SearchOptionsProps {
  mode: SearchMode
  onChangeMode: (mode: SearchMode) => void
  representationMode: RepresentationMode
  onChangeRepresentationMode: (mode: RepresentationMode) => void
  limit: number
  onChangeLimit: (limit: number) => void
  candidateLimit: number
  onChangeCandidateLimit: (candidateLimit: number) => void
  selectedTypes: string[]
  onChangeSelectedTypes: (types: string[]) => void
  weights: Partial<Record<ChannelName, number>>
  onChangeWeights: (weights: Partial<Record<ChannelName, number>>) => void
  similarityCutoffs: Partial<Record<DenseChannelName, number>>
  onChangeSimilarityCutoffs: (
    cutoffs: Partial<Record<DenseChannelName, number>>
  ) => void
}

const ALL_CHANNELS: ChannelName[] = [
  'text',
  'transcript',
  'ocr',
  'image',
  'audio',
  'video',
  'combined',
  'lexical',
  'identifier',
  'filename',
]

const DENSE_CHANNELS: DenseChannelName[] = [
  'text',
  'transcript',
  'ocr',
  'image',
  'audio',
  'video',
  'combined',
]

const CONTENT_TYPE_PRESETS = [
  { label: 'All Media', icon: Layers, types: [] },
  {
    label: 'Images',
    icon: ImageIcon,
    types: ['image/png', 'image/jpeg', 'image/webp', 'image/tiff'],
  },
  {
    label: 'Video',
    icon: Video,
    types: ['video/mp4', 'video/quicktime', 'video/webm', 'video/x-matroska'],
  },
  {
    label: 'Audio',
    icon: Music,
    types: ['audio/wav', 'audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/x-m4a'],
  },
  {
    label: 'Documents',
    icon: FileText,
    types: [
      'application/pdf',
      'text/plain',
      'text/markdown',
      'text/html',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'text/x-python',
    ],
  },
]

export function SearchOptions({
  mode,
  onChangeMode,
  representationMode,
  onChangeRepresentationMode,
  limit,
  onChangeLimit,
  candidateLimit,
  onChangeCandidateLimit,
  selectedTypes,
  onChangeSelectedTypes,
  weights,
  onChangeWeights,
  similarityCutoffs,
  onChangeSimilarityCutoffs,
}: SearchOptionsProps) {
  const [showAdvanced, setShowAdvanced] = React.useState(false)

  const handleWeightChange = (channel: ChannelName, val: number) => {
    onChangeWeights({
      ...weights,
      [channel]: val,
    })
  }

  const handleCutoffChange = (
    channel: DenseChannelName,
    val: number | null
  ) => {
    const updated = { ...similarityCutoffs }
    if (val === null) {
      delete updated[channel]
    } else {
      updated[channel] = val
    }
    onChangeSimilarityCutoffs(updated)
  }

  const resetWeights = () => {
    onChangeWeights({})
    onChangeSimilarityCutoffs({})
  }

  const isPresetActive = (types: string[]) => {
    if (types.length === 0) return selectedTypes.length === 0
    return (
      types.length === selectedTypes.length &&
      types.every((t) => selectedTypes.includes(t))
    )
  }

  return (
    <div className="space-y-4 rounded-2xl border border-border/80 bg-card/60 p-4 shadow-xs backdrop-blur-xs">
      {/* Primary retrieval controls */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Mode Selector */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase">
            Mode:
          </span>
          <div className="inline-flex rounded-xl border border-border/80 bg-muted/40 p-1">
            {(['hybrid', 'semantic', 'keyword'] as SearchMode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => onChangeMode(m)}
                className={`rounded-lg px-3 py-1 text-xs font-semibold capitalize transition-all ${
                  mode === m
                    ? 'bg-background text-foreground shadow-xs'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>

        {/* Representation Mode */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase">
            Vectors:
          </span>
          <div className="inline-flex rounded-xl border border-border/80 bg-muted/40 p-1">
            {(['separate', 'combined', 'both'] as RepresentationMode[]).map(
              (rm) => (
                <button
                  key={rm}
                  type="button"
                  onClick={() => onChangeRepresentationMode(rm)}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold capitalize transition-all ${
                    representationMode === rm
                      ? 'bg-background text-foreground shadow-xs'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {rm}
                </button>
              )
            )}
          </div>
        </div>

        {/* Advanced Toggle */}
        <Button
          variant="outline"
          size="xs"
          onClick={() => setShowAdvanced((prev) => !prev)}
          className="ml-auto gap-1.5 rounded-lg text-xs"
        >
          <SlidersHorizontal className="size-3" />
          {showAdvanced ? 'Hide Weights' : 'Fine-Tune Weights'}
          {showAdvanced ? (
            <ChevronUp className="size-3" />
          ) : (
            <ChevronDown className="size-3" />
          )}
        </Button>
      </div>

      {representationMode === 'combined' && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-500/25 bg-amber-500/10 p-2.5 text-xs text-amber-700 dark:text-amber-400">
          <Info className="size-4 shrink-0" />
          <span>
            Combined vectors require assets reprocessed with combined
            representations. Lexical search is disabled in this mode.
          </span>
        </div>
      )}

      {/* Content Type Quick Presets */}
      <div className="flex flex-wrap items-center gap-2 border-t border-border/50 pt-3">
        <span className="mr-1 text-[11px] font-bold tracking-wider text-muted-foreground uppercase">
          Media:
        </span>
        {CONTENT_TYPE_PRESETS.map((preset) => {
          const IconComponent = preset.icon
          const active = isPresetActive(preset.types)
          return (
            <button
              key={preset.label}
              type="button"
              onClick={() => onChangeSelectedTypes(preset.types)}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all ${
                active
                  ? 'bg-primary text-primary-foreground shadow-2xs'
                  : 'border border-border/80 bg-muted/30 text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              <IconComponent className="size-3.5" />
              <span>{preset.label}</span>
            </button>
          )
        })}
      </div>

      {/* Advanced drawer: Limits, Weights, Cutoffs */}
      {showAdvanced && (
        <div className="mt-4 animate-in space-y-5 rounded-xl border border-border/80 bg-muted/20 p-4 duration-200 fade-in-50">
          {/* Limits */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="font-medium text-foreground">
                  Result Limit
                </span>
                <span className="font-mono text-muted-foreground">{limit}</span>
              </div>
              <Slider
                min={1}
                max={50}
                value={[limit]}
                onValueChange={([val]) => {
                  onChangeLimit(val)
                  if (candidateLimit < val) onChangeCandidateLimit(val)
                }}
              />
            </div>

            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="font-medium text-foreground">
                  Candidate Pool (RRF pool)
                </span>
                <span className="font-mono text-muted-foreground">
                  {candidateLimit}
                </span>
              </div>
              <Slider
                min={10}
                max={200}
                value={[candidateLimit]}
                onValueChange={([val]) => {
                  if (val >= limit) onChangeCandidateLimit(val)
                }}
              />
            </div>
          </div>

          {/* Channel Weights */}
          <div className="space-y-3 border-t border-border/60 pt-3">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-xs font-semibold tracking-wide text-foreground uppercase">
                  Channel Retrieval Weights (0.0 – 10.0)
                </h4>
                <p className="text-[11px] text-muted-foreground">
                  Multipliers applied in Reciprocal Rank Fusion. Set to 0 to
                  disable a channel.
                </p>
              </div>
              <Button
                variant="ghost"
                size="xs"
                onClick={resetWeights}
                className="gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <RotateCcw className="size-3" /> Reset Defaults
              </Button>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              {ALL_CHANNELS.map((channel) => {
                const currentWeight =
                  weights[channel] !== undefined ? weights[channel]! : 1.0
                return (
                  <div
                    key={channel}
                    className="space-y-1.5 rounded-lg border border-border/70 bg-card p-2.5 shadow-2xs"
                  >
                    <div className="flex justify-between text-[11px]">
                      <span className="font-semibold text-foreground capitalize">
                        {channel}
                      </span>
                      <span className="font-mono text-muted-foreground">
                        {currentWeight.toFixed(1)}
                      </span>
                    </div>
                    <Slider
                      min={0}
                      max={10}
                      step={0.1}
                      value={[currentWeight]}
                      onValueChange={([val]) =>
                        handleWeightChange(channel, val)
                      }
                    />
                  </div>
                )
              })}
            </div>
          </div>

          {/* Dense Similarity Cutoffs */}
          <div className="space-y-3 border-t border-border/60 pt-3">
            <div>
              <h4 className="text-xs font-semibold tracking-wide text-foreground uppercase">
                Dense Similarity Cutoffs (-1.0 to 1.0)
              </h4>
              <p className="text-[11px] text-muted-foreground">
                Optional minimum cosine similarity filter for dense
                representations.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {DENSE_CHANNELS.map((channel) => {
                const currentCutoff = similarityCutoffs[channel]
                const isSet = currentCutoff !== undefined
                return (
                  <div
                    key={channel}
                    className="space-y-1.5 rounded-lg border border-border/70 bg-card p-2.5 shadow-2xs"
                  >
                    <div className="flex justify-between text-[11px]">
                      <span className="font-semibold text-foreground capitalize">
                        {channel}
                      </span>
                      <span className="font-mono text-muted-foreground">
                        {isSet ? currentCutoff.toFixed(2) : 'None'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Slider
                        min={-1}
                        max={1}
                        step={0.05}
                        value={[isSet ? currentCutoff : 0]}
                        onValueChange={([val]) =>
                          handleCutoffChange(channel, val)
                        }
                        disabled={!isSet}
                        className={!isSet ? 'opacity-40' : ''}
                      />
                      <button
                        type="button"
                        onClick={() =>
                          handleCutoffChange(channel, isSet ? null : 0.2)
                        }
                        className="shrink-0 text-[10px] text-muted-foreground underline hover:text-foreground"
                      >
                        {isSet ? 'Clear' : 'Enable'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
