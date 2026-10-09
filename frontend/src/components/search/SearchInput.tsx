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

  const handleFileSelect = (files: FileList | null) => {
    if (!files || files.length === 0) return
    const file = files[0]
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

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      onSearch()
    }
  }

  const renderFileIcon = (file: File) => {
    const cat = getMimeCategory(file.type)
    if (cat === 'image')
      return <ImageIcon className="size-3.5 text-emerald-500" />
    if (cat === 'audio') return <Music className="size-3.5 text-violet-500" />
    if (cat === 'video') return <Video className="size-3.5 text-amber-500" />
    return <Paperclip className="size-3.5 text-muted-foreground" />
  }

  return (
    <div className="space-y-3">
      <div className="relative flex items-center rounded-xl border border-input bg-card shadow-xs transition-shadow focus-within:border-ring focus-within:ring-1 focus-within:ring-ring">
        <div className="flex size-10 shrink-0 items-center justify-center pl-1 text-muted-foreground">
          <Search className="size-5" />
        </div>

        <input
          type="text"
          value={query}
          onChange={(e) => onChangeQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            queryFile
              ? 'Optional text to guide media query search (e.g. "blue bicycle")...'
              : 'Search documents, images, audio, transcripts, OCR, keywords...'
          }
          className="h-12 w-full bg-transparent px-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
        />

        <div className="flex items-center gap-1.5 pr-2">
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
            size="xs"
            onClick={() => fileInputRef.current?.click()}
            title="Attach image or audio/video file for multimodal query"
            className="gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <Paperclip className="size-3.5" />
            <span className="hidden sm:inline">Attach Media</span>
          </Button>

          <Button
            type="button"
            size="sm"
            onClick={onSearch}
            disabled={loading || (!query.trim() && !queryFile)}
            className="h-8 gap-1.5 px-4"
          >
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Search className="size-3.5" />
            )}
            Search
          </Button>
        </div>
      </div>

      {/* Query File Badge */}
      {queryFile && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs">
          <div className="flex min-w-0 items-center gap-2">
            {renderFileIcon(queryFile)}
            <span className="truncate font-semibold text-foreground">
              {queryFile.name}
            </span>
            <span className="text-muted-foreground">
              ({formatBytes(queryFile.size)})
            </span>
            <span className="py-0.2 rounded bg-muted px-1.5 text-[10px] text-muted-foreground">
              Query Attachment (Not stored in library)
            </span>
          </div>

          <Button
            variant="ghost"
            size="icon-xs"
            onClick={() => {
              onChangeQueryFile(null)
              setFileWarning(null)
            }}
            title="Remove attachment"
          >
            <X className="size-3.5" />
          </Button>
        </div>
      )}

      {/* Warning banner */}
      {fileWarning && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-xs text-destructive">
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
