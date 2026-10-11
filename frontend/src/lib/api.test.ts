import test from 'node:test'
import assert from 'node:assert/strict'
import { api, ApiError, createApi } from './api.ts'

test('api.getAssetContentUrl returns relative path for proxying', () => {
  const url = api.getAssetContentUrl('test-uuid-123')
  assert.equal(url, '/api/assets/test-uuid-123/content')
})

test('ApiError preserves status and details', () => {
  const err = new ApiError(404, 'Not found', 'asset not found')
  assert.equal(err.status, 404)
  assert.equal(err.message, 'Not found')
  assert.equal(err.details, 'asset not found')
})

test('workspace clients keep requests and preview URLs isolated', async (t) => {
  const calls: string[] = []
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    calls.push(url)
    if (url.startsWith('/api/search/jobs/')) {
      return Response.json({
        id: 'search-id',
        status: 'succeeded',
        result: { results: [] },
      })
    }
    if (url.startsWith('/api/search?')) {
      return Response.json(
        { id: 'search-id', status: 'queued' },
        { status: 202 }
      )
    }
    return new Response(JSON.stringify([]), { status: 200 })
  })
  const apollo = createApi('apollo')
  const work = createApi('work')
  await Promise.all([apollo.getAssets(10, 20), work.getProfiles()])
  await apollo.searchText({ query: 'moon', mode: 'keyword' })
  await apollo.uploadAsset(new File(['moon'], 'moon.txt'))
  await work.cancelAsset('asset')
  await work.getPresignedUrl('asset')
  assert.deepEqual(calls, [
    '/api/assets?limit=10&offset=20&workspace_id=apollo',
    '/api/profiles?workspace_id=work',
    '/api/search?workspace_id=apollo',
    '/api/search/jobs/search-id?workspace_id=apollo',
    '/api/assets?workspace_id=apollo',
    '/api/assets/asset/cancel?workspace_id=work',
    '/api/assets/asset/presigned?workspace_id=work',
  ])
  assert.equal(
    apollo.getAssetContentUrl('asset'),
    '/api/assets/asset/content?workspace_id=apollo'
  )
  assert.equal(
    work.getAssetContentUrl('asset'),
    '/api/assets/asset/content?workspace_id=work'
  )
})

test('search waits through retries and returns the persisted result', async (t) => {
  const expected = { query: 'moon', mode: 'hybrid', results: [] }
  let polls = 0
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    if (!url.includes('/jobs/'))
      return Response.json({ id: 'queued', status: 'queued' }, { status: 202 })
    polls += 1
    return Response.json(
      polls === 1
        ? { id: 'queued', status: 'retry', result: null }
        : { id: 'queued', status: 'succeeded', result: expected }
    )
  })
  assert.deepEqual(await api.searchText({ query: 'moon' }), expected)
  assert.equal(polls, 2)
})

test('search exposes worker failures', async (t) => {
  t.mock.method(globalThis, 'fetch', async (url: string) =>
    Response.json(
      url.includes('/jobs/')
        ? {
            id: 'bad',
            status: 'failed',
            error: { code: 'ValueError', message: 'Invalid media' },
          }
        : { id: 'bad', status: 'queued' },
      { status: url.includes('/jobs/') ? 200 : 202 }
    )
  )
  await assert.rejects(
    api.searchMedia(new File(['bad'], 'bad.wav'), {}),
    (err: unknown) =>
      err instanceof ApiError &&
      err.status === 422 &&
      err.message === 'Invalid media'
  )
})

test('aborting a search stops polling', async (t) => {
  const controller = new AbortController()
  const calls: string[] = []
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    calls.push(url)
    if (url.includes('/jobs/')) controller.abort()
    return Response.json(
      { id: 'pending', status: 'running' },
      { status: url.includes('/jobs/') ? 200 : 202 }
    )
  })
  await assert.rejects(
    api.searchImage(new File(['image'], 'query.png'), {}, controller.signal),
    (err: unknown) => err instanceof DOMException && err.name === 'AbortError'
  )
  assert.equal(calls.length, 2)
})

test('completed text, image, and media submissions return without status polling', async (t) => {
  const expected = { query: 'moon', mode: 'semantic', results: [] }
  const urls: string[] = []
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    urls.push(url)
    return Response.json(expected)
  })
  assert.deepEqual(await api.searchText({ query: 'moon' }), expected)
  assert.deepEqual(
    await api.searchImage(new File(['image'], 'query.png'), {}),
    expected
  )
  assert.deepEqual(
    await api.searchMedia(new File(['audio'], 'query.wav'), {}),
    expected
  )
  assert.deepEqual(urls, [
    '/api/search',
    '/api/search/image',
    '/api/search/media',
  ])
})
