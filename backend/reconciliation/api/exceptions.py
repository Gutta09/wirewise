"""HTTP error mapping. Service-layer errors become status codes in one place."""

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler

from ..services.actions import ActionConflict
from ..services.importer import FileRejected


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The record changed before this action could be applied."


class BadRequest(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The request was not valid."


def exception_handler(exc, context):
    """Translate domain exceptions, then fall back to DRF's own handling."""
    if isinstance(exc, ActionConflict):
        exc = Conflict(str(exc))
    elif isinstance(exc, FileRejected):
        response = drf_exception_handler(BadRequest(exc.message), context)
        if response is not None and exc.missing_columns:
            response.data["missing_columns"] = exc.missing_columns
        return response
    return drf_exception_handler(exc, context)
