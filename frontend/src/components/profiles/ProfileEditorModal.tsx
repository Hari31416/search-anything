import * as React from 'react'
import { Settings2, Loader2, Info, AlertCircle } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { api, ApiError } from '@/lib/api'
import type { IngestionOptions, MediaPreset, Profile } from '@/types/api'

interface ProfileEditorModalProps {
  initialProfile?: Profile | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess: () => void
}

const PRESET_DESCRIPTIONS: Record<MediaPreset, string> = {
  automatic:
    'Detects audio/video structure dynamically (speech defaults to 30s speech windows, video to 8s/1fps)',
  speech_lectures:
    'Optimized for spoken audio/dialogue; uses speech chunking with Whisper transcription',
  general_video:
    'Balanced audio and video frame sampling for general clips and presentation recordings',
  music_sounds:
    'Dense audio windows prioritizing acoustic and musical features over speech',
  camera_footage:
    'Higher frame sampling rate for CCTV or dashcam video with minimal audio',
}

export function ProfileEditorModal({
  initialProfile,
  open,
  onOpenChange,
  onSuccess,
}: ProfileEditorModalProps) {
  const [name, setName] = React.useState('custom_profile')
  const [mediaPreset, setMediaPreset] = React.useState<MediaPreset>('automatic')
  const [textChunkTokens, setTextChunkTokens] = React.useState(700)
  const [textOverlapTokens, setTextOverlapTokens] = React.useState(80)
  const [mediaWindowSeconds, setMediaWindowSeconds] = React.useState<string>('')
  const [mediaOverlapSeconds, setMediaOverlapSeconds] =
    React.useState<string>('')
  const [videoSamplingFps, setVideoSamplingFps] = React.useState<string>('')
  const [ocrLanguages, setOcrLanguages] = React.useState('eng')
  const [transcriptionLanguage, setTranscriptionLanguage] = React.useState('')
  const [combinedMediaText, setCombinedMediaText] = React.useState(false)

  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (initialProfile) {
      setName(initialProfile.name)
      const cfg = initialProfile.config || {}
      setMediaPreset(cfg.media_preset || 'automatic')
      setTextChunkTokens(cfg.text_chunk_tokens || 700)
      setTextOverlapTokens(cfg.text_overlap_tokens || 80)
      setMediaWindowSeconds(
        cfg.media_window_seconds ? String(cfg.media_window_seconds) : ''
      )
      setMediaOverlapSeconds(
        cfg.media_overlap_seconds ? String(cfg.media_overlap_seconds) : ''
      )
      setVideoSamplingFps(
        cfg.video_sampling_fps ? String(cfg.video_sampling_fps) : ''
      )
      setOcrLanguages(cfg.ocr_languages || 'eng')
      setTranscriptionLanguage(cfg.transcription_language || '')
      setCombinedMediaText(!!cfg.combined_media_text)
    } else {
      setName('custom_profile')
      setMediaPreset('automatic')
      setTextChunkTokens(700)
      setTextOverlapTokens(80)
      setMediaWindowSeconds('')
      setMediaOverlapSeconds('')
      setVideoSamplingFps('')
      setOcrLanguages('eng')
      setTranscriptionLanguage('')
      setCombinedMediaText(false)
    }
    setError(null)
  }, [initialProfile, open])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    // Client-side validations matching Pydantic rules
    const cleanName = name.trim()
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$/.test(cleanName)) {
      setError(
        'Profile name must start with alphanumeric character and contain only letters, numbers, underscores, or hyphens (up to 120 chars).'
      )
      return
    }

    if (textOverlapTokens >= textChunkTokens) {
      setError(
        'Text overlap tokens must be strictly smaller than the text chunk target.'
      )
      return
    }

    if (!/^[A-Za-z0-9_+.-]+$/.test(ocrLanguages.trim())) {
      setError(
        'OCR languages list contains invalid characters. Use formats like "eng" or "eng+fra".'
      )
      return
    }

    const windowSec = mediaWindowSeconds.trim()
      ? parseFloat(mediaWindowSeconds)
      : null
    const overlapSec = mediaOverlapSeconds.trim()
      ? parseFloat(mediaOverlapSeconds)
      : null

    if (windowSec !== null && overlapSec !== null && overlapSec >= windowSec) {
      setError(
        'Media overlap seconds must be strictly smaller than the media window.'
      )
      return
    }

    const fps = videoSamplingFps.trim() ? parseFloat(videoSamplingFps) : null

    const options: IngestionOptions = {
      strategy: 'automatic',
      version: 1,
      media_preset: mediaPreset,
      text_chunk_tokens: textChunkTokens,
      text_overlap_tokens: textOverlapTokens,
      ocr_languages: ocrLanguages.trim(),
      combined_media_text: combinedMediaText,
      media_window_seconds: windowSec,
      media_overlap_seconds: overlapSec,
      video_sampling_fps: fps,
      transcription_language: transcriptionLanguage.trim() || null,
    }

    setSubmitting(true)
    try {
      await api.saveProfile(cleanName, options)
      onSuccess()
      onOpenChange(false)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.details)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to save profile revision')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="size-4 text-primary" />
            {initialProfile
              ? `Revise Profile "${initialProfile.name}"`
              : 'Create Ingestion Profile'}
          </DialogTitle>
          <DialogDescription className="text-xs">
            Profiles define how uploaded files are segmented, sampled, and
            indexed.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 py-2 text-xs">
          <div className="flex gap-2 rounded-md border border-border/80 bg-muted/40 p-3 text-xs text-muted-foreground">
            <Info className="size-4 shrink-0 text-primary" />
            <span>
              Profiles are immutable. Saving with an existing name creates a new
              incremented revision. Library uploads default to the latest{' '}
              <code>automatic</code> revision.
            </span>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-2.5 text-xs text-destructive">
              <AlertCircle className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Profile Name */}
          <div className="space-y-1">
            <label className="font-semibold text-foreground">
              Profile Name
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={submitting}
              placeholder="e.g. automatic, speech_focus, dense_video"
              required
            />
          </div>

          {/* Media Preset */}
          <div className="space-y-1">
            <label className="font-semibold text-foreground">
              Media Preset
            </label>
            <select
              value={mediaPreset}
              onChange={(e) => setMediaPreset(e.target.value as MediaPreset)}
              disabled={submitting}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-xs shadow-xs focus:ring-1 focus:ring-ring focus:outline-none"
            >
              <option value="automatic">automatic</option>
              <option value="speech_lectures">speech_lectures</option>
              <option value="general_video">general_video</option>
              <option value="music_sounds">music_sounds</option>
              <option value="camera_footage">camera_footage</option>
            </select>
            <p className="text-[11px] text-muted-foreground">
              {PRESET_DESCRIPTIONS[mediaPreset]}
            </p>
          </div>

          {/* Text Segmentation */}
          <div className="grid grid-cols-2 gap-3 border-t border-border/60 pt-2">
            <div className="space-y-1">
              <label className="font-semibold text-foreground">
                Text Chunk Tokens
              </label>
              <Input
                type="number"
                min={64}
                max={4096}
                value={textChunkTokens}
                onChange={(e) =>
                  setTextChunkTokens(parseInt(e.target.value) || 700)
                }
                disabled={submitting}
              />
              <span className="text-[10px] text-muted-foreground">
                Target tokens (64 – 4096)
              </span>
            </div>

            <div className="space-y-1">
              <label className="font-semibold text-foreground">
                Text Overlap Tokens
              </label>
              <Input
                type="number"
                min={0}
                max={512}
                value={textOverlapTokens}
                onChange={(e) =>
                  setTextOverlapTokens(parseInt(e.target.value) || 0)
                }
                disabled={submitting}
              />
              <span className="text-[10px] text-muted-foreground">
                Must be &lt; chunk tokens
              </span>
            </div>
          </div>

          {/* Media Window Overrides */}
          <div className="grid grid-cols-3 gap-3 border-t border-border/60 pt-2">
            <div className="space-y-1">
              <label className="font-semibold text-foreground">
                Media Window (s)
              </label>
              <Input
                type="number"
                step="any"
                min={1}
                max={300}
                placeholder="Default"
                value={mediaWindowSeconds}
                onChange={(e) => setMediaWindowSeconds(e.target.value)}
                disabled={submitting}
              />
              <span className="text-[10px] text-muted-foreground">
                1 – 300s (optional)
              </span>
            </div>

            <div className="space-y-1">
              <label className="font-semibold text-foreground">
                Media Overlap (s)
              </label>
              <Input
                type="number"
                step="any"
                min={0}
                max={29}
                placeholder="Default"
                value={mediaOverlapSeconds}
                onChange={(e) => setMediaOverlapSeconds(e.target.value)}
                disabled={submitting}
              />
              <span className="text-[10px] text-muted-foreground">
                0 – 29s (optional)
              </span>
            </div>

            <div className="space-y-1">
              <label className="font-semibold text-foreground">Video FPS</label>
              <Input
                type="number"
                step="any"
                min={0.05}
                max={30}
                placeholder="Default"
                value={videoSamplingFps}
                onChange={(e) => setVideoSamplingFps(e.target.value)}
                disabled={submitting}
              />
              <span className="text-[10px] text-muted-foreground">
                0.05 – 30 (optional)
              </span>
            </div>
          </div>

          {/* OCR & Transcription */}
          <div className="grid grid-cols-2 gap-3 border-t border-border/60 pt-2">
            <div className="space-y-1">
              <label className="font-semibold text-foreground">
                OCR Languages
              </label>
              <Input
                value={ocrLanguages}
                onChange={(e) => setOcrLanguages(e.target.value)}
                disabled={submitting}
                placeholder="eng"
              />
              <span className="text-[10px] text-muted-foreground">
                e.g. &quot;eng&quot;, &quot;eng+fra&quot;
              </span>
            </div>

            <div className="space-y-1">
              <label className="font-semibold text-foreground">
                Transcribe Language
              </label>
              <Input
                value={transcriptionLanguage}
                onChange={(e) => setTranscriptionLanguage(e.target.value)}
                disabled={submitting}
                placeholder="Leave blank for auto"
              />
              <span className="text-[10px] text-muted-foreground">
                e.g. &quot;en&quot; (optional)
              </span>
            </div>
          </div>

          {/* Combined media text switch */}
          <div className="flex items-center justify-between rounded-lg border border-t border-border/60 border-border/80 bg-muted/20 p-3 pt-2">
            <div className="space-y-0.5">
              <label className="font-semibold text-foreground">
                Index Combined Media/Text
              </label>
              <p className="text-[11px] text-muted-foreground">
                Generates multimodal combined embeddings for aligned media and
                transcript/OCR passages.
              </p>
            </div>
            <Switch
              checked={combinedMediaText}
              onCheckedChange={setCombinedMediaText}
              disabled={submitting}
            />
          </div>

          <DialogFooter className="pt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={submitting}
              className="gap-1.5"
            >
              {submitting && <Loader2 className="size-3.5 animate-spin" />}
              Save Profile Revision
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
