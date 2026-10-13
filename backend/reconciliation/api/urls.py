from django.urls import path

from . import views

urlpatterns = [
    path("organizations", views.OrganizationListView.as_view(), name="organization-list"),
    path("transactions", views.TransactionListView.as_view(), name="transaction-list"),
    path(
        "transactions/<int:pk>/ignore",
        views.TransactionIgnoreView.as_view(),
        name="transaction-ignore",
    ),
    path("line-items", views.LineItemListView.as_view(), name="line-item-list"),
    path("imports", views.ImportView.as_view(), name="import-create"),
    path("matches/<int:pk>/approve", views.MatchApproveView.as_view(), name="match-approve"),
    path("matches/<int:pk>/reject", views.MatchRejectView.as_view(), name="match-reject"),
]
