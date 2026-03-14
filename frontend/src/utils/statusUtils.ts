export function getStatusVariant(status: string | undefined): string {
  if (!status) {
    return 'secondary'
  }

  switch (status.toLowerCase()) {
    case 'quoting':
      return 'secondary'
    case 'accepted_quote':
      return 'default'
    case 'in_progress':
      return 'default'
    case 'completed':
      return 'outline'
    case 'on_hold':
      return 'destructive'
    case 'archived':
      return 'outline'
    default:
      return 'secondary'
  }
}

export function getJobColor(jobId: string | undefined): string {
  if (!jobId) {
    return 'bg-gray-100'
  }

  const hash = jobId.split('').reduce((a, b) => {
    a = (a << 5) - a + b.charCodeAt(0)
    return a & a
  }, 0)

  const colors = [
    'bg-blue-100',
    'bg-green-100',
    'bg-yellow-100',
    'bg-purple-100',
    'bg-pink-100',
    'bg-indigo-100',
  ]

  return colors[Math.abs(hash) % colors.length]
}
