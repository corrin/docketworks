/**
 * Fable: jsdom ships no IntersectionObserver, so this double is the global
 * under test (see setup.ts). Tests that need a scroll call `intersect()`,
 * which fires every observer still observing — like the real API, a
 * disconnected observer never fires again.
 */
const live = new Set<FakeIntersectionObserver>()

export class FakeIntersectionObserver implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly scrollMargin = ''
  readonly thresholds: readonly number[] = []
  private readonly callback: IntersectionObserverCallback
  private target: Element | null = null

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
  }

  observe(target: Element): void {
    this.target = target
    live.add(this)
  }

  unobserve(): void {
    this.target = null
    live.delete(this)
  }

  disconnect(): void {
    this.unobserve()
  }

  takeRecords(): IntersectionObserverEntry[] {
    return []
  }

  fire(isIntersecting: boolean): void {
    if (this.target === null) throw new Error('fired before observe()')
    const rect = this.target.getBoundingClientRect()
    this.callback(
      [
        {
          isIntersecting,
          target: this.target,
          time: 0,
          intersectionRatio: isIntersecting ? 1 : 0,
          boundingClientRect: rect,
          intersectionRect: rect,
          rootBounds: null,
        },
      ],
      this,
    )
  }
}

/** Scroll every observed element into (or out of) view. */
export function intersect(isIntersecting: boolean): void {
  for (const observer of live) observer.fire(isIntersecting)
}

/** How many observers are still observing — zero after every unmount. */
export function observingCount(): number {
  return live.size
}

/** Forget every observer, so one test's leak cannot fire in the next. */
export function resetIntersectionObservers(): void {
  live.clear()
}
