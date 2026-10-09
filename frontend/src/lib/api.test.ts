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
