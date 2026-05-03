import uuid

from django.db import models
from django.db.models import Q, UniqueConstraint


class XeroApp(models.Model):
    """A registered Xero app (client_id / client_secret pair).

    In practice an install has one or two rows — Xero's developer portal
    registers up to two apps per integration so credentials can be
    rotated without downtime — but the code does not enforce a hard cap;
    extra rows are inert until activated. Exactly one row is marked
    is_active=True at a time (enforced by a partial unique index). The
    active row's credentials are what every Xero API call uses; tokens
    and quota state are stored alongside the credentials so a swap is a
    single atomic flip.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=64)

    client_id = models.CharField(max_length=128, unique=True)
    client_secret = models.CharField(max_length=256)
    redirect_uri = models.CharField(max_length=512)
    # Xero webhook signing key — set per-app in Xero's developer portal.
    # Empty string means the app cannot verify webhooks; the verifier loops
    # over every non-empty webhook_key and accepts if any HMAC matches, so
    # both apps in a rotation pair must each have their own key set.
    webhook_key = models.CharField(max_length=128, blank=True, default="")

    is_active = models.BooleanField(default=False)

    tenant_id = models.CharField(max_length=100, null=True, blank=True)
    token_type = models.CharField(max_length=50, null=True, blank=True)
    access_token = models.TextField(null=True, blank=True)
    refresh_token = models.TextField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(null=True, blank=True)

    day_remaining = models.IntegerField(null=True, blank=True)
    minute_remaining = models.IntegerField(null=True, blank=True)
    snapshot_at = models.DateTimeField(null=True, blank=True)
    last_429_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["is_active"],
                condition=Q(is_active=True),
                name="xero_app_only_one_active",
            ),
        ]

    def __str__(self) -> str:
        return f"XeroApp({self.label}, client_id={self.client_id[:8]}...)"
