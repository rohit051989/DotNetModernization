/** Same origin: the dev server proxies /api to the backend (vite.config.ts), so the session cookie the backend sets
 * is the page's own, sent with every call and every download link. */
const BASE_URL = ''

/** Fired when the backend says there is no signed-in session: the app shows the sign-in page. */
export const SIGNED_OUT_EVENT = 'platform:signed-out'

/** Fired, with the backend's message as its detail, when a change is refused because the admin has updated the
 * database while this backend runs (409 PLATFORM_UPDATED): the app shows a banner to update and restart. */
export const PLATFORM_UPDATED_EVENT = 'platform:updated'

/** For places that need a real URL rather than a fetch() call — e.g. a
 * download link the browser navigates to directly. */
export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`
}

export interface FieldError {
  field: string
  message: string
}

export class ApiError extends Error {
  status: number
  /** The first error's machine-readable code: SIGNED_OUT, NOT_ALLOWED, STALE_COPY, ... */
  code: string | null
  fieldErrors: FieldError[]
  /** The raw `detail` array, verbatim, for endpoints whose error items carry
   * fields beyond the generic {field, message, code} shape — e.g. the step
   * policy dependency guard's `dependent_steps`/`blocking_steps`/`resolution`
   * (see types/policy.ts's PolicyConflictDetail). Empty unless `detail` was
   * an array. */
  rawDetail: unknown[]

  constructor(status: number, message: string, fieldErrors: FieldError[] = [], rawDetail: unknown[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    const first = rawDetail[0] as { code?: unknown } | undefined
    this.code = typeof first?.code === 'string' ? first.code : null
    this.fieldErrors = fieldErrors
    this.rawDetail = rawDetail
  }
}

async function parseErrorDetail(
  response: Response,
): Promise<{ message: string; fieldErrors: FieldError[]; rawDetail: unknown[] }> {
  let body: unknown
  try {
    body = await response.json()
  } catch {
    return { message: response.statusText || 'Request failed', fieldErrors: [], rawDetail: [] }
  }

  const detail = (body as { detail?: unknown })?.detail

  if (Array.isArray(detail)) {
    const fieldErrors = detail.map((item) => ({
      field: typeof item?.field === 'string' ? item.field : '__root__',
      message: typeof item?.message === 'string' ? item.message : String(item),
    }))
    return { message: fieldErrors[0]?.message ?? 'Request failed', fieldErrors, rawDetail: detail }
  }

  if (typeof detail === 'string') {
    return { message: detail, fieldErrors: [], rawDetail: [] }
  }

  return { message: 'Request failed', fieldErrors: [], rawDetail: [] }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    const { message, fieldErrors, rawDetail } = await parseErrorDetail(response)
    const error = new ApiError(response.status, message, fieldErrors, rawDetail)
    if (response.status === 401 && error.code === 'SIGNED_OUT') window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
    if (response.status === 409 && error.code === 'PLATFORM_UPDATED') {
      window.dispatchEvent(new CustomEvent(PLATFORM_UPDATED_EVENT, { detail: message }))
    }
    throw error
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

/** An edit of a shared record names the version of the copy it was made on: a stale copy is refused (409
 * STALE_COPY), saying who changed it first, and nothing is overwritten. */
export interface EditOptions {
  version?: number | null
}

function versionHeader(options?: EditOptions): Record<string, string> {
  return options?.version !== undefined && options?.version !== null ? { 'If-Match': String(options.version) } : {}
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: EditOptions) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined, headers: versionHeader(options) }),
  put: <T>(path: string, body?: unknown, options?: EditOptions) =>
    request<T>(path, { method: 'PUT', body: body !== undefined ? JSON.stringify(body) : undefined, headers: versionHeader(options) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
