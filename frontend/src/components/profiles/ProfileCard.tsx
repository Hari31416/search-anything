import { Edit } from 'lucide-react'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card'
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
  const settings = [
    ['Strategy', config.strategy || 'automatic'],
    ['Media preset', config.media_preset?.replaceAll('_', ' ') || 'automatic'],
    ['Text chunk size', `${config.text_chunk_tokens ?? 700} tokens`],
    ['Text overlap', `${config.text_overlap_tokens ?? 80} tokens`],
    ['OCR languages', config.ocr_languages || 'eng'],
    ...(config.media_window_seconds != null
      ? [['Media window', `${config.media_window_seconds}s`]]
      : []),
    ...(config.media_overlap_seconds != null
      ? [['Media overlap', `${config.media_overlap_seconds}s`]]
      : []),
    ...(config.video_sampling_fps != null
      ? [['Video sampling', `${config.video_sampling_fps} FPS`]]
      : []),
    ...(config.transcription_language
      ? [['Transcription language', config.transcription_language]]
      : []),
    [
      'Combined media and text',
      config.combined_media_text ? 'Enabled' : 'Disabled',
    ],
  ]

  return (
    <Card className="overflow-hidden rounded-2xl border-border/80 shadow-none">
      <CardHeader className="gap-4 p-5 sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 space-y-2">
            <CardTitle className="text-lg leading-snug font-semibold break-words">
              {profile.name}
            </CardTitle>
            <CardDescription className="text-xs leading-relaxed">
              Revision {profile.revision} · {formatDate(profile.created_at)}
            </CardDescription>
            {isAutomatic && (
              <p className="text-xs font-medium text-muted-foreground">
                Used for new uploads
              </p>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={() => onEdit(profile)}>
            <Edit className="size-3.5" />
            Revise
          </Button>
        </div>
        <p className="border-t border-border pt-4 text-sm leading-relaxed text-muted-foreground">
          {isAutomatic
            ? 'Revisions apply to new uploads. To update existing files, use Reprocess in the Library.'
            : 'To apply a revision to existing files, use Reprocess in the Library. New uploads use the automatic profile.'}
        </p>
      </CardHeader>
      <CardContent className="px-5 pb-5 sm:px-6 sm:pb-6">
        <dl className="divide-y divide-border/60 text-sm">
          {settings.map(([label, value]) => (
            <div
              key={label}
              className="flex justify-between gap-4 py-2.5 first:pt-0 last:pb-0"
            >
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="text-right font-medium break-words text-foreground tabular-nums">
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  )
}
