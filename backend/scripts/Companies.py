"""Staff company management — link Shopify customers by ID, sync company name metafield."""

from __future__ import annotations

from scripts.company_store import (  # type: ignore
    add_member as store_add_member,
    add_note as store_add_note,
    create_company as store_create_company,
    get_company,
    list_companies,
    remove_member as store_remove_member,
    update_company_name,
)
from scripts.Customers import (  # type: ignore
    _fetch_single_customer,
    set_customer_company_link,
    clear_customer_company_link,
)


def _enrich_members(company: dict) -> dict:
    members_out = []
    for member in company.get("members") or []:
        customer_id = str(member.get("customer_id") or "")
        info = {"customer_id": customer_id, "added_at": member.get("added_at") or ""}
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
    return out


def get_companies_overview() -> dict:
    return {"success": True, "companies": list_companies(), "total": len(list_companies())}


def get_company_detail(company_id: str) -> dict:
    company = get_company(company_id)
    if not company:
        return {"success": False, "error": "Company not found"}
    return {"success": True, "company": _enrich_members(company)}


def create_company(name: str) -> dict:
    try:
        company = store_create_company(name)
        return {"success": True, "company": company}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


def rename_company(company_id: str, name: str) -> dict:
    try:
        name = (name or "").strip()
        company = update_company_name(company_id, name)
        for member in company.get("members") or []:
            customer_id = str(member.get("customer_id") or "")
            if customer_id:
                set_customer_company_link(customer_id, company_id, name)
        updated = get_company(company_id) or company
        return {"success": True, "company": _enrich_members(updated)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}


def add_company_member(company_id: str, customer_id: str) -> dict:
    try:
        company = get_company(company_id)
        if not company:
            return {"success": False, "error": "Company not found"}
        customer_id = str(customer_id or "").strip()
        if not customer_id:
            return {"success": False, "error": "Customer id is required"}
        _fetch_single_customer(customer_id)
        store_add_member(company_id, customer_id)
        set_customer_company_link(customer_id, company_id, company["name"])
        updated = get_company(company_id) or {}
        return {"success": True, "company": _enrich_members(updated)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def remove_company_member(company_id: str, customer_id: str) -> dict:
    try:
        store_remove_member(company_id, customer_id)
        clear_customer_company_link(customer_id)
        company = get_company(company_id)
        if not company:
            return {"success": False, "error": "Company not found"}
        return {"success": True, "company": _enrich_members(company)}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def add_company_note(company_id: str, *, author: str, body: str, note_date: str = "") -> dict:
    try:
        note = store_add_note(company_id, author=author, body=body, note_date=note_date)
        return {"success": True, "note": note}
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
