## Overview

**COMPLETE MIGRATION** from raw Axios + handwritten interfaces to Zodios API client
and centralised Zod schemas (generated and local).

## ⚠️ CRITICAL REQUIREMENTS ⚠️

1. **NO MORE AXIOS.GET/POST/PATCH/DELETE** - ALL API calls MUST use Zodios `api.endpoint()`
2. **NO MORE MANUAL RESPONSE PARSING** - Zodios handles validation automatically
3. **NO MORE FALLBACK CONVERSIONS** - Use the actual API response structure
4. **NO MORE `response.data ||`** - Remove all manual fallback logic

## Step-by-Step

1. **Mapping** – build DEPRECATED_REPORT.md from every `@deprecated` tag.
2. **API Migration** – **MANDATORY**: Replace ALL `axios.get/post/patch/delete` with `api.<alias>()`
   - Remove all manual response parsing (`response.data || []`)
   - Remove all manual type conversions (`convertedJobs.map(...)`)
   - Remove all fallback logic - trust the schema validation
3. **Schema Migration**  
   • Import generated schemas where available.  
   • Create local schemas in `src/api/local/schemas.ts` for uncovered cases.  
   • Replace interfaces with `z.infer<typeof XxxSchema>`.
4. **Clean Up** - Remove all manual error handling, response parsing, data conversion
5. **Lint** – run `npm run lint` until clean.
6. **Reporting** – tick finished items in DEPRECATED_REPORT.md.
7. **Pull Request** – commit: `refactor!: Zodios & Zod migration`, open PR.

## Anti-Patterns to ELIMINATE

❌ `axios.get('/api/endpoint')`  
❌ `response.data || []`  
❌ `convertedJobs.map(job => ({ ...transformation }))`  
❌ Manual error handling with try/catch for API calls  
❌ Manual type assertions and fallbacks

✅ `api.getPurchasingJobs()`  
✅ Direct usage of validated response  
✅ Trust the schema validation  
✅ Let Zodios handle errors

## Checklist

- [ ] DEPRECATED_REPORT.md reviewed
- [ ] **ALL** API calls migrated to Zodios (NO axios.get/post remaining)
- [ ] **ALL** manual response parsing removed
- [ ] **ALL** data conversion logic removed
- [ ] Interfaces replaced by generated schemas
- [ ] Remaining interfaces converted to local schemas
- [ ] Lint passes
- [ ] Pull Request merged
