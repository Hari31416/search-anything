import test from 'node:test'
import assert from 'node:assert/strict'
import { installExclusivePlayback, pauseOtherMedia } from './media-playback.ts'

class FakeMedia {
  paused = true
  readonly nodeName: 'AUDIO' | 'VIDEO'
  constructor(nodeName: 'AUDIO' | 'VIDEO') {
    this.nodeName = nodeName
  }
  pause() {
    this.paused = true
  }
}

class FakeDocument extends EventTarget {
  readonly media: FakeMedia[]
  constructor(media: FakeMedia[]) {
    super()
    this.media = media
  }
  querySelectorAll() {
    return this.media
  }
  play(media: FakeMedia) {
    media.paused = false
    const event = new Event('play')
    Object.defineProperty(event, 'target', { value: media })
    this.dispatchEvent(event)
  }
}

for (const [firstKind, secondKind] of [
  ['AUDIO', 'AUDIO'],
  ['VIDEO', 'VIDEO'],
  ['AUDIO', 'VIDEO'],
  ['VIDEO', 'AUDIO'],
] as const) {
  test(`${secondKind} playback pauses a preceding ${firstKind} player`, () => {
    const first = new FakeMedia(firstKind)
    const second = new FakeMedia(secondKind)
    const root = new FakeDocument([first, second])
    const cleanup = installExclusivePlayback(root as unknown as Document)
    root.play(first)
    assert.equal(first.paused, false)
    root.play(second)
    assert.equal(first.paused, true)
    assert.equal(second.paused, false)
    root.play(first)
    assert.equal(second.paused, true)
    assert.equal(first.paused, false)
    cleanup()
  })
}

test('opening a preview can pause every inline player', () => {
  const media = [new FakeMedia('AUDIO'), new FakeMedia('VIDEO')]
  media.forEach((player) => {
    player.paused = false
  })
  const root = new FakeDocument(media)
  pauseOtherMedia(null, root as unknown as Document)
  assert.ok(media.every((player) => player.paused))
})

test('cleanup pauses playback and removes the listener', () => {
  const first = new FakeMedia('AUDIO')
  const second = new FakeMedia('VIDEO')
  const root = new FakeDocument([first, second])
  const cleanup = installExclusivePlayback(root as unknown as Document)
  root.play(first)
  cleanup()
  assert.equal(first.paused, true)
  root.play(first)
  root.play(second)
  assert.equal(first.paused, false)
  assert.equal(second.paused, false)
})
