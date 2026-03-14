# Quoting Tool – Implementation Progress & Plan

## ✅ Implementation Status

**Foundation Complete**: Chat interface, backend APIs, message persistence, file upload UI  
**Next Phase**: Core quoting workflow and MCP integration

## Purpose

A structured, estimator-facing quoting tool that:

- Follows a **strict, step-by-step process** with no assumptions
- Does **not proceed** to calculation until all required information is confirmed
- Uses current material and labor pricing via MCP
- Produces a **table of estimated labor and estimated materials**, including:
  - Supplier names
  - Supplier part numbers
  - Material cost
  - Labor effort
- Shows material usage via **three cross-checked methods**:
  - Area + waste percentage
  - Tenths-based usage
  - Proportional (fractional) billing basis
- Flags missing or inconsistent inputs
- Outputs a complete, **human-reviewed** quote

This is a quoting tool, not an AI assistant.

---

## Core Objectives

### 1. Process Enforcement

Before quoting begins, the tool confirms:

- Job type and fabrication context
- Quantity
- Dimensions
- Material type, thickness, and finish
- Install vs supply-only
- Welding, folding, or other fabrication methods

LLM confirms and reflects this understanding back to the estimator with clear assumptions before calculating anything.

---

### 2. Material & Labor Inputs

- Pricing is fetched via **MCP server queries**
- MCP tools return structured data from internal or supplier tables
- Tracks:
  - Sheet metal (type, finish, gauge, size)
  - Consumables (e.g. hinges, sealants)
  - Labor categories (fabrication, install, delivery)
- Remnant stock lookup via internal MCP tool
- No parsing of attached files—input is freeform text (though files/sketches are allowed)

---

### 3. Calculation Engine

#### 🔁 Two-Phase Quoting Workflow

---

### Phase 1: Material Interpretation & Expansion

LLM role: confirm estimator intent and compute material requirements.  
This phase ends with a complete material plan—no quoting occurs until this is resolved.

The system shows:

#### ✅ Material Usage Estimated Three Ways:

| Method                        | Description                                                     |
| ----------------------------- | --------------------------------------------------------------- |
| **1. Area + Waste %**         | Flat area × (1 + waste %) → divide by sheet area                |
| **2. Tenths (yield logic)**   | Sheet divided into 10 blocks → count tenths used by part layout |
| **3. Proportional (billing)** | Part area ÷ sheet area = fractional usage per part × quantity   |

- All three values are displayed
- Divergences help identify edge cases or misinterpretations
- Tenths are used for **yield planning**, proportional is used for **billing**

---

### Phase 2: Pricing

Once sheet usage is confirmed, the system:

- Queries MCP for **top 2 supplier prices**
- Flags large pricing gaps (potential spec mismatch)
- Checks internal remnant availability
- Applies:
  - Sheet pricing (cheapest and next-cheapest shown)
  - Labor (based on fabrication type and quantity)
  - Markup (explicit, editable)
- Generates full quote breakdown with trace:
  - Flat parts
  - Tenths consumed
  - Sheet pricing
  - Labor assumptions
  - Final totals

---

### 4. Output

- Structured quote line items (materials, labor, extras)
- Line-by-line calculation trace
- Summary table: total, markup, margin
- Comparison of material usage by all three methods
- Export to spreadsheet for quoting workflow
- Estimator-reviewed before client use

---

### 5. Quote Checking Mode

The tool supports a secondary mode: **quote verification**.  
In this mode:

- The user provides both:
  - The original estimator input (text description)
  - The manually prepared quote table
- The tool reprocesses the input using the standard calculation engine
- Compares actual vs expected:
  - Material usage
  - Supplier selection
  - Pricing
  - Labor hours
- Flags discrepancies or inconsistencies
- Explains the differences in a traceable way

This allows the tool to be used not only for quote generation, but also for training, auditing, and consistency checks.

---

## UI / UX

- **Freeform text interface** (chat-style, single-pass not multi-turn)
- Estimator enters part descriptions, dimensions, and notes
- System:
  - Parses and normalizes materials (e.g. “brushed” → “304/4”)
  - Confirms full assumptions before proceeding
  - Outputs tabular results with clear trace
- Supports:
  - Editable overrides
  - Clarification prompts
  - Export to quote document
  - Quote checking mode input form

---

## Non-Goals

- File upload and sketches are allowed, but **not required **. They're handled as a best effort
- Estimators are encouraged to provide structured text descriptions
- No quote outcome prediction (win/loss modelling). This is a tool for turning a job request into a dollar number.
- No pricing strategy automation
- No quoting without estimator confirmation and review

---

## 🎯 Implementation Roadmap

### Phase 1: Foundation ✅ COMPLETE

- ✅ Chat interface with job context
- ✅ Backend API for message persistence
- ✅ File upload UI integration
- ✅ Reset/clear chat functionality

### Phase 2: Core Workflow 🚧 IN PROGRESS

**Immediate Next Steps:**

1. **LLM Integration** (HIGH) - Replace mock responses with actual LLM calls
2. **Input Parsing** (HIGH) - Extract dimensions, materials, quantities from freeform text
3. **Confirmation Phase** (HIGH) - Implement structured confirmation before calculation

### Phase 3: Calculation Engine 📋 PLANNED

**Three-Method Material Usage:**

- Area + waste percentage calculation
- Tenths-based yield logic
- Proportional billing methodology
- Cross-validation and discrepancy flagging

### Phase 4: MCP Integration 📋 PLANNED

**Pricing & Materials:**

- Connect to supplier pricing APIs
- Internal remnant stock queries
- Real-time material cost lookup
- Labor rate calculations

### Phase 5: Output & Export 📋 PLANNED

- Structured quote table generation
- Calculation trace/audit trail
- Export to existing quote workflow
- Quote verification mode

## 🚀 Next Sprint Priority

**Week 1**: LLM integration with structured parsing  
**Week 2**: Implement confirmation phase and basic material extraction  
**Week 3**: Begin 3-method calculation engine

Focus: Get the core interaction working before building calculation complexity.
