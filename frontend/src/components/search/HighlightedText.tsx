interface HighlightedTextProps {
  text: string
  query?: string | null
  className?: string
}

function tokenizeAndSplit(
  text: string,
  query: string
): { parts: string[]; regex: RegExp | null } {
  const rawTerms = query
    .trim()
    .split(/\s+/)
    .map((term) => term.replace(/[^\w\s-]/g, '').trim())
    .filter((term) => term.length >= 2)

  if (rawTerms.length === 0) {
    return { parts: [text], regex: null }
  }

  try {
    const escaped = rawTerms
      .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('|')
    const regex = new RegExp(`(${escaped})`, 'gi')
    return { parts: text.split(regex), regex }
  } catch {
    return { parts: [text], regex: null }
  }
}

export function HighlightedText({
  text,
  query,
  className,
}: HighlightedTextProps) {
  if (!query || !query.trim()) {
    return <span className={className}>{text}</span>
  }

  const { parts, regex } = tokenizeAndSplit(text, query)

  return (
    <span className={className}>
      {parts.map((part, i) => {
        if (!part) return null
        const isMatch = regex ? regex.test(part) : false
        if (regex) regex.lastIndex = 0
        return isMatch ? (
          <mark
            key={i}
            className="rounded-xs bg-primary/25 px-0.5 font-semibold text-primary"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      })}
    </span>
  )
}
