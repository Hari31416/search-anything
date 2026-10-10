import test from 'node:test'
import assert from 'node:assert/strict'
import { getMatchPreview } from './match-preview.ts'
import type { RepresentationHit, SearchMatch } from '../types/api.ts'

function representation(
  overrides: Partial<RepresentationHit>
): RepresentationHit {
  return {
    representation_id: 'transcript',
    kind: 'transcript',
    text: 'classified as NPA',
    location: {},
    time_start: 27.5,
    time_end: 29.98,
    source_start: null,
    source_end: null,
    similarity: 0.83,
    channels: ['transcript'],
    ...overrides,
  }
}

function match(representations: RepresentationHit[]): SearchMatch {
  return {
    score: 0.03,
    channels: {},
    time_start: 0,
    time_end: 49.04,
    source_start: null,
    source_end: null,
    representations,
    channel_evidence: {
      audio: {
        contribution: 0.016,
        representation_id: 'audio',
        kind: 'audio',
        similarity: 0.68,
      },
    },
  }
}

const audio = representation({
  representation_id: 'audio',
  kind: 'audio',
  text: null,
  time_start: 25,
  time_end: 49.04,
  channels: ['audio'],
})

test('transcript preview seeks to its passage rather than the fused window start', () => {
  const unrelated = representation({
    text: 'opening sentence',
    channels: [],
    time_start: 0,
  })
  assert.deepEqual(
    getMatchPreview(match([unrelated, audio, representation({})])),
    {
      text: 'classified as NPA',
      kind: 'transcript',
      start: 27.5,
      end: 29.98,
    }
  )
})

test('a genuine transcript match at zero remains playable', () => {
  assert.equal(
    getMatchPreview(match([representation({ time_start: 0 })])).start,
    0
  )
})

test('audio-only preview uses the contributing audio window', () => {
  const unrelated = representation({
    ...audio,
    representation_id: 'other',
    time_start: 0,
    channels: [],
  })
  assert.deepEqual(getMatchPreview(match([unrelated, audio])), {
    text: null,
    kind: null,
    start: 25,
    end: 49.04,
  })
})

test('text without timestamps does not inherit misleading window timestamps', () => {
  assert.deepEqual(
    getMatchPreview(
      match([representation({ time_start: null, time_end: null }), audio])
    ),
    {
      text: 'classified as NPA',
      kind: 'transcript',
      start: null,
      end: null,
    }
  )
})

test('range-only matches retain their available bounds', () => {
  assert.deepEqual(getMatchPreview(match([])), {
    text: null,
    kind: null,
    start: 0,
    end: 49.04,
  })
})

test('mixed OCR and speech keep the source label with the contributing text', () => {
  const ocr = representation({
    representation_id: 'ocr',
    kind: 'ocr',
    text: 'Launch day',
    time_start: 6,
    time_end: 7,
    channels: [],
  })
  assert.deepEqual(getMatchPreview(match([ocr, representation({})])), {
    text: 'classified as NPA',
    kind: 'transcript',
    start: 27.5,
    end: 29.98,
  })
  assert.deepEqual(getMatchPreview(match([ocr])), {
    text: 'Launch day',
    kind: 'ocr',
    start: 6,
    end: 7,
  })
})
