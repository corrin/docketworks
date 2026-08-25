import { isNotFound } from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'

import { Route as FormsCategoryIndexRoute } from './index'
import { Route as FormsCategoryFormIdRoute } from './$formId'

type IndexBeforeLoadArg = Parameters<
  NonNullable<typeof FormsCategoryIndexRoute.options.beforeLoad>
>[0]
type FormIdBeforeLoadArg = Parameters<
  NonNullable<typeof FormsCategoryFormIdRoute.options.beforeLoad>
>[0]

// Both routes' beforeLoad only reads `params.category`, so a params-only
// context satisfies it at runtime; the router-internal fields (search,
// location, cause, …) this synthetic call never needs are why the cast is
// unsafe by oxlint's own rule, not by mistake.
function indexContextFor(category: string): IndexBeforeLoadArg {
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- synthetic minimal context for a unit test
  return { params: { category } } as unknown as IndexBeforeLoadArg
}

function formIdContextFor(category: string): FormIdBeforeLoadArg {
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- synthetic minimal context for a unit test
  return { params: { category, formId: 'irrelevant-form-id' } } as unknown as FormIdBeforeLoadArg
}

describe('forms/$category route guards', () => {
  it('index route lets a real category through', () => {
    expect(() =>
      FormsCategoryIndexRoute.options.beforeLoad?.(indexContextFor('safety')),
    ).not.toThrow()
  })

  it('index route renders not-found for a junk category', () => {
    let caught: unknown
    try {
      FormsCategoryIndexRoute.options.beforeLoad?.(indexContextFor('bogus'))
    } catch (error) {
      caught = error
    }
    expect(isNotFound(caught)).toBe(true)
  })

  it('$formId route lets a real category through', () => {
    expect(() =>
      FormsCategoryFormIdRoute.options.beforeLoad?.(formIdContextFor('incident')),
    ).not.toThrow()
  })

  it('$formId route renders not-found for a junk category', () => {
    let caught: unknown
    try {
      FormsCategoryFormIdRoute.options.beforeLoad?.(formIdContextFor('bogus'))
    } catch (error) {
      caught = error
    }
    expect(isNotFound(caught)).toBe(true)
  })
})
