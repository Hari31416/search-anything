import * as React from 'react'
import {
  Search,
  Paperclip,
  Image as ImageIcon,
  Video,
  Music,
  X,
  AlertTriangle,
  Loader2,
  Sparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { formatBytes, getMimeCategory } from '@/lib/formatters'

interface SearchInputProps {
  query: string
  onChangeQuery: (query: string) => void
  queryFile: File | null
  onChangeQueryFile: (file: File | null) => void
  onSearch: () => void
  loading: boolean
}

const MAX_IMAGE_BYTES = 8 * 1024 * 1024
const MAX_MEDIA_BYTES = 16 * 1024 * 1024

const SUGGESTIONS = [
  'Diagrams and schematics',
  'Presentation slides',
  'Podcast interview',
  'Nature and landscape',
  'Financial statements',
]

export function SearchInput({
  query,
  onChangeQuery,
  queryFile,
  onChangeQueryFile,
  onSearch,
  loading,
}: SearchInputProps) {
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const [fileWarning, setFileWarning] = React.useState<string | null>(null)
  const [isDragOver, setIsDragOver] = React.useState(false)
  const [imagePreviewUrl, setImagePreviewUrl] = React.useState<string | null>(
    null
  )

  // Generate thumbnail URL when image file is attached
  React.useEffect(() => {
    if (queryFile && getMimeCategory(queryFile.type) === 'image') {
      const url = URL.createObjectURL(queryFile)
      setImagePreviewUrl(url)
      return () => {
        URL.revokeObjectURL(url)
      }
    } else {
      setImagePreviewUrl(null)
    }
  }, [queryFile])

  const handleProcessFile = (file: File) => {
    setFileWarning(null)
    const category = getMimeCategory(file.type)

    if (category === 'image') {
      if (file.size > MAX_IMAGE_BYTES) {
        setFileWarning(
          `Image queries are limited to 8 MiB (selected file is ${formatBytes(file.size)}).`
        )
        return
      }
    } else if (category === 'audio' || category === 'video') {
      if (file.size > MAX_MEDIA_BYTES) {
        setFileWarning(
          `Audio/Video queries are limited to 16 MiB (selected file is ${formatBytes(file.size)}).`
        )
        return
      }
    } else {
      setFileWarning(
        'Unsupported query attachment format. Attach an image (.png, .jpg, .webp) or audio/video file.'
      )
      return
    }

    onChangeQueryFile(file)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleFileSelect = (files: FileList | null) => {
    if (!files || files.length === 0) return
    handleProcessFile(files[0])
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      onSearch()
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragOver(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleProcessFile(e.dataTransfer.files[0])
    }
  }

  const renderFileIcon = (file: File) => {
    const cat = getMimeCategory(file.type)
    if (cat === 'image')
      return <ImageIcon className="size-4 text-emerald-500" />
    if (cat === 'audio') return <Music className="size-4 text-violet-500" />
    if (cat === 'video') return <Video className="size-4 text-amber-500" />
    return <Paperclip className="size-4 text-muted-foreground" />
  }

  return (
    <div className="space-y-3">
      {/* Search Input Container with Drop Support */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        className={`relative flex items-center rounded-2xl border bg-card shadow-sm transition-all duration-200 ${
          isDragOver
            ? 'border-primary bg-primary/5 ring-2 ring-primary/30'
            : 'border-border/80 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20 hover:border-primary/40'
        }`}
      >
        <div className="flex size-12 shrink-0 items-center justify-center pl-2 text-muted-foreground">
          <Search className="size-5" />
        </div>

        <input
          type="text"
          value={query}
          onChange={(e) => onChangeQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            queryFile
              ? 'Optional text to refine media query (e.g. "aerial view", "speech section")...'
              : 'Search documents, images, audio, video by semantics, OCR, or text...'
          }
          className="h-14 w-full bg-transparent px-2 text-sm text-foreground placeholder:text-muted-foreground/80 focus:outline-none"
        />

        <div className="flex items-center gap-2 pr-3">
          {/* Query attachment trigger */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,video/*,audio/*"
            className="hidden"
            onChange={(e) => handleFileSelect(e.target.files)}
          />

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            title="Attach image or audio/video for multimodal search"
            className="h-9 gap-1.5 rounded-xl px-2.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Paperclip className="size-4" />
            <span className="hidden sm:inline">Attach Media</span>
          </Button>

          <Button
            type="button"
            size="sm"
            onClick={onSearch}
            disabled={loading || (!query.trim() && !queryFile)}
            className="h-9 gap-1.5 rounded-xl px-5 text-xs font-semibold shadow-xs"
          >
            {loading ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Search className="size-4" />
            )}
            <span>Search</span>
          </Button>
        </div>
      </div>

      {/* Query File Rich Preview Card */}
      {queryFile && (
        <div className="flex animate-in items-center justify-between gap-3 rounded-xl border border-primary/25 bg-primary/5 p-3 text-xs shadow-xs duration-200 fade-in-50">
          <div className="flex min-w-0 items-center gap-3">
            {imagePreviewUrl ? (
              <img
                src={imagePreviewUrl}
                alt="Query image"
                className="size-12 rounded-lg border border-border object-cover shadow-2xs"
              />
            ) : (
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border/80 bg-background shadow-2xs">
                {renderFileIcon(queryFile)}
              </div>
            )}

            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate font-semibold text-foreground">
                  {queryFile.name}
                </span>
                <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  Multimodal Query
                </span>
              </div>
              <p className="font-mono text-[11px] text-muted-foreground">
                {queryFile.type || 'media'} &bull; {formatBytes(queryFile.size)}
              </p>
            </div>
          </div>

          <Button
            variant="ghost"
            size="icon-xs"
            onClick={() => {
              onChangeQueryFile(null)
              setFileWarning(null)
            }}
            title="Remove attachment"
            className="rounded-lg hover:bg-destructive/10 hover:text-destructive"
          >
            <X className="size-4" />
          </Button>
        </div>
      )}

      {/* Search Suggestion Pills */}
      {!query && !queryFile && (
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5 text-xs">
          <span className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
            <Sparkles className="size-3 text-primary" /> Suggestions:
          </span>
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => {
                onChangeQuery(s)
              }}
              className="rounded-full border border-border/70 bg-muted/40 px-2.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:bg-muted hover:text-foreground"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Warning banner */}
      {fileWarning && (
        <div className="flex animate-in items-center gap-2 rounded-xl border border-destructive/25 bg-destructive/10 p-3 text-xs text-destructive fade-in-50">
          <AlertTriangle className="size-4 shrink-0" />
          <span className="flex-1">{fileWarning}</span>
          <button
            type="button"
            onClick={() => setFileWarning(null)}
            className="font-semibold underline hover:no-underline"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}
