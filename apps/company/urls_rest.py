"""
Company REST URLs

REST URLs for Company module following RESTful patterns:
- Clearly defined endpoints
- Appropriate HTTP verbs
- Consistent structure with other REST modules
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.company.views.address_views import AddressValidateView
from apps.company.views.company_rest_views import (
    CompanyCreateRestView,
    CompanyJobsRestView,
    CompanyListAllRestView,
    CompanyRetrieveRestView,
    CompanySearchRestView,
    CompanyUpdateRestView,
    JobPersonRestView,
)
from apps.company.views.contact_method_viewset import ContactMethodViewSet
from apps.company.views.person_views import (
    CompanyPeopleView,
    CompanyPersonPhoneOwnershipView,
)
from apps.company.views.supplier_pickup_address_viewset import (
    SupplierPickupAddressViewSet,
)
from apps.company.views.supplier_search_alias_views import (
    CompanySupplierAliasListCreateView,
    SupplierAliasDetailView,
)

app_name = "companies_rest"

# Router for ViewSet-based endpoints
router = DefaultRouter()
router.register(
    "contact-methods",
    ContactMethodViewSet,
    basename="contact-method",
)
router.register(
    "pickup-addresses", SupplierPickupAddressViewSet, basename="supplier-pickup-address"
)

urlpatterns = [
    # Company list all REST endpoint
    path(
        "all/",
        CompanyListAllRestView.as_view(),
        name="company_list_all_rest",
    ),
    # Company creation REST endpoint
    path(
        "create/",
        CompanyCreateRestView.as_view(),
        name="company_create_rest",
    ),
    # Company search REST endpoint
    path(
        "search/",
        CompanySearchRestView.as_view(),
        name="company_search_rest",
    ),
    # Company retrieve REST endpoint
    path(
        "<uuid:company_id>/",
        CompanyRetrieveRestView.as_view(),
        name="company_retrieve_rest",
    ),
    # Company update REST endpoint
    path(
        "<uuid:company_id>/update/",
        CompanyUpdateRestView.as_view(),
        name="company_update_rest",
    ),
    # Company jobs REST endpoint
    path(
        "<uuid:company_id>/jobs/",
        CompanyJobsRestView.as_view(),
        name="company_jobs_rest",
    ),
    path(
        "<uuid:company_id>/people/",
        CompanyPeopleView.as_view(),
        name="company_people_rest",
    ),
    path(
        "<uuid:company_id>/people/phone-ownership/",
        CompanyPersonPhoneOwnershipView.as_view(),
        name="company_person_phone_ownership_rest",
    ),
    path(
        "<uuid:company_id>/supplier-aliases/",
        CompanySupplierAliasListCreateView.as_view(),
        name="company_supplier_aliases_rest",
    ),
    path(
        "supplier-aliases/<uuid:alias_id>/",
        SupplierAliasDetailView.as_view(),
        name="supplier_alias_detail_rest",
    ),
    # Job person REST endpoint
    path(
        "jobs/<uuid:job_id>/person/",
        JobPersonRestView.as_view(),
        name="job_person_rest",
    ),
    # Address validation endpoint
    path(
        "addresses/validate/",
        AddressValidateView.as_view(),
        name="address_validate",
    ),
    # ViewSet routes (people/contact method CRUD)
    path("", include(router.urls)),
]
