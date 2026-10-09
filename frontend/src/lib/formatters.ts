export function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const value = bytes / Math.pow(1024, i)
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return '--'
  const totalSeconds = Math.floor(seconds)
  const mins = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  const formattedSecs = secs < 10 ? `0${secs}` : `${secs}`
  if (mins >= 60) {
    const hours = Math.floor(mins / 60)
    const remainingMins = mins % 60
    const formattedMins =
      remainingMins < 10 ? `0${remainingMins}` : `${remainingMins}`
    return `${hours}:${formattedMins}:${formattedSecs}`
  }
  return `${mins}:${formattedSecs}`
}

export function formatTimeRange(
  start: number | null,
  end: number | null
): string {
  if (start === null && end === null) return ''
  const s = start !== null ? formatDuration(start) : '0:00'
  const e = end !== null ? formatDuration(end) : 'end'
  return `${s} – ${e}`
}

export function formatDate(dateString: string): string {
  try {
    const date = new Date(dateString)
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateString
  }
}

export function getMimeCategory(
  contentType: string
): 'document' | 'image' | 'audio' | 'video' | 'other' {
  if (contentType.startsWith('video/')) return 'video'
  if (contentType.startsWith('audio/')) return 'audio'
  if (contentType.startsWith('image/')) return 'image'
  if (
    contentType.startsWith('text/') ||
    contentType.includes('pdf') ||
    contentType.includes('word') ||
    contentType.includes('document')
  ) {
    return 'document'
  }
  return 'other'
}

export function formatScore(score: number): string {
  if (!isFinite(score)) return '0.000'
  return score.toFixed(4)
}
