"""Read serializers. Amounts are rendered as strings so no client sees a float."""

from rest_framework import serializers

from ..models import BankTransaction, CapitalCall, InvestorEntity, LineItem, Match, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "slug", "name")


class CapitalCallSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)

    class Meta:
        model = CapitalCall
        fields = ("id", "sequence", "label", "call_date", "due_date")


class InvestorEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = InvestorEntity
        fields = ("id", "name")


class LineItemSerializer(serializers.ModelSerializer):
    capital_call = CapitalCallSerializer(read_only=True)
    investor_entity = InvestorEntitySerializer(read_only=True)
    amount_remaining = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = LineItem
        fields = (
            "id",
            "capital_call",
            "investor_entity",
            "expected_wire_reference",
            "amount_called",
            "amount_funded",
            "amount_remaining",
            "status",
        )


class MatchLineItemSerializer(serializers.ModelSerializer):
    """The compact line item shown next to a suggestion in the transaction table."""

    investor_name = serializers.CharField(source="investor_entity.name", read_only=True)
    capital_call = serializers.CharField(source="capital_call.label", read_only=True)
    amount_remaining = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = LineItem
        fields = (
            "id",
            "expected_wire_reference",
            "investor_name",
            "capital_call",
            "amount_called",
            "amount_funded",
            "amount_remaining",
            "status",
        )


class MatchSerializer(serializers.ModelSerializer):
    line_item = MatchLineItemSerializer(read_only=True)

    class Meta:
        model = Match
        fields = ("id", "status", "amount", "reason", "line_item", "created_at", "decided_at")


class TransactionSerializer(serializers.ModelSerializer):
    matches = MatchSerializer(many=True, read_only=True)
    available_actions = serializers.SerializerMethodField()

    class Meta:
        model = BankTransaction
        fields = (
            "id",
            "date",
            "description",
            "amount",
            "type",
            "bank_reference",
            "status",
            "status_reason",
            "source_line_number",
            "imported_at",
            "matches",
            "available_actions",
            "airtable_sync_status",
            "airtable_record_id",
        )

    def get_available_actions(self, obj: BankTransaction) -> list[str]:
        """What the GP may do with this row, so the UI does not duplicate the rules."""
        actions = []
        if any(match.status == Match.Status.PROPOSED for match in obj.matches.all()):
            actions += ["approve_match", "reject_match"]
        if obj.is_credit and obj.status in {
            BankTransaction.Status.SUGGESTED,
            BankTransaction.Status.NEEDS_REVIEW,
        }:
            actions.append("ignore")
        return actions
