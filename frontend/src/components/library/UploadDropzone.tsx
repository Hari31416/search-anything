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
  const [progress, setProgress] = React.useState<UploadProgressState | null>(null)
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
        className={`group relative flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition-all ${isDragging
            ? 'border-primary bg-primary/5'
            : 'border-border/80 bg-card hover:border-primary/50 hover:bg-muted/30'
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
          <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary transition-transform group-hover:scale-105">
            {uploading ? (
              <Loader2 className="size-6 animate-spin text-primary" />
            ) : (
              <UploadCloud className="size-6 text-primary" />
            )}
          </div>

          <div>
            <p className="text-sm font-semibold text-foreground">
              {uploading && progress
                ? progress.total > 1
                  ? `Uploading ${progress.current} of ${progress.total}: ${progress.currentFileName}...`
                  : `Uploading ${progress.currentFileName}...`
                : 'Click to select files or drag and drop multiple files'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Documents (.pdf, .docx, .txt, .md, .html, .py), Images (.png, .jpg, .webp), Audio &amp; Video
            </p>
          </div>

          <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5">
              <FileText className="size-3 text-muted-foreground" /> Docs
            </span>
            <span className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5">
              <ImageIcon className="size-3 text-muted-foreground" /> Images
            </span>
            <span className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5">
              <Music className="size-3 text-muted-foreground" /> Audio
            </span>
            <span className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5">
              <Video className="size-3 text-muted-foreground" /> Video
            </span>
          </div>
        </div>
      </div>

      {successCount > 0 && !uploading && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3 text-xs text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="size-4 shrink-0" />
          <span className="font-medium">
            Successfully uploaded {successCount} {successCount === 1 ? 'file' : 'files'} to library.
          </span>
        </div>
      )}

      {errors.length > 0 && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive space-y-1.5">
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
          <ul className="list-disc pl-5 space-y-0.5 text-[11px]">
            {errors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
