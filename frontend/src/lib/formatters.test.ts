import test from 'node:test'
import assert from 'node:assert/strict'
import {
  formatBytes,
  formatDuration,
  formatTimeRange,
  formatScore,
  getMimeCategory,
} from './formatters.ts'

test('formatBytes formats file sizes correctly', () => {
  assert.equal(formatBytes(0), '0 B')
  assert.equal(formatBytes(512), '512 B')
  assert.equal(formatBytes(1024), '1.0 KB')
  assert.equal(formatBytes(1048576), '1.0 MB')
  assert.equal(formatBytes(1572864), '1.5 MB')
  assert.equal(formatBytes(1073741824), '1.0 GB')
})

test('formatDuration formats seconds to mm:ss and hh:mm:ss', () => {
  assert.equal(formatDuration(null), '--')
  assert.equal(formatDuration(undefined), '--')
  assert.equal(formatDuration(0), '0:00')
  assert.equal(formatDuration(45), '0:45')
  assert.equal(formatDuration(75), '1:15')
  assert.equal(formatDuration(3665), '1:01:05')
})

test('formatTimeRange formats time spans correctly', () => {
  assert.equal(formatTimeRange(null, null), '')
  assert.equal(formatTimeRange(10, 25), '0:10 – 0:25')
  assert.equal(formatTimeRange(null, 30), '0:00 – 0:30')
  assert.equal(formatTimeRange(15, null), '0:15 – end')
})

test('getMimeCategory identifies content types', () => {
  assert.equal(getMimeCategory('application/pdf'), 'document')
  assert.equal(getMimeCategory('text/plain'), 'document')
  assert.equal(getMimeCategory('image/png'), 'image')
  assert.equal(getMimeCategory('image/jpeg'), 'image')
  assert.equal(getMimeCategory('audio/wav'), 'audio')
  assert.equal(getMimeCategory('audio/mpeg'), 'audio')
  assert.equal(getMimeCategory('video/mp4'), 'video')
  assert.equal(getMimeCategory('video/quicktime'), 'video')
  assert.equal(getMimeCategory('application/octet-stream'), 'other')
})

test('formatScore formats float scores cleanly', () => {
  assert.equal(formatScore(0.01639), '0.0164')
  assert.equal(formatScore(0), '0.0000')
  assert.equal(formatScore(NaN), '0.000')
})
