/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Where the dev server proxies /api to (vite.config.ts); the page itself calls its own origin. */
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
