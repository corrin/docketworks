import { useEffect, useRef } from 'react'
import Quill from 'quill'
import 'quill/dist/quill.snow.css'

interface RichTextEditorProps {
  automationId: string
  initialHtml: string
  onChange: (html: string | null) => void
  onBlur: () => void
}

/**
 * Quill wrapper. The `.ql-editor` element inside the automation-id container
 * is part of the E2E contract, so this must be real Quill, not a
 * contenteditable imitation. Wrapped directly (not react-quill, which is not
 * React-19-safe): Quill owns the DOM subtree and React never re-renders
 * inside it.
 */
export function RichTextEditor({
  automationId,
  initialHtml,
  onChange,
  onBlur,
}: RichTextEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const quillRef = useRef<Quill | null>(null)
  const onChangeRef = useRef(onChange)
  const onBlurRef = useRef(onBlur)
  onChangeRef.current = onChange
  onBlurRef.current = onBlur

  useEffect(() => {
    const container = containerRef.current
    if (!container || quillRef.current) {
      return
    }
    const editorHost = document.createElement('div')
    container.appendChild(editorHost)
    const quill = new Quill(editorHost, { theme: 'snow' })
    quillRef.current = quill

    if (initialHtml) {
      quill.clipboard.dangerouslyPasteHTML(initialHtml)
    }

    quill.on('text-change', () => {
      // An empty editor still holds '<p><br></p>'; saving that would turn
      // "cleared the notes" into stored markup junk (unset is NULL).
      onChangeRef.current(quill.getText().trim() === '' ? null : quill.root.innerHTML)
    })
    quill.root.addEventListener('blur', () => onBlurRef.current())
    // Quill instances hold DOM and listeners for the component's lifetime;
    // the container unmounts with them, so no teardown is needed.
    // initialHtml is deliberately mount-only: Quill owns the content after
    // that, and re-pasting on parent re-render would move the caret.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return <div data-automation-id={automationId} ref={containerRef} />
}
