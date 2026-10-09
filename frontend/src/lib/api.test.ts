import test from 'node:test'
import assert from 'node:assert/strict'
import { api, ApiError } from './api.ts'

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
