"""Staff company management — durable store on office server, Shopify metafield sync on Render."""

from __future__ import annotations

import logging
import time

from scripts.company_store import (  # type: ignore
    add_member as store_add_member,
    add_note as store_add_note,
    create_company as store_create_company,
    delete_note as store_delete_note,
    delete_company as store_delete_company,
    get_company as store_get_company,
    list_companies as store_list_companies,
    remove_member as store_remove_member,
    update_company_name,
)
from scripts.Customers import (  # type: ignore
    _fetch_single_customer,
    clear_customer_company_link,
    get_customers_id_map,
    invalidate_customers_cache,
    set_customer_company_link,
)

logger = logging.getLogger(__name__)

_COMPANIES_LIST_CACHE: dict | None = None
_COMPANIES_LIST_CACHE_AT = 0.0
_COMPANIES_LIST_CACHE_TTL = 30  # seconds


def invalidate_companies_cache() -> None:
    global _COMPANIES_LIST_CACHE, _COMPANIES_LIST_CACHE_AT
    _COMPANIES_LIST_CACHE = None
    _COMPANIES_LIST_CACHE_AT = 0.0

try:
    from scripts import office_api  # type: ignore
    from scripts.office_api import OfficeApiError  # type: ignore
except Exception:  # pragma: no cover
    office_api = None

    class OfficeApiError(Exception):
        pass


def _office_companies_available() -> bool:
    return office_api is not None and bool(getattr(office_api, "OFFICE_API_URL", None))


def _company_from_office_result(result: dict) -> dict:
    if not isinstance(result, dict):
        return {}
    if isinstance(result.get("company"), dict):
        return result["company"]
    return result


def _load_companies_list() -> list[dict]:
    if _office_companies_available():
        try:
            data = office_api.list_companies()
            return list(data.get("companies") or [])
        except Exception as exc:
            logger.warning("Companies: Office API list failed, using local store (%s)", exc)
    return store_list_companies()


def _load_company(company_id: str) -> dict | None:
    cid = (company_id or "").strip()
    if not cid:
        return None
    if _office_companies_available():
        try:
            return office_api.get_company(cid)
        except OfficeApiError as exc:
            if "not found" in str(exc).lower():
                return None
            logger.warning("Companies: Office API get failed, using local store (%s)", exc)
        except Exception as exc:
            logger.warning("Companies: Office API get failed, using local store (%s)", exc)
    return store_get_company(cid)


def _note_from_company(company: dict, note_id) -> dict:
    notes = company.get("notes") or []
    if note_id is not None:
        for note in notes:
            if str(note.get("id")) == str(note_id):
                return dict(note)
    return dict(notes[0]) if notes else {}


def _enrich_members(company: dict) -> dict:
    customer_map = get_customers_id_map()
    members_out = []
    for member in company.get("members") or []:
        customer_id = str(member.get("customer_id") or "")
        info = {"customer_id": customer_id, "added_at": member.get("added_at") or ""}
        cached = customer_map.get(customer_id)
        if cached:
            info["name"] = cached.get("name") or ""
            info["email"] = cached.get("email") or ""
        else:
            try:
                customer = _fetch_single_customer(customer_id)
                info["name"] = customer.get("name") or ""
                info["email"] = customer.get("email") or ""
            except Exception:
                info["name"] = ""
                info["email"] = ""
        members_out.append(info)
    out = dict(company)
    out["members"] = members_out
    if "member_ids" not in out and members_out:
        out["member_ids"] = [m["customer_id"] for m in members_out]
    if "member_count" not in out:
        out["member_count"] = len(members_out)
    return out


def get_companies_overview(*, refresh: bool = False) -> dict:
    global _COMPANIES_LIST_CACHE, _COMPANIES_LIST_CACHE_AT

    now = time.time()
    if (
        not refresh
        and _COMPANIES_LIST_CACHE is not None
        and (now - _COMPANIES_LIST_CACHE_AT) < _COMPANIES_LIST_CACHE_TTL
    ):
        return _COMPANIES_LIST_CACHE

    companies = _load_companies_list()
    result = {"success": True, "companies": companies, "total": len(companies)}
    _COMPANIES_LIST_CACHE = result
    _COMPANIES_LIST_CACHE_AT = now
    return result


def get_company_detail(company_id: str) -> dict:
    company = _load_company(company_id)
    if not company:
        return {"success": False, "error": "Company not found"}
    return {"success": True, "company": _enrich_members(company)}


def create_company(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        return {"success": False, "error": "Company name is required"}
    if _office_companies_available():
        try:
            result = office_api.create_company(name)
            company = _company_from_office_result(result)
            invalidate_companies_cache()
            return {"success": True, "company": company}
        except OfficeApiError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("Companies: office create failed")
            return {"success": False, "error": str(exc)}
    try:
        company = store_create_company(name)
        invalidate_companies_cache()
        return {"success": True, "company": company}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


def rename_company(company_id: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        return {"success": False, "error": "Company name is required"}
    try:
        if _office_companies_available():
            result = office_api.rename_company(company_id, name)
            company = _company_from_office_result(result)
        else:
            company = update_company_name(company_id, name)
        for member in company.get("members") or []:
            customer_id = str(member.get("customer_id") or "")
            if customer_id:
                set_customer_company_link(customer_id, company_id, name)
        updated = _load_company(company_id) or company
        invalidate_companies_cache()
        invalidate_customers_cache()
        return {"success": True, "company": _enrich_members(updated)}
    except OfficeApiError as exc:
        return {"success": False, "error": str(exc)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def add_company_member(company_id: str, customer_id: str) -> dict:
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        return {"success": False, "error": "Customer id is required"}
    try:
        company = _load_company(company_id)
        if not company:
            return {"success": False, "error": "Company not found"}
        _fetch_single_customer(customer_id)
        if _office_companies_available():
            result = office_api.add_company_member(company_id, customer_id)
            company = _company_from_office_result(result)
        else:
            store_add_member(company_id, customer_id)
            company = store_get_company(company_id) or {}
        set_customer_company_link(customer_id, company_id, company.get("name") or "")
        updated = _load_company(company_id) or company
        invalidate_companies_cache()
        invalidate_customers_cache()
        return {"success": True, "company": _enrich_members(updated)}
    except OfficeApiError as exc:
        return {"success": False, "error": str(exc)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def remove_company_member(company_id: str, customer_id: str) -> dict:
    try:
        if _office_companies_available():
            result = office_api.remove_company_member(company_id, customer_id)
            company = _company_from_office_result(result)
        else:
            store_remove_member(company_id, customer_id)
            company = store_get_company(company_id)
            if not company:
                return {"success": False, "error": "Company not found"}
        clear_customer_company_link(customer_id)
        updated = _load_company(company_id) or company
        invalidate_companies_cache()
        invalidate_customers_cache()
        return {"success": True, "company": _enrich_members(updated or {})}
    except OfficeApiError as exc:
        return {"success": False, "error": str(exc)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def add_company_note(company_id: str, *, author: str, body: str, note_date: str = "") -> dict:
    try:
        if _office_companies_available():
            result = office_api.add_company_note(
                company_id,
                author=author,
                body=body,
                note_date=note_date,
            )
            company = _company_from_office_result(result)
            note = _note_from_company(company, result.get("note_id"))
            invalidate_companies_cache()
            return {"success": True, "note": note}
        note = store_add_note(company_id, author=author, body=body, note_date=note_date)
        invalidate_companies_cache()
        return {"success": True, "note": note}
    except OfficeApiError as exc:
        return {"success": False, "error": str(exc)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


def delete_company_note(company_id: str, note_id: str) -> dict:
    note_id = str(note_id or "").strip()
    if not note_id:
        return {"success": False, "error": "Note id is required"}
    try:
        if _office_companies_available():
            result = office_api.delete_company_note(company_id, note_id)
            company = _company_from_office_result(result)
            updated = company if company.get("id") else (_load_company(company_id) or {})
            invalidate_companies_cache()
            return {"success": True, "company": _enrich_members(updated)}
        store_delete_note(company_id, note_id)
        updated = _load_company(company_id)
        if not updated:
            return {"success": False, "error": "Company not found"}
        invalidate_companies_cache()
        return {"success": True, "company": _enrich_members(updated)}
    except OfficeApiError as exc:
        return {"success": False, "error": str(exc)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


def delete_company(company_id: str) -> dict:
    """Delete a company record only — does not modify Shopify customer metafields."""
    cid = (company_id or "").strip()
    if not cid:
        return {"success": False, "error": "Company id is required"}
    try:
        if _office_companies_available():
            office_api.delete_company(cid)
        else:
            store_delete_company(cid)
        invalidate_companies_cache()
        return {"success": True, "company_id": cid}
    except OfficeApiError as exc:
        return {"success": False, "error": str(exc)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
