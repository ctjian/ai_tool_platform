/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DELETE_PASSWORD?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
