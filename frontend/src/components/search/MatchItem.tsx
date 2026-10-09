import * as React from 'react'
import {
  Clock,
  Play,
  FileText,
  ChevronDown,
  ChevronRight,
  Sparkles,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { formatScore, formatTimeRange } from '@/lib/formatters'
import type { SearchMatch, RepresentationHit } from '@/types/api'

interface MatchItemProps {
  match: SearchMatch
  index: number
  onPlayTimestamp?: (seconds: number) => void
  onOpenSource?: () => void
}

export function MatchItem({ match, index, onPlayTimestamp }: MatchItemProps) {
  const [showEvidence, setShowEvidence] = React.useState(false)

  const isTemporal = match.time_start !== null && match.time_end !== null
  const hasPage = match.representations.some(
    (r) => r.location && r.location.page !== undefined
  )
  const pageNumber = match.representations.find(
    (r) => r.location && r.location.page !== undefined
  )?.location.page

  // Extract best text from representations (prioritizing non-empty text)
  const primaryText =
    match.representations.find((r) => r.text && r.text.trim().length > 0)
      ?.text || null

  return (
    <div className="space-y-2.5 rounded-lg border border-border/70 bg-card/60 p-3.5 transition-all hover:border-primary/40">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="font-mono text-[10px]">
            Match #{index + 1}
          </Badge>

          {isTemporal ? (
            <div className="flex items-center gap-1.5 rounded-full bg-violet-500/10 px-2.5 py-0.5 text-xs font-medium text-violet-600 dark:text-violet-400">
              <Clock className="size-3" />
              <span>{formatTimeRange(match.time_start, match.time_end)}</span>
              {onPlayTimestamp && match.time_start !== null && (
                <button
                  type="button"
                  onClick={() => onPlayTimestamp(match.time_start!)}
                  className="ml-1 flex items-center gap-0.5 rounded px-1 text-[10px] font-semibold hover:bg-violet-500/20"
                  title="Play from this moment"
                >
                  <Play className="size-2.5 fill-current" /> Play
                </button>
              )}
            </div>
          ) : hasPage ? (
            <div className="flex items-center gap-1 rounded bg-sky-500/10 px-2 py-0.5 text-xs text-sky-600 dark:text-sky-400">
              <FileText className="size-3" />
              <span>Page {String(pageNumber)}</span>
            </div>
          ) : null}

          {match.source_start !== null &&
            match.source_end !== null &&
            !isTemporal &&
            !hasPage && (
              <span className="font-mono text-[10px] text-muted-foreground">
                offsets {match.source_start}–{match.source_end}
              </span>
            )}
        </div>

        <div className="flex items-center gap-1.5 rounded-md border border-border/80 bg-muted/50 px-2.5 py-1">
          <span className="text-[10px] font-semibold text-muted-foreground uppercase">Rank Score</span>
          <span className="font-mono text-xs font-bold text-foreground">
            {formatScore(match.score)}
          </span>
        </div>
      </div>

      {/* Matched text rendered safely */}
      {primaryText ? (
        <div className="rounded-md bg-muted/40 p-2.5 font-sans text-xs leading-relaxed text-foreground select-text">
          &ldquo;{primaryText}&rdquo;
        </div>
      ) : (
        <div className="text-xs text-muted-foreground italic">
          Visual or acoustic match without direct transcript/OCR text
        </div>
      )}

      {/* Channel contribution badges */}
      <div className="flex flex-wrap items-center gap-1 text-[10px]">
        <span className="mr-1 text-muted-foreground">Channels:</span>
        {Object.entries(match.channels).map(([channel, contrib]) => (
          <span
            key={channel}
            className="inline-flex items-center gap-1 rounded bg-secondary px-2 py-0.5 font-medium text-secondary-foreground"
          >
            <Sparkles className="size-2.5 text-primary" />
            <span className="capitalize">{channel}</span>
            <span className="font-mono text-[9px] text-muted-foreground">
              +{contrib.toFixed(3)}
            </span>
          </span>
        ))}
      </div>

      {/* Evidence expansion */}
      <div>
        <button
          type="button"
          onClick={() => setShowEvidence((prev) => !prev)}
          className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground"
        >
          {showEvidence ? (
            <ChevronDown className="size-3" />
          ) : (
            <ChevronRight className="size-3" />
          )}
          <span>
            {showEvidence ? 'Hide' : 'Show'} raw ranking details &
            representations
          </span>
        </button>

        {showEvidence && (
          <div className="mt-2.5 animate-in space-y-2 rounded-md border border-border/80 bg-background/80 p-3 text-xs duration-150 fade-in-50">
            {/* Representations details */}
            <div className="space-y-1.5">
              <span className="text-[10px] font-bold tracking-wider text-muted-foreground uppercase">
                Representations ({match.representations.length})
              </span>
              <div className="space-y-1.5">
                {match.representations.map(
                  (rep: RepresentationHit, rIdx: number) => (
                    <div
                      key={rIdx}
                      className="space-y-1 rounded border border-border/60 bg-muted/20 p-2 text-[11px]"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-semibold text-primary uppercase">
                          Kind: {rep.kind}
                        </span>
                        {rep.similarity !== null && (
                          <span className="font-mono text-[10px] text-muted-foreground">
                            similarity: {rep.similarity.toFixed(4)}
                          </span>
                        )}
                      </div>
                      {rep.location && Object.keys(rep.location).length > 0 && (
                        <div className="truncate font-mono text-[10px] text-muted-foreground">
                          loc: {JSON.stringify(rep.location)}
                        </div>
                      )}
                    </div>
                  )
                )}
              </div>
            </div>

            {/* Channel evidence map */}
            {match.channel_evidence &&
              Object.keys(match.channel_evidence).length > 0 && (
                <div className="space-y-1 border-t border-border/50 pt-2">
                  <span className="text-[10px] font-bold tracking-wider text-muted-foreground uppercase">
                    Channel Evidence Map
                  </span>
                  <div className="grid grid-cols-2 gap-2 font-mono text-[11px] text-muted-foreground">
                    {Object.entries(match.channel_evidence).map(([ch, ev]) => (
                      <div key={ch} className="rounded bg-muted/40 p-1.5">
                        <div className="font-semibold text-foreground capitalize">
                          {ch}
                        </div>
                        <div>contrib: +{ev.contribution.toFixed(4)}</div>
                        {ev.similarity !== null && (
                          <div>sim: {ev.similarity.toFixed(4)}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
          </div>
        )}
      </div>
    </div>
  )
}
