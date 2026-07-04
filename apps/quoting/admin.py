from typing import Any, cast

from django import forms
from django.contrib import admin
from django.db.models import QuerySet
from django.forms.models import BaseInlineFormSet
from django.http import HttpRequest

from apps.client.models import Client, Supplier
from apps.quoting.models import SupplierCredential, SupplierScraperConfig


class SupplierCredentialAdminForm(forms.ModelForm[SupplierCredential]):
    class Meta:
        model = SupplierCredential
        fields = "__all__"

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        self.instance.credential_type = cleaned_data.get("credential_type", "")
        self.instance.username = cleaned_data.get("username")
        self.instance.password = cleaned_data.get("password")
        self.instance.api_key = cleaned_data.get("api_key")
        self.instance.extra_config = cleaned_data.get("extra_config") or {}
        self.instance.clean()
        return cleaned_data


class SupplierScraperConfigAdminForm(forms.ModelForm[SupplierScraperConfig]):
    class Meta:
        model = SupplierScraperConfig
        fields = "__all__"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        supplier = None
        if self.instance and self.instance.pk:
            supplier = self.instance.supplier
        elif self.data.get("supplier"):
            supplier = self.data.get("supplier")

        if supplier:
            active_credential_field = cast(
                forms.ModelChoiceField[SupplierCredential],
                self.fields["active_credential"],
            )
            active_credential_field.queryset = SupplierCredential.objects.filter(
                supplier=supplier, is_active=True
            )
        else:
            active_credential_field = cast(
                forms.ModelChoiceField[SupplierCredential],
                self.fields["active_credential"],
            )
            active_credential_field.queryset = SupplierCredential.objects.none()

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        supplier = cleaned_data.get("supplier")
        active_credential = cleaned_data.get("active_credential")
        if supplier and active_credential:
            if active_credential.supplier_id != supplier.id:
                raise forms.ValidationError(
                    "Active credential must belong to the selected supplier."
                )
        return cleaned_data


class SupplierScraperConfigInlineFormSet(
    BaseInlineFormSet[SupplierScraperConfig, Any, Any]
):
    def add_fields(self, form: forms.BaseForm, index: int | None) -> None:
        super().add_fields(form, index)
        active_credential_field = cast(
            forms.ModelChoiceField[SupplierCredential],
            form.fields["active_credential"],
        )
        active_credential_field.queryset = SupplierCredential.objects.filter(
            supplier=self.instance, is_active=True
        )


class SupplierCredentialInline(admin.TabularInline[SupplierCredential, Client]):
    model = SupplierCredential
    form = SupplierCredentialAdminForm
    extra = 0
    fields = (
        "label",
        "credential_type",
        "username",
        "password",
        "api_key",
        "extra_config",
        "is_active",
    )


class SupplierScraperConfigInline(admin.StackedInline[SupplierScraperConfig, Client]):
    model = SupplierScraperConfig
    form = SupplierScraperConfigAdminForm
    formset = SupplierScraperConfigInlineFormSet
    extra = 0
    max_num = 1
    fields = ("scraper_class", "portal_url", "is_enabled", "active_credential")


class ClientAdmin(admin.ModelAdmin[Client]):
    list_display = ("name", "is_supplier", "email")
    list_filter = ("is_supplier",)
    search_fields = ("name", "email")
    inlines = (SupplierCredentialInline, SupplierScraperConfigInline)


class SupplierAdmin(ClientAdmin):
    def get_queryset(self, request: HttpRequest) -> QuerySet[Client]:
        return super().get_queryset(request).filter(is_supplier=True)


@admin.register(SupplierCredential)
class SupplierCredentialAdmin(admin.ModelAdmin[SupplierCredential]):
    form = SupplierCredentialAdminForm
    list_display = ("supplier", "label", "credential_type", "is_active")
    list_filter = ("credential_type", "is_active")
    search_fields = ("supplier__name", "label")


@admin.register(SupplierScraperConfig)
class SupplierScraperConfigAdmin(admin.ModelAdmin[SupplierScraperConfig]):
    form = SupplierScraperConfigAdminForm
    list_display = ("supplier", "scraper_class", "portal_url", "is_enabled")
    list_filter = ("is_enabled",)
    search_fields = ("supplier__name", "scraper_class", "portal_url")


admin.site.register(Client, ClientAdmin)
admin.site.register(Supplier, SupplierAdmin)
