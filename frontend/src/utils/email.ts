export interface EmailComposeOptions {
  to: string
  subject: string
  body: string
}

export function openGmailCompose({ to, subject, body }: EmailComposeOptions) {
  const params = new URLSearchParams({
    to,
    su: subject,
    body,
  })
  const url = `https://mail.google.com/mail/?view=cm&fs=1&${params.toString()}`
  window.open(url, '_blank', 'noopener,noreferrer')
}
