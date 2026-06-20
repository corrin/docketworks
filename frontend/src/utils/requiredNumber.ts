export function requiredNumber(value: unknown, label: string): number {
  if (value === null || value === undefined || value === '') {
    throw new Error(`Missing ${label}`)
  }
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) {
    throw new Error(`Invalid ${label}: ${JSON.stringify(value)}`)
  }
  return numberValue
}
