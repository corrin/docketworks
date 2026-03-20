# Process URLs Documentation

<!-- This file is auto-generated. To regenerate, run: python scripts/generate_url_docs.py -->

### Categories Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/categories/` | `CategoriesView` | `process:process_categories` | Return available categories for procedures and forms. |

### Forms Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/forms/<str:category>/<uuid:pk>/fill/` | `form_viewsets.FormFillView` | `process:form_fill` | Create a new FormEntry from a Form definition. |

### Jobs Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/jobs/<uuid:job_id>/jsa/` | `procedure_viewsets.JSAListView` | `process:jsa_list` | List all JSAs for a job. |
| `/jobs/<uuid:job_id>/jsa/generate/` | `procedure_viewsets.JSAGenerateView` | `process:jsa_generate` | Generate a new JSA for a job. |

### Procedures Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/procedures/<str:category>/<uuid:pk>/content/` | `procedure_viewsets.ProcedureContentView` | `process:procedure_content` | GET/PUT content for a procedure stored in Google Docs. |
| `/procedures/safety/generate-sop/` | `procedure_viewsets.SOPGenerateView` | `process:sop_generate` | Generate a new Standard Operating Procedure. |
| `/procedures/safety/generate-swp/` | `procedure_viewsets.SWPGenerateView` | `process:swp_generate` | Generate a new Safe Work Procedure. |

### Safety-Ai Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/safety-ai/generate-controls/` | `procedure_viewsets.AIGenerateControlsView` | `process:ai_generate_controls` | Generate controls for hazards using AI. |
| `/safety-ai/generate-hazards/` | `procedure_viewsets.AIGenerateHazardsView` | `process:ai_generate_hazards` | Generate hazards for a task description using AI. |
| `/safety-ai/improve-document/` | `procedure_viewsets.AIImproveDocumentView` | `process:ai_improve_document` | Improve an entire document using AI. |
| `/safety-ai/improve-section/` | `procedure_viewsets.AIImproveSectionView` | `process:ai_improve_section` | Improve a section of text using AI. |
