import { Settings2, Edit } from 'lucide-react'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/formatters'
import type { Profile } from '@/types/api'

interface ProfileCardProps {
  profile: Profile
  onEdit: (profile: Profile) => void
}

export function ProfileCard({ profile, onEdit }: ProfileCardProps) {
  const config = profile.config || {}
  const isAutomatic = profile.name === 'automatic'

  return (
    <Card className="overflow-hidden transition-shadow hover:shadow-xs">
      <CardHeader className="bg-muted/30 pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded bg-primary/10 text-primary">
              <Settings2 className="size-4" />
            </div>
            <div>
              <CardTitle className="text-sm font-bold">
                {profile.name}
              </CardTitle>
              <CardDescription className="font-mono text-[11px]">
                Revision {profile.revision} &bull;{' '}
                {formatDate(profile.created_at)}
              </CardDescription>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isAutomatic && (
              <Badge variant="success" className="text-[10px]">
                Default Ingestion
              </Badge>
            )}
            <Button
              variant="outline"
              size="xs"
              onClick={() => onEdit(profile)}
              className="gap-1 text-xs"
            >
              <Edit className="size-3" />
              Revise
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pt-4 text-xs">
        <div className="grid grid-cols-2 gap-2 text-muted-foreground">
          <div className="rounded border border-border/70 bg-muted/20 p-2">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase">
              Strategy
            </span>
            <div className="mt-0.5 font-medium text-foreground">
              {config.strategy || 'automatic'}
            </div>
          </div>

          <div className="rounded border border-border/70 bg-muted/20 p-2">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase">
              Media Preset
            </span>
            <div className="mt-0.5 font-medium text-foreground capitalize">
              {config.media_preset?.replace('_', ' ') || 'automatic'}
            </div>
          </div>
        </div>

        <div className="space-y-1.5 font-mono text-[11px] text-muted-foreground">
          <div className="flex justify-between">
            <span>Text Chunk Target:</span>
            <span className="text-foreground">
              {config.text_chunk_tokens || 700} tokens
            </span>
          </div>
          <div className="flex justify-between">
            <span>Text Overlap:</span>
            <span className="text-foreground">
              {config.text_overlap_tokens || 80} tokens
            </span>
          </div>
          <div className="flex justify-between">
            <span>OCR Languages:</span>
            <span className="text-foreground">
              {config.ocr_languages || 'eng'}
            </span>
          </div>

          {config.media_window_seconds && (
            <div className="flex justify-between">
              <span>Media Window:</span>
              <span className="text-foreground">
                {config.media_window_seconds}s
              </span>
            </div>
          )}
          {config.media_overlap_seconds && (
            <div className="flex justify-between">
              <span>Media Overlap:</span>
              <span className="text-foreground">
                {config.media_overlap_seconds}s
              </span>
            </div>
          )}
          {config.video_sampling_fps && (
            <div className="flex justify-between">
              <span>Video Sampling:</span>
              <span className="text-foreground">
                {config.video_sampling_fps} FPS
              </span>
            </div>
          )}
          {config.transcription_language && (
            <div className="flex justify-between">
              <span>Transcribe Lang:</span>
              <span className="text-foreground">
                {config.transcription_language}
              </span>
            </div>
          )}

          <div className="flex justify-between border-t border-border/50 pt-1">
            <span>Combined Media/Text:</span>
            <span
              className={
                config.combined_media_text
                  ? 'font-semibold text-primary'
                  : 'text-muted-foreground'
              }
            >
              {config.combined_media_text ? 'Enabled' : 'Disabled'}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
