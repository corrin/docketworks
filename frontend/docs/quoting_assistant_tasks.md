🧱 Phase 1 – Input Handling & Validation ✅ FOUNDATION COMPLETE

**Navigation Integration Complete ✅**

- Interactive Quote button added to JobView (mobile + desktop)
- Route `/quoting/tool` created with job context
- QuotingToolView created with phase management
  1.1 Parse Estimator Input ✅

✅ Extract quantity, dimensions, material type, fabrication requirements

✅ Recognize multiple part types (e.g. flat plate, folded tray, angle bar)

**Files Created:**

- `src/types/quoting-tool.ts` - Complete interfaces
- `src/services/quoting-tool.service.ts` - parseInputText method

  1.2 Validate Input Completeness

Check: material, finish, gauge/diameter, fabrication intent

Flag ambiguous or missing fields

Normalize material shorthand (e.g. “brushed” → “304/4”)

1.3 Confirm Material Spec with Estimator

Present back parsed + normalized input

Ask for confirmation or correction

Do not proceed until confirmed

📐 Phase 2 – Material Usage Calculation
2.1 Flat Area Calculator (for sheet/plate)

Area + seam allowance + waste %

Handles multi-face parts (e.g. welded box)

2.2 Tenths-Based Sheet Yield Estimator

Divide standard sheet into tenths

Count tenths per part

Total = quantity × tenths per part

2.3 Proportional Billing Calculator

Part area ÷ sheet area × quantity

Used only for fractional cost recovery

2.4 Bar Stock Calculator

Use per-part length

Add handling cutoff waste

Total bar length = ceil(sum / available lengths)

2.5 Consumables & Services Estimator

Detect and account for:

Rivets, fasteners, sealants

Galvanising (price per m² or per kg)

Powder coating, polishing

2.6 Usage Summary (All Materials)

Report estimated usage for each material type

Show sheet, bar, and consumables side-by-side

Include waste rules + physical yield where applicable

🧮 Phase 3 – Price & Labor
3.1 MCP Price Lookup

Fetch top 2 supplier prices from MCP

Sheet

Bar

Rivets and other items

Include part number, unit price, supplier

Flag large price gaps

3.2 Remnant Stock Check

Query MCP for available internal remnants

If match found, prefer remnant (zero material cost)

3.3 Labor Estimation

Apply fabrication time per method:

Welding, folding, punching, assembly

Also handles delivery or install time

📦 Phase 4 – Quote Table Generation
4.1 Build Line Items Table

Per part: material, supplier, quantity, usage, price

Per service: name, basis (m²/kg), total

Include unit rates, markup, part numbers

4.2 Apply Markup & Totals

Show:

Raw material + labor

Markup %

Final cost

Breakdown by category

4.3 Export for Quote Use

Copy-paste-ready table

CSV download

Flags questionable inputs for review

🔍 Phase 5 – Quote Checking Mode
5.1 Accept Estimator Quote Table

Accept both original input and manual quote

5.2 Recalculate Internally

Run full material + labor logic

Re-query MCP

5.3 Report Discrepancies

Differences in sheet/bar usage, price, labor

Clear reasons (e.g. different supplier, yield rule)

Highlight errors or assumptions

🧑‍💻 Phase 6 – UI & Dev Utilities
6.1 Minimal Estimator UI

Freeform text input box

Clear output layout: tables, traces

Support simple editing + re-submission

6.2 Developer Test Harness

JSON job input + expected output

Log MCP query results

Enable CI-level test coverage of logic
