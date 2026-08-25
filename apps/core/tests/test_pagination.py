"""The one pagination envelope (results/count/page/page_size/total_pages).

Company, CRM and process all page lists; this module is the single
implementation they share (the company app's docstring asked for the hoist
on the second consumer).
"""

import pytest
from django.http import Http404

from apps.core.models import ServiceAPIKey
from apps.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, paginate

pytestmark = pytest.mark.django_db


def make_keys(count: int) -> None:
    for index in range(count):
        ServiceAPIKey.objects.create(name=f"key-{index}")


class TestPaginate:
    def test_defaults_to_page_size_50(self) -> None:
        make_keys(3)
        page = paginate(ServiceAPIKey.objects.order_by("name"), page=1, page_size=None)
        assert page.page_size == DEFAULT_PAGE_SIZE
        assert page.count == 3
        assert page.total_pages == 1
        assert len(page.rows) == 3

    def test_caps_page_size_at_100(self) -> None:
        make_keys(1)
        page = paginate(ServiceAPIKey.objects.order_by("name"), page=1, page_size=9999)
        assert page.page_size == MAX_PAGE_SIZE

    def test_zero_or_negative_page_size_falls_back_to_default(self) -> None:
        make_keys(1)
        queryset = ServiceAPIKey.objects.order_by("name")
        assert paginate(queryset, page=1, page_size=0).page_size == DEFAULT_PAGE_SIZE
        assert paginate(queryset, page=1, page_size=-5).page_size == DEFAULT_PAGE_SIZE

    def test_out_of_range_page_is_404(self) -> None:
        make_keys(1)
        with pytest.raises(Http404):
            paginate(ServiceAPIKey.objects.order_by("name"), page=99, page_size=None)

    def test_slices_the_requested_page(self) -> None:
        make_keys(5)
        page = paginate(ServiceAPIKey.objects.order_by("name"), page=2, page_size=2)
        assert page.page == 2
        assert page.count == 5
        assert page.total_pages == 3
        assert len(page.rows) == 2
