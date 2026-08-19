const BASE_URL = import.meta.env.VITE_API_BASE_URL

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
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    const { message, fieldErrors, rawDetail } = await parseErrorDetail(response)
    throw new ApiError(response.status, message, fieldErrors, rawDetail)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
