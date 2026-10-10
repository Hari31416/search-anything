import type { SearchMatch } from '../types/api.ts'

// Group bounds include overlapping media windows. Use the displayed text's
// own bounds so its playback link opens the passage the user can see.
export function getMatchPreview(match: SearchMatch) {
  const textRepresentations = match.representations.filter((rep) =>
    rep.text?.trim()
  )
  const primary =
    textRepresentations.find((rep) => rep.channels.length > 0) ??
    textRepresentations[0]
  const evidenceIds = new Set(
    Object.values(match.channel_evidence ?? {}).map(
      (item) => item.representation_id
    )
  )
  const timedEvidence = match.representations.find(
    (rep) => evidenceIds.has(rep.representation_id) && rep.time_start !== null
  )
  const source = primary ?? timedEvidence ?? match
  return {
    text: primary?.text?.trim() ?? null,
    kind: primary?.kind ?? null,
    start: source.time_start,
    end: source.time_end,
  }
}
