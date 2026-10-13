"""Tenant resolution from the ``X-Organization`` header (assessment Section 4)."""

from rest_framework.exceptions import NotFound

from ..models import Organization
from .exceptions import BadRequest

ORGANIZATION_HEADER = "X-Organization"


def resolve_organization(request) -> Organization:
    """Return the organization named by the header.

    A missing header is a 400; an unknown organization is a 404.
    """
    slug = (request.headers.get(ORGANIZATION_HEADER) or "").strip()
    if not slug:
        raise BadRequest(f"The {ORGANIZATION_HEADER} header is required.")
    try:
        return Organization.objects.get(slug=slug.lower())
    except Organization.DoesNotExist:
        raise NotFound(f"Unknown organization {slug!r}.") from None


class OrganizationScopedMixin:
    """Resolves the tenant before the handler runs and exposes ``self.organization``.

    Views must build every queryset from ``self.organization``, which is why a
    record belonging to another organization comes back as a 404, never a 403:
    it is simply not in the queryset.
    """

    @property
    def organization(self) -> Organization:
        if not hasattr(self, "_organization"):
            self._organization = resolve_organization(self.request)
        return self._organization

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.organization  # fail fast with 400/404 before any work happens
