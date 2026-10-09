export function pauseOtherMedia(
  active: HTMLMediaElement | null = null,
  root: Pick<Document, 'querySelectorAll'> = document
) {
  for (const media of root.querySelectorAll<HTMLMediaElement>('audio, video')) {
    if (media !== active) media.pause()
  }
}

export function installExclusivePlayback(root: Document = document) {
  const onPlay = (event: Event) => {
    const media = event.target as HTMLMediaElement | null
    if (media?.nodeName === 'AUDIO' || media?.nodeName === 'VIDEO') {
      pauseOtherMedia(media, root)
    }
  }
  // Media play events do not bubble. Capture catches native controls and
  // timestamp buttons in both inline players and portaled preview dialogs.
  const options = { capture: true }
  root.addEventListener('play', onPlay, options)
  return () => {
    root.removeEventListener('play', onPlay, options)
    pauseOtherMedia(null, root)
  }
}
