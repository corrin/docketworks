/// <reference types="vite/client" />

declare module 'dompurify' {
  interface Config {
    USE_PROFILES?: { html?: boolean; svg?: boolean; svgFilters?: boolean; mathMl?: boolean }
    ALLOWED_TAGS?: string[]
    ALLOWED_ATTR?: string[]
    [key: string]: unknown
  }
  interface DOMPurify {
    sanitize(dirty: string | Node, config?: Config): string
    setConfig(config: Config): void
    clearConfig(): void
    isValidAttribute(tag: string, attr: string, value: string): boolean
    addHook(
      entryPoint: string,
      hookFunction: (node: Element, data: object, config: Config) => Element,
    ): void
    removeHook(entryPoint: string): void
    removeHooks(entryPoint: string): void
    removeAllHooks(): void
  }
  const DOMPurify: DOMPurify
  export default DOMPurify
}

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_ALLOWED_HOSTS: string
  readonly VITE_WEEKEND_TIMESHEETS_ENABLED: string
  readonly VITE_AUTH_METHOD: 'cookie' | 'bearer'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
