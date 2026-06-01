import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { relative, resolve } from 'node:path'

const sourceRoot = resolve(__dirname, '../..')
const allowedStoreImportFiles = new Set([
  'components/shared/SaveStatusIndicator.vue',
  'composables/useSaveFeedback.ts',
])

function walkSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const fullPath = resolve(dir, entry)
    const stat = statSync(fullPath)
    if (stat.isDirectory()) {
      if (entry === '__tests__') continue
      files.push(...walkSourceFiles(fullPath))
    } else if (/\.(ts|vue)$/.test(entry)) {
      files.push(fullPath)
    }
  }
  return files
}

describe('save feedback boundary', () => {
  it('keeps direct save status store imports inside the approved boundary', () => {
    const offenders = walkSourceFiles(sourceRoot)
      .map((file) => ({
        file,
        relativePath: relative(sourceRoot, file),
        text: readFileSync(file, 'utf8'),
      }))
      .filter(({ relativePath, text }) => {
        if (allowedStoreImportFiles.has(relativePath)) return false
        return text.includes("from '@/stores/saveStatus'")
      })
      .map(({ relativePath }) => relativePath)

    expect(offenders).toEqual([])
  })

  it('keeps editor persistence success feedback out of toasts', () => {
    const forbiddenByFile = new Map([
      [
        'composables/useAddMaterialCostLine.ts',
        ['Material cost line added!', 'Adding material cost line...'],
      ],
      ['composables/useCreateCostLineFromEmpty.ts', ['Cost line created!']],
      [
        'components/workshop/WorkshopMaterialsUsedTable.vue',
        ['Material logged for approval', 'Adjustment added'],
      ],
      ['views/purchasing/PurchaseOrderFormView.vue', ['Receipt saved']],
      ['views/TimesheetEntryView.vue', ['Entry saved']],
    ])

    const offenders = [...forbiddenByFile.entries()].flatMap(([relativePath, messages]) => {
      const text = readFileSync(resolve(sourceRoot, relativePath), 'utf8')
      return messages
        .filter((message) => text.includes(`toast.success('${message}'`))
        .map((message) => `${relativePath}: ${message}`)
    })

    expect(offenders).toEqual([])
  })
})
