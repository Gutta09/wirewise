"""Thin views: resolve the tenant, call a service, serialize the result."""

from django.conf import settings
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import BankTransaction, LineItem, Match, Organization
from ..services import actions, importer
from ..services.summaries import summary_to_dict
from .exceptions import BadRequest, Conflict
from .organizations import OrganizationScopedMixin
from .serializers import (
    LineItemSerializer,
    MatchSerializer,
    OrganizationSerializer,
    TransactionSerializer,
)


class OrganizationListView(ListAPIView):
    """The organization switcher. Deliberately not scoped: it only lists slugs and names."""

    serializer_class = OrganizationSerializer
    queryset = Organization.objects.all()


class TransactionListView(OrganizationScopedMixin, ListAPIView):
    serializer_class = TransactionSerializer

    def get_queryset(self):
        queryset = (
            BankTransaction.objects.filter(organization=self.organization)
            .prefetch_related("matches__line_item__investor_entity", "matches__line_item__capital_call")
            .order_by("-date", "-id")
        )
        requested_status = self.request.query_params.get("status")
        if requested_status:
            queryset = queryset.filter(status=requested_status)
        return queryset


class LineItemListView(OrganizationScopedMixin, ListAPIView):
    serializer_class = LineItemSerializer

    def get_queryset(self):
        return (
            LineItem.objects.filter(organization=self.organization)
            .select_related("capital_call", "investor_entity")
            .order_by("capital_call__sequence", "expected_wire_reference")
        )


class ImportView(OrganizationScopedMixin, APIView):
    """``POST /api/imports`` with a ``file`` part: the GP's CSV upload."""

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise BadRequest("Attach the bank statement CSV as the 'file' field.")
        limit = settings.IMPORT_MAX_UPLOAD_BYTES
        if upload.size and upload.size > limit:
            raise BadRequest(f"The file is larger than the {limit // (1024 * 1024)} MB limit.")

        try:
            summary = importer.import_statement(self.organization, upload.read())
        except IntegrityError:
            # Two uploads of the same statement at the same moment.
            raise Conflict(
                "Another import of these bank references is in progress. Please retry."
            ) from None
        return Response(summary_to_dict(summary), status=status.HTTP_201_CREATED)


class MatchActionView(OrganizationScopedMixin, APIView):
    """Shared lookup for the two match actions."""

    def get_match(self, pk) -> Match:
        return get_object_or_404(
            Match.objects.filter(organization=self.organization).select_related(
                "transaction", "line_item__investor_entity"
            ),
            pk=pk,
        )


class MatchApproveView(MatchActionView):
    def post(self, request, pk):
        match = actions.approve_match(self.get_match(pk))
        return Response(_match_payload(match))


class MatchRejectView(MatchActionView):
    def post(self, request, pk):
        match = actions.reject_match(self.get_match(pk))
        return Response(_match_payload(match))


class TransactionIgnoreView(OrganizationScopedMixin, APIView):
    def post(self, request, pk):
        transaction = get_object_or_404(
            BankTransaction.objects.filter(organization=self.organization), pk=pk
        )
        transaction = actions.ignore_transaction(transaction)
        return Response(TransactionSerializer(transaction).data)


def _match_payload(match: Match) -> dict:
    """Return the decided match plus its refreshed transaction, so the UI can patch state."""
    match.transaction.refresh_from_db()
    return {
        "match": MatchSerializer(match).data,
        "transaction": TransactionSerializer(match.transaction).data,
        "line_item": LineItemSerializer(
            LineItem.objects.select_related("capital_call", "investor_entity").get(
                pk=match.line_item_id
            )
        ).data,
    }
