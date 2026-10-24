"""The UI dictionary, public because the sign-in page needs it."""
from __future__ import annotations

from flask import Blueprint
from pydantic import RootModel

from illumio_ops.domain.values import Language
from illumio_ops.i18n import dictionary
from illumio_ops.web.contract import ApiFailure, api_route, operation


class Dictionary(RootModel[dict[str, str]]):
    pass


OP_DICTIONARY = operation("i18n.dictionary", "GET", "/api/i18n/<lang>", None, Dictionary)

bp = Blueprint("i18n", __name__)


@api_route(bp, OP_DICTIONARY)
def get_dictionary(lang: str) -> Dictionary:
    try:
        language = Language(lang)
    except ValueError:
        raise ApiFailure(404, "not_found", "err_not_found") from None
    return Dictionary(dictionary(language))
