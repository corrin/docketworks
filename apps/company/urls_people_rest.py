"""REST URLs for first-class People and their company relationships."""

from django.urls import path

from apps.company.views.person_views import (
    PersonArchiveView,
    PersonCompanyLinkDetailView,
    PersonCompanyLinksView,
    PersonContactMethodDetailView,
    PersonContactMethodsView,
    PersonDetailView,
    PersonListView,
)

app_name = "people_rest"

urlpatterns = [
    path("", PersonListView.as_view(), name="person_list"),
    path("<uuid:person_id>/", PersonDetailView.as_view(), name="person_detail"),
    path(
        "<uuid:person_id>/company-links/",
        PersonCompanyLinksView.as_view(),
        name="person_company_links",
    ),
    path(
        "<uuid:person_id>/company-links/<uuid:company_id>/",
        PersonCompanyLinkDetailView.as_view(),
        name="person_company_link_detail",
    ),
    path(
        "<uuid:person_id>/contact-methods/",
        PersonContactMethodsView.as_view(),
        name="person_contact_methods",
    ),
    path(
        "<uuid:person_id>/contact-methods/<uuid:method_id>/",
        PersonContactMethodDetailView.as_view(),
        name="person_contact_method_detail",
    ),
    path(
        "<uuid:person_id>/archive/",
        PersonArchiveView.as_view(),
        name="person_archive",
    ),
]
