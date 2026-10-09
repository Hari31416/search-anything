export interface Workspace {
  id: string
  name: string
  created_at: string
}

export interface Asset {
  id: string
  filename: string
  content_type: string
  byte_size: number
  content_hash: string
  state:
    | 'pending'
    | 'processing'
    | 'ready'
    | 'failed'
    | 'cancelled'
    | 'deleted'
    | string
  duration_seconds: number | null
  page_count: number | null
  created_at: string
  active_generation_id: string | null
}

export interface UploadResponse {
  asset: Asset
  generation_id: string
  job_id: string
}

export interface PresignedURLResponse {
  url: string
  expires_in_seconds: number
}

export interface ReadinessResponse {
  status: string
  database: string
  storage: string
}

export interface JobStatus {
  id: string
  stage: string
  status:
    | 'pending'
    | 'queued'
    | 'retry'
    | 'running'
    | 'leased'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | string
  attempts: number
  max_attempts: number
  progress: number
  cancellation_requested: boolean
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface GenerationStatus {
  id: string
  state: string
  profile_snapshot: Record<string, unknown>
  extractor_versions: Record<string, unknown>
  created_at: string
  jobs: JobStatus[]
}

export interface AssetStatus {
  asset_id: string
  state: string
  active_generation_id: string | null
  current_generation_id: string | null
  generations: GenerationStatus[]
}

export type MediaPreset =
  | 'automatic'
  | 'speech_lectures'
  | 'general_video'
  | 'music_sounds'
  | 'camera_footage'

export interface IngestionOptions {
  strategy?: 'automatic'
  version?: number
  media_preset?: MediaPreset
  media_window_seconds?: number | null
  media_overlap_seconds?: number | null
  video_sampling_fps?: number | null
  transcription_language?: string | null
  text_chunk_tokens?: number
  text_overlap_tokens?: number
  ocr_languages?: string
  combined_media_text?: boolean
}

export interface Profile {
  id: string
  name: string
  revision: number
  config: IngestionOptions
  created_at: string
}

export type SearchMode = 'hybrid' | 'semantic' | 'keyword'
export type RepresentationMode = 'separate' | 'combined' | 'both'

export type ChannelName =
  | 'text'
  | 'transcript'
  | 'ocr'
  | 'image'
  | 'audio'
  | 'video'
  | 'combined'
  | 'lexical'
  | 'identifier'
  | 'filename'

export type DenseChannelName =
  'text' | 'transcript' | 'ocr' | 'image' | 'audio' | 'video' | 'combined'

export interface SearchRequest {
  query: string
  mode?: SearchMode
  representation_mode?: RepresentationMode
  limit?: number
  candidate_limit?: number
  content_types?: string[] | null
  asset_ids?: string[] | null
  weights?: Partial<Record<ChannelName, number>> | null
  similarity_cutoffs?: Partial<Record<DenseChannelName, number>> | null
}

export interface RepresentationHit {
  representation_id: string
  kind: string
  text: string | null
  location: Record<string, unknown>
  time_start: number | null
  time_end: number | null
  source_start: number | null
  source_end: number | null
  similarity: number | null
  channels: string[]
}

export interface ChannelEvidenceItem {
  contribution: number
  representation_id: string
  kind: string
  similarity: number | null
}

export interface SearchMatch {
  score: number
  channels: Record<string, number>
  time_start: number | null
  time_end: number | null
  source_start: number | null
  source_end: number | null
  representations: RepresentationHit[]
  channel_evidence: Record<string, ChannelEvidenceItem>
}

export interface SearchResult {
  asset_id: string
  filename: string
  content_type: string
  generation_id: string
  score: number
  matches: SearchMatch[]
}

export interface SearchResponse {
  query?: string
  mode: SearchMode
  representation_mode: RepresentationMode
  results: SearchResult[]
  transcript?: string
  query_window_count?: number
  query_duration_seconds?: number
  covered_ranges_seconds?: [number, number][]
  max_query_windows_per_modality?: number
  pooled_modalities?: string[]
  source_filename?: string
}

export interface ApiErrorDetail {
  loc?: (string | number)[]
  msg?: string
  type?: string
}

export interface ApiErrorResponse {
  detail: string | ApiErrorDetail[]
}
