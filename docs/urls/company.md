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

### Archive Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:person_id>/archive/` | `person_views.PersonArchiveView` | `people:person_archive` | Explicitly retire a person (deactivate all links + archive). |

### Company-Defaults Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/company-defaults/schema/` | `company_defaults_schema_api.CompanyDefaultsSchemaAPIView` | `api_company_defaults_schema` | API endpoint that returns field metadata for CompanyDefaults. |
| `/company-defaults/upload-logo/` | `company_defaults_logo_api.CompanyDefaultsLogoAPIView` | `api_company_defaults_upload_logo` | API view for uploading and deleting company logo images. |

### Company-Links Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:person_id>/company-links/` | `person_views.PersonCompanyLinksView` | `people:person_company_links` | List all active company relationships for a Person. |
| `/<uuid:person_id>/company-links/<uuid:company_id>/` | `person_views.PersonCompanyLinkDetailView` | `people:person_company_link_detail` | Create, update, reactivate, or remove a Person-company relationship. |

### Contact-Methods Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:person_id>/contact-methods/` | `person_views.PersonContactMethodsView` | `people:person_contact_methods` | List or create a Person's contact methods. |
| `/<uuid:person_id>/contact-methods/<uuid:method_id>/` | `person_views.PersonContactMethodDetailView` | `people:person_contact_method_detail` | Update or delete one Person contact method. |

### Create Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/create/` | `company_rest_views.CompanyCreateRestView` | `companies:company_create_rest` | REST view for creating new companies. |

### Jobs Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:company_id>/jobs/` | `company_rest_views.CompanyJobsRestView` | `companies:company_jobs_rest` | REST view for fetching all jobs for a specific company. |
| `/jobs/<uuid:job_id>/person/` | `company_rest_views.JobPersonRestView` | `companies:job_person_rest` | REST view for person information operations for a job. |

### Other
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/` | `person_views.PersonListView` | `people:person_list` | List and search active people across company relationships. |
| `/<uuid:company_id>/` | `company_rest_views.CompanyRetrieveRestView` | `companies:company_retrieve_rest` | REST view for retrieving a specific company by ID. |
| `/<uuid:person_id>/` | `person_views.PersonDetailView` | `people:person_detail` | Retrieve or update a Person's identity fields. |

### People Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/<uuid:company_id>/people/` | `person_views.CompanyPeopleView` | `companies:company_people_rest` | List a company's people or create a Person with its initial link. |
| `/<uuid:company_id>/people/phone-ownership/` | `person_views.CompanyPersonPhoneOwnershipView` | `companies:company_person_phone_ownership_rest` | Classify a phone before creating a Person for a company. |

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
