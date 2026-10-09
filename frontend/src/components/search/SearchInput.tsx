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
  SlidersHorizontal,
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
  showSettings: boolean
  onToggleSettings: () => void
  hasCustomSettings?: boolean
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
  showSettings,
  onToggleSettings,
  hasCustomSettings,
}: SearchInputProps) {
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const [fileWarning, setFileWarning] = React.useState<string | null>(null)
  const [isDragOver, setIsDragOver] = React.useState(false)

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
        'Unsupported query attachment format. Attach an image, audio, or video file.'
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
      return <ImageIcon className="size-3.5 text-emerald-500" />
    if (cat === 'audio') return <Music className="size-3.5 text-sky-500" />
    if (cat === 'video') return <Video className="size-3.5 text-amber-500" />
    return <Paperclip className="size-3.5 text-muted-foreground" />
  }

  return (
    <div className="space-y-2.5">
      {/* Search Input Container with Drop Support */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        className={`relative flex items-center rounded-2xl border bg-card shadow-xs transition-all duration-200 ${
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
          placeholder={queryFile ? 'Refine search...' : 'Search anything...'}
          className="h-13 w-full bg-transparent px-2 text-sm text-foreground placeholder:text-muted-foreground/80 focus:outline-none"
        />

        <div className="flex items-center gap-1.5 pr-2.5">
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
            title="Attach image or audio/video for search"
            className="h-8 gap-1.5 rounded-xl px-2.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Paperclip className="size-3.5" />
            <span className="hidden sm:inline">Attach</span>
          </Button>

          {/* Config / Settings Toggle Button */}
          <Button
            type="button"
            variant={showSettings ? 'secondary' : 'ghost'}
            size="sm"
            onClick={onToggleSettings}
            title="Search options & weights"
            className={`relative h-8 gap-1.5 rounded-xl px-2.5 text-xs transition-colors ${
              showSettings
                ? 'bg-secondary text-secondary-foreground'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <SlidersHorizontal className="size-3.5" />
            <span className="hidden sm:inline">Options</span>
            {hasCustomSettings && (
              <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-primary" />
            )}
          </Button>

          <Button
            type="button"
            size="sm"
            onClick={onSearch}
            disabled={loading || (!query.trim() && !queryFile)}
            className="h-8 gap-1.5 rounded-xl px-4 text-xs font-semibold shadow-xs"
          >
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Search className="size-3.5" />
            )}
            <span>Search</span>
          </Button>
        </div>
      </div>

      {/* Compact Query File Pill (unobtrusive, no transcripts or heavy boxes) */}
      {queryFile && (
        <div className="flex items-center gap-2">
          <div className="inline-flex items-center gap-2 rounded-lg border border-border/80 bg-muted/40 px-2.5 py-1 text-xs text-foreground shadow-2xs">
            {renderFileIcon(queryFile)}
            <span className="max-w-xs truncate font-medium">
              {queryFile.name}
            </span>
            <span className="font-mono text-[11px] text-muted-foreground">
              ({formatBytes(queryFile.size)})
            </span>
            <button
              type="button"
              onClick={() => {
                onChangeQueryFile(null)
                setFileWarning(null)
              }}
              title="Remove attached file"
              className="ml-1 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-3" />
            </button>
          </div>
        </div>
      )}

      {/* Warning banner */}
      {fileWarning && (
        <div className="flex animate-in items-center gap-2 rounded-xl border border-destructive/25 bg-destructive/10 p-2.5 text-xs text-destructive fade-in-50">
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
