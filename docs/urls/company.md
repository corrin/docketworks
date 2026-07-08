# Company URLs Documentation

<!-- This file is auto-generated. To regenerate, run: python scripts/generate_url_docs.py -->

### Addresses Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/addresses/validate/` | `address_views.AddressValidateView` | `companies:address_validate` | Validate and clean an address using Google Address Validation API. |

### All Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/all/` | `company_rest_views.CompanyListAllRestView` | `companies:company_list_all_rest` | REST view for listing all companies. |

### Company-Defaults Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/company-defaults/schema/` | `company_defaults_schema_api.CompanyDefaultsSchemaAPIView` | `api_company_defaults_schema` | API endpoint that returns field metadata for CompanyDefaults. |
| `/company-defaults/upload-logo/` | `company_defaults_logo_api.CompanyDefaultsLogoAPIView` | `api_company_defaults_upload_logo` | API view for uploading and deleting company logo images. |

### Create Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/create/` | `company_rest_views.CompanyCreateRestView` | `companies:company_create_rest` | REST view for creating new companies. |

### Jobs Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:company_id>/jobs/` | `company_rest_views.CompanyJobsRestView` | `companies:company_jobs_rest` | REST view for fetching all jobs for a specific company. |
| `/jobs/<uuid:job_id>/contact/` | `company_rest_views.JobContactRestView` | `companies:job_contact_rest` | REST view for contact information operations for a job. |

### Other
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:company_id>/` | `company_rest_views.CompanyRetrieveRestView` | `companies:company_retrieve_rest` | REST view for retrieving a specific company by ID. |

### Search Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/search/` | `company_rest_views.CompanySearchRestView` | `companies:company_search_rest` | REST view for company search with pagination and sorting. |

### Supplier-Aliases Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:company_id>/supplier-aliases/` | `supplier_search_alias_views.CompanySupplierAliasListCreateView` | `companies:company_supplier_aliases_rest` | List and create search aliases for a company/supplier contact. |
| `/supplier-aliases/<uuid:alias_id>/` | `supplier_search_alias_views.SupplierAliasDetailView` | `companies:supplier_alias_detail_rest` | Deactivate a supplier search alias. |

### System
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/company-defaults/` | `company_defaults_api.CompanyDefaultsAPIView` | `api_company_defaults` | API view for managing company default settings. |

### Update Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:company_id>/update/` | `company_rest_views.CompanyUpdateRestView` | `companies:company_update_rest` | REST view for updating company information. |
