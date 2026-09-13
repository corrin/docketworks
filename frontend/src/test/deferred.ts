/** GPT: ES2023 lacks Promise.withResolvers; controlled responses prove ordering without sleeps. */
export function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
