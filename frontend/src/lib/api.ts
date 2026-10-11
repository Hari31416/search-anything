import type {
  Asset,
  AssetStatus,
  IngestionOptions,
  Profile,
  ReadinessResponse,
  SearchRequest,
  SearchResponse,
  UploadResponse,
  Workspace,
} from '@/types/api'

export class ApiError extends Error {
  readonly status: number
  readonly details: string

  constructor(status: number, message: string, details?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details || message
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.ok) {
    if (res.status === 204) {
      return undefined as unknown as T
    }
    return (await res.json()) as T
  }

  let errorMessage = `Request failed with status ${res.status}`
  let detailed = ''

  try {
    const errorData = (await res.json()) as { detail?: unknown }
    if (typeof errorData.detail === 'string') {
      errorMessage = errorData.detail
      detailed = errorData.detail
    } else if (Array.isArray(errorData.detail)) {
      detailed = errorData.detail
        .map((item: { loc?: (string | number)[]; msg?: string }) => {
          const field = Array.isArray(item.loc) ? item.loc.join('.') : ''
          return field
            ? `${field}: ${item.msg}`
            : (item.msg ?? 'Validation error')
        })
        .join(', ')
      errorMessage = detailed || errorMessage
    }
  } catch {
    // Non-JSON response
  }

  throw new ApiError(res.status, errorMessage, detailed)
}

export function createApi(workspaceId?: string) {
  const scopedUrl = (url: string) => {
    if (!workspaceId || !url.startsWith('/api/')) return url
    const separator = url.includes('?') ? '&' : '?'
    return `${url}${separator}workspace_id=${encodeURIComponent(workspaceId)}`
  }
  const scopedFetch = (url: string, options?: RequestInit) =>
    fetch(scopedUrl(url), options)
  type SearchJob = {
    id: string
    status: 'queued' | 'running' | 'retry' | 'succeeded' | 'failed'
    result?: SearchResponse | null
    error?: { code: string; message: string } | null
  }
  const waitForSearch = async (
    res: Response,
    signal?: AbortSignal
  ): Promise<SearchResponse> => {
    if (res.status === 200) return handleResponse<SearchResponse>(res)
    const submitted = await handleResponse<SearchJob>(res)
    const deadline = Date.now() + 10 * 60 * 1000
    while (true) {
      signal?.throwIfAborted()
      const job = await handleResponse<SearchJob>(
        await scopedFetch(
          `/api/search/jobs/${encodeURIComponent(submitted.id)}`,
          { signal }
        )
      )
      if (job.status === 'succeeded' && job.result) return job.result
      if (job.status === 'failed') {
        throw new ApiError(
          ['ValueError', 'ContextLimitError', 'IngestionError'].includes(
            job.error?.code ?? ''
          )
            ? 422
            : 503,
          job.error?.message || 'Search failed'
        )
      }
      if (Date.now() >= deadline) {
        throw new ApiError(
          504,
          'Search is still queued or processing. Try again later.'
        )
      }
      await new Promise<void>((resolve, reject) => {
        const onAbort = () => {
          clearTimeout(timer)
          reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
        }
        const timer = setTimeout(() => {
          signal?.removeEventListener('abort', onAbort)
          resolve()
        }, 500)
        signal?.addEventListener('abort', onAbort, { once: true })
        if (signal?.aborted) {
          signal.removeEventListener('abort', onAbort)
          onAbort()
        }
      })
    }
  }
  return {
    async getHealth(): Promise<ReadinessResponse> {
      const res = await scopedFetch('/health/ready')
      return handleResponse<ReadinessResponse>(res)
    },

    async getAssets(limit = 50, offset = 0): Promise<Asset[]> {
      const res = await scopedFetch(
        `/api/assets?limit=${limit}&offset=${offset}`
      )
      return handleResponse<Asset[]>(res)
    },

    async getAsset(id: string): Promise<Asset> {
      const res = await scopedFetch(`/api/assets/${id}`)
      return handleResponse<Asset>(res)
    },

    async uploadAsset(file: File): Promise<UploadResponse> {
      const formData = new FormData()
      formData.append('file', file)
      const res = await scopedFetch('/api/assets', {
        method: 'POST',
        body: formData,
      })
      return handleResponse<UploadResponse>(res)
    },

    async getAssetStatus(id: string): Promise<AssetStatus> {
      const res = await scopedFetch(`/api/assets/${id}/status`)
      return handleResponse<AssetStatus>(res)
    },

    async retryAsset(id: string): Promise<{
      status: string
      asset_id: string
      generation_id: string
      job_id: string
    }> {
      const res = await scopedFetch(`/api/assets/${id}/retry`, {
        method: 'POST',
      })
      return handleResponse<{
        status: string
        asset_id: string
        generation_id: string
        job_id: string
      }>(res)
    },

    async cancelAsset(
      id: string,
      generationId?: string
    ): Promise<{
      status: string
      asset_id: string
      generation_id: string
      running_jobs: number
    }> {
      const res = await scopedFetch(`/api/assets/${id}/cancel`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(
          generationId ? { generation_id: generationId } : {}
        ),
      })
      return handleResponse<{
        status: string
        asset_id: string
        generation_id: string
        running_jobs: number
      }>(res)
    },

    async deleteAsset(id: string): Promise<void> {
      const res = await scopedFetch(`/api/assets/${id}`, {
        method: 'DELETE',
      })
      await handleResponse<unknown>(res)
    },

    async reprocessAsset(
      id: string,
      profileName: string
    ): Promise<{
      status: string
      asset_id: string
      generation_id: string
      job_id: string
    }> {
      const res = await scopedFetch(`/api/assets/${id}/reprocess`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ profile_name: profileName }),
      })
      return handleResponse<{
        status: string
        asset_id: string
        generation_id: string
        job_id: string
      }>(res)
    },

    async getProfiles(): Promise<Profile[]> {
      const res = await scopedFetch('/api/profiles')
      return handleResponse<Profile[]>(res)
    },

    async saveProfile(
      name: string,
      options: IngestionOptions
    ): Promise<Profile> {
      const res = await scopedFetch(
        `/api/profiles/${encodeURIComponent(name)}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ options }),
        }
      )
      return handleResponse<Profile>(res)
    },

    async getPresignedUrl(
      id: string
    ): Promise<{ url: string; expires_in_seconds: number }> {
      const res = await scopedFetch(`/api/assets/${id}/presigned`)
      return handleResponse<{ url: string; expires_in_seconds: number }>(res)
    },

    getAssetContentUrl(id: string): string {
      return scopedUrl(`/api/assets/${id}/content`)
    },

    async searchText(
      request: SearchRequest,
      signal?: AbortSignal
    ): Promise<SearchResponse> {
      const res = await scopedFetch('/api/search', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request),
        signal,
      })
      return waitForSearch(res, signal)
    },

    async searchImage(
      file: File,
      options: Omit<SearchRequest, 'query'> & { query?: string },
      signal?: AbortSignal
    ): Promise<SearchResponse> {
      const formData = new FormData()
      formData.append('file', file)
      if (options.query) formData.append('query', options.query)
      if (options.mode) formData.append('mode', options.mode)
      if (options.limit !== undefined)
        formData.append('limit', String(options.limit))
      if (options.candidate_limit !== undefined)
        formData.append('candidate_limit', String(options.candidate_limit))
      if (options.representation_mode)
        formData.append('representation_mode', options.representation_mode)

      if (options.content_types && options.content_types.length > 0) {
        formData.append('content_types', JSON.stringify(options.content_types))
      }
      if (options.asset_ids && options.asset_ids.length > 0) {
        formData.append('asset_ids', JSON.stringify(options.asset_ids))
      }
      if (options.weights && Object.keys(options.weights).length > 0) {
        formData.append('weights', JSON.stringify(options.weights))
      }
      if (
        options.similarity_cutoffs &&
        Object.keys(options.similarity_cutoffs).length > 0
      ) {
        formData.append(
          'similarity_cutoffs',
          JSON.stringify(options.similarity_cutoffs)
        )
      }

      const res = await scopedFetch('/api/search/image', {
        method: 'POST',
        body: formData,
        signal,
      })
      return waitForSearch(res, signal)
    },

    async searchMedia(
      file: File,
      options: Omit<SearchRequest, 'query'> & { query?: string },
      signal?: AbortSignal
    ): Promise<SearchResponse> {
      const formData = new FormData()
      formData.append('file', file)
      if (options.query) formData.append('query', options.query)
      if (options.mode) formData.append('mode', options.mode)
      if (options.limit !== undefined)
        formData.append('limit', String(options.limit))
      if (options.candidate_limit !== undefined)
        formData.append('candidate_limit', String(options.candidate_limit))
      if (options.representation_mode)
        formData.append('representation_mode', options.representation_mode)

      if (options.content_types && options.content_types.length > 0) {
        formData.append('content_types', JSON.stringify(options.content_types))
      }
      if (options.asset_ids && options.asset_ids.length > 0) {
        formData.append('asset_ids', JSON.stringify(options.asset_ids))
      }
      if (options.weights && Object.keys(options.weights).length > 0) {
        formData.append('weights', JSON.stringify(options.weights))
      }
      if (
        options.similarity_cutoffs &&
        Object.keys(options.similarity_cutoffs).length > 0
      ) {
        formData.append(
          'similarity_cutoffs',
          JSON.stringify(options.similarity_cutoffs)
        )
      }

      const res = await scopedFetch('/api/search/media', {
        method: 'POST',
        body: formData,
        signal,
      })
      return waitForSearch(res, signal)
    },
  }
}

export const api = createApi()

export const workspaceApi = {
  async list(): Promise<Workspace[]> {
    return handleResponse<Workspace[]>(await fetch('/api/workspaces'))
  },
  async create(name: string): Promise<Workspace> {
    return handleResponse<Workspace>(
      await fetch('/api/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
    )
  },
  async rename(id: string, name: string): Promise<Workspace> {
    return handleResponse<Workspace>(
      await fetch(`/api/workspaces/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
    )
  },
}
