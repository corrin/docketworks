declare module 'lodash-es' {
  type DebouncedFunc<T extends (...args: unknown[]) => unknown> = ((
    ...args: Parameters<T>
  ) => ReturnType<T>) & {
    cancel(): void
    flush(): void
  }

  export function debounce<T extends (...args: unknown[]) => unknown>(
    func: T,
    wait?: number,
    options?: {
      leading?: boolean
      maxWait?: number
      trailing?: boolean
    },
  ): DebouncedFunc<T>
}
