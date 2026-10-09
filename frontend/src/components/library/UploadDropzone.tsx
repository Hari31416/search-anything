import * as React from 'react'
import {
  UploadCloud,
  FileText,
  Image as ImageIcon,
  Music,
  Video,
  AlertCircle,
  Loader2,
  CheckCircle2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'
import type { UploadResponse } from '@/types/api'

interface UploadDropzoneProps {
  onUploadSuccess: (response: UploadResponse) => void
}

interface UploadProgressState {
  current: number
  total: number
  currentFileName: string
}

export function UploadDropzone({ onUploadSuccess }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = React.useState(false)
  const [uploading, setUploading] = React.useState(false)
  const [progress, setProgress] = React.useState<UploadProgressState | null>(
    null
  )
  const [errors, setErrors] = React.useState<string[]>([])
  const [successCount, setSuccessCount] = React.useState<number>(0)
  const fileInputRef = React.useRef<HTMLInputElement>(null)

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const fileList = Array.from(files)
    setErrors([])
    setSuccessCount(0)
    setUploading(true)

    const accumulatedErrors: string[] = []
    let completed = 0

    for (let i = 0; i < fileList.length; i++) {
      const file = fileList[i]
      setProgress({
        current: i + 1,
        total: fileList.length,
        currentFileName: file.name,
      })

      try {
        const res = await api.uploadAsset(file)
        onUploadSuccess(res)
        completed++
        setSuccessCount(completed)
      } catch (err) {
        let msg = `${file.name}: Upload failed`
        if (err instanceof ApiError) {
          msg = `${file.name}: ${err.details}`
        } else if (err instanceof Error) {
          msg = `${file.name}: ${err.message}`
        }
        accumulatedErrors.push(msg)
      }
    }

    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
    setErrors(accumulatedErrors)
    setUploading(false)
    setProgress(null)
  }

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const onDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    handleFiles(e.dataTransfer.files)
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => !uploading && fileInputRef.current?.click()}
        className={`group relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center transition-all duration-200 ${
          isDragging
            ? 'scale-[1.005] border-primary bg-primary/10'
            : 'border-border/80 bg-card/60 hover:border-primary/50 hover:bg-muted/30'
        } ${uploading ? 'pointer-events-none opacity-80' : ''}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          disabled={uploading}
          onChange={(e) => handleFiles(e.target.files)}
        />

        <div className="flex flex-col items-center gap-3">
          <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-inner transition-transform group-hover:scale-105">
            {uploading ? (
              <Loader2 className="size-7 animate-spin text-primary" />
            ) : (
              <UploadCloud className="size-7 text-primary" />
            )}
          </div>

          <div>
            <p className="text-sm font-bold text-foreground">
              {uploading && progress
                ? progress.total > 1
                  ? `Indexing ${progress.current} of ${progress.total}: ${progress.currentFileName}...`
                  : `Indexing ${progress.currentFileName}...`
                : 'Drop media files here or click to browse'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Images (.png, .jpg, .webp), Videos (.mp4, .webm, .mkv), Audio
              (.wav, .mp3, .m4a), and Documents
            </p>
          </div>

          <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/50 px-2.5 py-1 font-medium">
              <ImageIcon className="size-3 text-emerald-500" /> Images
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/50 px-2.5 py-1 font-medium">
              <Video className="size-3 text-amber-500" /> Videos
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/50 px-2.5 py-1 font-medium">
              <Music className="size-3 text-violet-500" /> Audio
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-muted/50 px-2.5 py-1 font-medium">
              <FileText className="size-3 text-sky-500" /> Documents
            </span>
          </div>
        </div>
      </div>

      {successCount > 0 && !uploading && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-3 text-xs text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="size-4 shrink-0" />
          <span className="font-semibold">
            Successfully uploaded {successCount}{' '}
            {successCount === 1 ? 'file' : 'files'} to library.
          </span>
        </div>
      )}

      {errors.length > 0 && (
        <div className="space-y-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3.5 text-xs text-destructive">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-semibold">
              <AlertCircle className="size-4 shrink-0" />
              <span>Upload errors ({errors.length})</span>
            </div>
            <Button
              variant="ghost"
              size="xs"
              onClick={() => setErrors([])}
              className="text-destructive hover:bg-destructive/10"
            >
              Dismiss
            </Button>
          </div>
          <ul className="list-disc space-y-0.5 pl-5 text-[11px]">
            {errors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
