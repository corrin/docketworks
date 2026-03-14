# Bug Fix Plan: Missing Estimate CostLines on Job Creation

## Problem Summary

When creating a new job with estimated materials and workshop time, the resulting job sometimes shows no estimate data. The bug is intermittent due to race conditions in the current implementation.

## Root Cause

Currently, the frontend creates the job first, then attempts to create CostLines asynchronously after navigation. This creates race conditions and error handling issues:

1. `JobCreateView.vue` calls `jobService.createJob()`
2. Backend creates job + 3 empty CostSets (estimate, quote, actual)
3. Frontend navigates to `JobView.vue`
4. Frontend attempts to create CostLines asynchronously (lines 517-556 in JobCreateView.vue)
5. Errors are caught but only toasted/logged, not blocking

The `estimatedMaterials` and `estimatedTime` fields are frontend-only and not in the `JobCreateRequest` schema, so they're ignored by the backend.

## Solution: Move CostLine Creation to Backend

The frontend already fetches CostLines from the backend when loading the estimate tab, so it will automatically display whatever the backend creates.

### Frontend Verification (Already Works)

The frontend flow that will pick up backend-created CostLines:

1. `JobCreateView.vue` navigates to `JobView.vue` (line 581-586)
2. `JobView.vue` `onMounted` loads job header (line 338-354)
3. User clicks "Estimate" tab → `JobViewTabs.vue` shows `JobEstimateTab.vue`
4. `JobEstimateTab.vue` `onMounted` → calls `loadEstimate()` (line 162-176)
5. `loadEstimate()` → calls `fetchCostSet(jobId, 'estimate')` (JobEstimateTab.vue:144)
6. `fetchCostSet()` → calls `GET /job/rest/jobs/:id/cost_sets/estimate/` (costing.service.ts:11)
7. Frontend displays whatever CostLines are returned

**The frontend doesn't care who created the CostLines - it just fetches and displays them.**

---

## Backend Changes Required

### Instructions for Backend Claude

**File to modify:** `/home/corrin/src/jobs_manager/apps/job/views/job_rest_views.py` (or wherever the job creation endpoint lives)

**Changes needed:**

1. **Update JobCreateRequest schema/serializer:**

   - Add `estimated_materials` field (Decimal, required, >= 0)
   - Add `estimated_time` field (Decimal, required, >= 0)

2. **In the job creation endpoint (after job and CostSets are created):**

   ```python
   # After creating job and 3 CostSets, get the estimate CostSet
   estimate_costset = job.costsets.get(kind='estimate')

   # Get company defaults for calculations
   company_defaults = CompanyDefaults.objects.first()
   wage_rate = company_defaults.wage_rate
   charge_out_rate = company_defaults.charge_out_rate
   materials_markup = company_defaults.materials_markup

   # Create material cost line
   CostLine.objects.create(
       cost_set=estimate_costset,
       kind='material',
       desc='Estimated materials',
       quantity=1,
       unit_cost=estimated_materials,
       unit_rev=estimated_materials * (1 + materials_markup)
   )

   # Create workshop time cost line
   CostLine.objects.create(
       cost_set=estimate_costset,
       kind='time',
       desc='Estimated workshop time',
       quantity=estimated_time,
       unit_cost=wage_rate,
       unit_rev=charge_out_rate
   )

   # Calculate office time (1:8 ratio, rounded up to quarter hours)
   office_time_hours = math.ceil((estimated_time / 8) * 4) / 4

   CostLine.objects.create(
       cost_set=estimate_costset,
       kind='time',
       desc='Estimated Office Time',
       quantity=office_time_hours,
       unit_cost=wage_rate,
       unit_rev=charge_out_rate
   )

   # For fixed_price jobs, copy estimate lines to quote CostSet
   if pricing_methodology == 'fixed_price':
       quote_costset = job.costsets.get(kind='quote')
       for estimate_line in estimate_costset.cost_lines.all():
           CostLine.objects.create(
               cost_set=quote_costset,
               kind=estimate_line.kind,
               desc=estimate_line.desc,
               quantity=estimate_line.quantity,
               unit_cost=estimate_line.unit_cost,
               unit_rev=estimate_line.unit_rev,
               ext_refs=estimate_line.ext_refs,
               meta=estimate_line.meta
           )
   ```

3. **Ensure the response includes the created CostLines** (optional - frontend fetches them anyway)

**Testing:**

- Create a job with `estimated_materials: 1000` and `estimated_time: 10`
- Verify 3 CostLines are created in estimate CostSet
- For fixed_price jobs, verify CostLines are copied to quote CostSet
- Check the Django logs no longer show "CostSet missing summary data" errors

---

## Frontend Changes Required ✅ COMPLETED

**File:** `/home/corrin/src/jobs_manager_front/src/views/JobCreateView.vue`

### Changes (Implemented):

1. **Simplify `handleSubmit` function:**

   - Remove CostLine creation logic (lines 514-577)
   - Keep only job creation and navigation
   - Remove the `estimateLines` array and all `try/catch` blocks for CostLine creation
   - Remove the fixed_price quote copying logic

2. **Keep the form validation** for `estimatedMaterials` and `estimatedTime` (lines 476-484)

3. **Simplified flow:**

   ```typescript
   const handleSubmit = async () => {
     if (!validateForm()) {
       debugLog('Validation errors:', errors.value)
       return
     }

     isSubmitting.value = true
     toast.info('Creating job…', { id: 'create-job' })

     try {
       const result = await jobService.createJob(formData.value)

       if (result.success && result.job_id) {
         toast.success('Job created!')
         toast.dismiss('create-job')

         const defaultTab =
           formData.value.pricing_methodology === 'fixed_price' ? 'quote' : 'estimate'
         router.push({
           name: 'job-edit',
           params: { id: result.job_id },
           query: { new: 'true', tab: defaultTab },
         })
       } else {
         throw new Error(String(result.error) || 'Failed to create job')
       }
     } catch (error: unknown) {
       toast.error('Failed to create job: ' + ((error as Error).message || error))
       debugLog('Job creation error:', error)
       toast.dismiss('create-job')
     } finally {
       isSubmitting.value = false
     }
   }
   ```

### What Was Removed:

- ✅ Lines 514-577: All CostLine creation logic
- ✅ All references to `costlineService.createCostLine()`
- ✅ The `estimateLines` array
- ✅ All the individual try/catch blocks for material, workshop time, and office time
- ✅ The fixed_price quote copying logic
- ✅ `calculateOfficeTimeQuantity` helper function
- ✅ Import of `costlineService`
- ✅ Import of `useCompanyDefaultsStore`
- ✅ CompanyDefaults validation check

### What Was Kept:

- ✅ Form validation for `estimatedMaterials` and `estimatedTime`
- ✅ The `formData` object with all fields including `estimatedMaterials` and `estimatedTime`
- ✅ Navigation to job detail page
- ✅ Toast notifications
- ✅ All UI components and form fields

---

## Benefits of This Approach

1. **Atomic Operations:** Job and CostLines created in single transaction
2. **No Race Conditions:** Everything created before response returns
3. **Simpler Frontend:** Remove ~60 lines of complex async code
4. **Better Error Handling:** Backend errors properly returned to frontend
5. **More Reliable:** No timing issues with navigation
6. **Easier Debugging:** Single backend operation instead of 4+ frontend API calls

## Testing Plan

1. Create a T&M job with estimates → verify estimate tab shows 3 CostLines
2. Create a fixed_price job with estimates → verify both estimate and quote tabs show CostLines
3. Verify office time calculation (1:8 ratio, rounded to quarter hours)
4. Verify materials markup applied correctly
5. Check no "CostSet missing summary data" errors in Django logs
