"""CRM Export and Integration Service for Dakini Geographical Discovery System.

Supports Universal Webhook, Generic REST endpoints, and pre-built adapters for HubSpot and Zoho CRM.
Handles city-specific lead exports, custom field mappings, automated post-scrape synchronization,
connection diagnostics, and audit logging.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from app.config import DATABASE_PATH
from app.services.persistence import (
    get_crm_destination,
    get_crm_destinations_for_city,
    list_crm_destinations,
    log_crm_export,
)

logger = logging.getLogger("dakini.crm")


def _extract_domain(url: str) -> str:
    """Extract clean network domain from website URL."""
    if not url:
        return ""
    try:
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def fetch_leads_for_export(
    city: str,
    limit: int = 100,
    phone_only: bool = False,
    category: str = "",
    db_path: str = DATABASE_PATH,
) -> List[Dict[str, Any]]:
    """Retrieve city-specific business leads from SQLite database formatted for CRM export."""
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        clean_city = city.strip()
        query = "SELECT * FROM companies WHERE 1=1"
        params: list[Any] = []

        if clean_city:
            query += " AND LOWER(city) = LOWER(?)"
            params.append(clean_city)

        if phone_only:
            query += " AND phone IS NOT NULL AND phone != ''"

        if category.strip():
            query += " AND LOWER(industry_category) = LOWER(?)"
            params.append(category.strip())

        query += " ORDER BY (phone IS NOT NULL AND phone != '') DESC, updated_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        leads: List[Dict[str, Any]] = []

        for row in rows:
            item = dict(row)
            # Parse JSON services if serialized as string
            services = item.get("services")
            if isinstance(services, str):
                try:
                    item["services"] = json.loads(services)
                except Exception:
                    item["services"] = [services] if services else []
            elif not isinstance(services, list):
                item["services"] = []

            # Clean internal or non-export fields
            item.pop("evidence_items", None)
            leads.append(item)

        return leads
    finally:
        conn.close()


def format_leads_payload(
    leads: List[Dict[str, Any]],
    crm_type: str,
    city: str,
    field_mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Format leads list into target CRM schema (Universal Webhook, HubSpot, or Zoho)."""
    norm_type = (crm_type or "webhook").strip().lower()

    if norm_type == "hubspot":
        # HubSpot Companies Batch API Schema
        # https://developers.hubspot.com/docs/api/crm/companies
        inputs = []
        for lead in leads:
            services_str = ", ".join(lead.get("services") or [])
            desc = f"Dakini Lead Discovery ({city})"
            if services_str:
                desc += f" - Services: {services_str}"
            props = {
                "name": lead.get("company_name", ""),
                "domain": _extract_domain(lead.get("website", "")),
                "website": lead.get("website", ""),
                "phone": lead.get("phone", ""),
                "city": lead.get("city") or city,
                "state": lead.get("state", ""),
                "country": lead.get("country", "India"),
                "industry": lead.get("industry_subcategory") or lead.get("industry_category", ""),
                "description": desc,
            }
            if field_mapping:
                for src_key, target_key in field_mapping.items():
                    if src_key in lead and lead[src_key]:
                        props[target_key] = lead[src_key]
            inputs.append({"properties": props})
        return {"inputs": inputs}

    elif norm_type == "zoho":
        # Zoho CRM Leads API Schema
        # https://www.zoho.com/crm/developer/docs/api/v2/insert-records.html
        records = []
        for lead in leads:
            company_name = lead.get("company_name", "Unknown Business")
            contact_name = lead.get("contact_person") or "Lead Contact"
            last_name = contact_name.split()[-1] if " " in contact_name else contact_name
            services_str = ", ".join(lead.get("services") or [])

            record: Dict[str, Any] = {
                "Company": company_name,
                "Last_Name": last_name,
                "Phone": lead.get("phone", ""),
                "Email": lead.get("email", ""),
                "Website": lead.get("website", ""),
                "City": lead.get("city") or city,
                "State": lead.get("state", ""),
                "Country": lead.get("country", "India"),
                "Lead_Source": "Dakini AI Geographical Scraping",
                "Description": f"Discovered by Dakini AI in {city}. Services: {services_str}",
            }
            if field_mapping:
                for src_key, target_key in field_mapping.items():
                    if src_key in lead and lead[src_key]:
                        record[target_key] = lead[src_key]
            records.append(record)
        return {"data": records}

    else:
        # Universal Webhook / Generic REST Format
        formatted_leads = []
        for lead in leads:
            if field_mapping:
                mapped_lead = {}
                for k, v in lead.items():
                    target_k = field_mapping.get(k, k)
                    mapped_lead[target_k] = v
                formatted_leads.append(mapped_lead)
            else:
                formatted_leads.append(lead)

        return {
            "event": "dakini_leads_export",
            "source": "Dakini AI Geographical Scraping System",
            "city": city,
            "total_leads": len(formatted_leads),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "leads": formatted_leads,
        }


def build_request_headers(
    crm_type: str,
    api_key: str = "",
    custom_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Construct HTTP headers including authentication and User-Agent."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Dakini-AI-CRM-Exporter/2.5",
    }

    norm_type = (crm_type or "").strip().lower()
    clean_key = (api_key or "").strip()

    if clean_key:
        if norm_type == "zoho":
            headers["Authorization"] = f"Zoho-oauthtoken {clean_key}"
        elif clean_key.lower().startswith(("bearer ", "token ", "apikey ")):
            headers["Authorization"] = clean_key
        else:
            headers["Authorization"] = f"Bearer {clean_key}"

    if custom_headers:
        headers.update(custom_headers)

    return headers


def send_payload_to_crm(
    target_url: str,
    payload: Any,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 15.0,
    max_retries: int = 2,
) -> Tuple[bool, int, str, str]:
    """
    Dispatch HTTP POST payload to customer CRM endpoint with retry handling.
    Returns: (success, status_code, response_summary, error_message)
    """
    clean_url = target_url.strip()
    if not clean_url:
        return False, 0, "", "Target URL is required."

    last_error = ""
    status_code = 0
    response_body = ""

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                clean_url,
                json=payload,
                headers=headers or {},
                timeout=timeout,
            )
            status_code = resp.status_code
            response_body = resp.text[:500] if resp.text else ""

            if 200 <= status_code < 300:
                return True, status_code, response_body, ""

            last_error = f"HTTP {status_code}: {response_body}"
            # Retry on server errors or rate limiting (5xx or 429)
            if status_code in (429, 502, 503, 504) and attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            break

        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = f"Network Error: {exc}"
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
        except Exception as exc:
            last_error = f"Request Exception: {exc}"
            break

    return False, status_code, response_body, last_error


def export_leads_to_destination(
    destination_id: Optional[str] = None,
    destination: Optional[Dict[str, Any]] = None,
    city: str = "",
    leads: Optional[List[Dict[str, Any]]] = None,
    limit: int = 100,
    phone_only: bool = False,
    category: str = "",
    trigger_type: str = "manual",
    db_path: str = DATABASE_PATH,
) -> Dict[str, Any]:
    """Export city leads to a registered or resolved CRM destination."""
    now_iso = datetime.now(timezone.utc).isoformat()

    dest = destination
    if not dest and destination_id:
        dest = get_crm_destination(destination_id, db_path=db_path)

    if not dest:
        error_msg = f"CRM Destination '{destination_id}' not found."
        log_crm_export(
            destination_id=destination_id or "",
            customer_name="",
            city=city,
            crm_type="unknown",
            leads_count=0,
            status="failed",
            status_code=404,
            error_message=error_msg,
            trigger_type=trigger_type,
            db_path=db_path,
        )
        return {
            "success": False,
            "destination_id": destination_id,
            "customer_name": None,
            "crm_type": "unknown",
            "target_url": "",
            "city": city,
            "leads_count": 0,
            "status_code": 404,
            "response_summary": None,
            "error": error_msg,
            "timestamp": now_iso,
        }

    cust_name = dest.get("customer_name", "Customer CRM")
    crm_type = dest.get("crm_type", "webhook")
    target_url = dest.get("target_url", "")
    api_key = dest.get("api_key", "")
    headers_cfg = dest.get("headers") or {}
    mapping_cfg = dest.get("field_mapping") or {}

    # If leads not supplied, fetch from database for the specified city
    export_leads = leads
    if export_leads is None:
        export_leads = fetch_leads_for_export(
            city=city,
            limit=limit,
            phone_only=phone_only,
            category=category,
            db_path=db_path,
        )

    # Format payload according to target CRM adapter
    payload = format_leads_payload(
        leads=export_leads,
        crm_type=crm_type,
        city=city,
        field_mapping=mapping_cfg,
    )

    req_headers = build_request_headers(
        crm_type=crm_type,
        api_key=api_key,
        custom_headers=headers_cfg,
    )

    success, code, body, err = send_payload_to_crm(
        target_url=target_url,
        payload=payload,
        headers=req_headers,
    )

    # Log export record to audit trail
    log_crm_export(
        destination_id=dest.get("destination_id", destination_id or ""),
        customer_name=cust_name,
        city=city,
        crm_type=crm_type,
        leads_count=len(export_leads),
        status="success" if success else "failed",
        status_code=code,
        response_summary=body,
        error_message=err,
        trigger_type=trigger_type,
        db_path=db_path,
    )

    return {
        "success": success,
        "destination_id": dest.get("destination_id", destination_id),
        "customer_name": cust_name,
        "crm_type": crm_type,
        "target_url": target_url,
        "city": city,
        "leads_count": len(export_leads),
        "status_code": code,
        "response_summary": body,
        "error": err if not success else None,
        "timestamp": now_iso,
    }


def export_leads_dynamic(
    city: str,
    target_url: str,
    crm_type: str = "webhook",
    api_key: str = "",
    headers: Optional[Dict[str, str]] = None,
    field_mapping: Optional[Dict[str, str]] = None,
    leads: Optional[List[Dict[str, Any]]] = None,
    limit: int = 100,
    phone_only: bool = False,
    category: str = "",
    trigger_type: str = "api_dynamic",
    db_path: str = DATABASE_PATH,
) -> Dict[str, Any]:
    """Execute a one-off export without pre-registering a customer destination in the database."""
    temp_destination = {
        "destination_id": "dynamic",
        "customer_name": "One-off Export",
        "crm_type": crm_type,
        "target_url": target_url,
        "api_key": api_key,
        "headers": headers or {},
        "field_mapping": field_mapping or {},
    }
    return export_leads_to_destination(
        destination=temp_destination,
        city=city,
        leads=leads,
        limit=limit,
        phone_only=phone_only,
        category=category,
        trigger_type=trigger_type,
        db_path=db_path,
    )


def export_city_leads_to_all_destinations(
    city: str,
    leads: Optional[List[Dict[str, Any]]] = None,
    limit: int = 100,
    phone_only: bool = False,
    category: str = "",
    trigger_type: str = "manual_broadcast",
    db_path: str = DATABASE_PATH,
) -> List[Dict[str, Any]]:
    """Broadcast city leads to all active destinations configured for this city."""
    destinations = get_crm_destinations_for_city(city=city, auto_sync_only=False, db_path=db_path)
    results = []
    for dest in destinations:
        res = export_leads_to_destination(
            destination=dest,
            city=city,
            leads=leads,
            limit=limit,
            phone_only=phone_only,
            category=category,
            trigger_type=trigger_type,
            db_path=db_path,
        )
        results.append(res)
    return results


def trigger_auto_crm_sync(
    city: str,
    leads: Optional[List[Dict[str, Any]]] = None,
    run_id: str = "",
    db_path: str = DATABASE_PATH,
) -> None:
    """
    Automated background hook invoked upon scrape completion to push city-specific leads
    to all active customer CRM destinations subscribed to this city.
    Runs asynchronously to ensure scraping pipeline response is not blocked.
    """
    def _worker():
        try:
            destinations = get_crm_destinations_for_city(city=city, auto_sync_only=True, db_path=db_path)
            if not destinations:
                return

            print(
                f"[crm-auto-sync] Scrape completed for {city} (run={run_id}). "
                f"Dispatching leads to {len(destinations)} active customer CRM destination(s)...",
                flush=True,
            )

            for dest in destinations:
                try:
                    res = export_leads_to_destination(
                        destination=dest,
                        city=city,
                        leads=leads,
                        limit=500,
                        trigger_type="auto_scraper",
                        db_path=db_path,
                    )
                    status_text = "SUCCESS" if res.get("success") else f"FAILED: {res.get('error')}"
                    print(
                        f"[crm-auto-sync] Customer '{dest.get('customer_name')}' -> {dest.get('target_url')}: {status_text}",
                        flush=True,
                    )
                except Exception as exc:
                    print(
                        f"[crm-auto-sync] Error dispatching to customer '{dest.get('customer_name')}': {exc}",
                        flush=True,
                    )
        except Exception as exc:
            logger.exception("Failed in crm auto sync worker: %s", exc)

    thread = threading.Thread(target=_worker, daemon=True, name="crm-auto-sync-thread")
    thread.start()


def test_crm_connection(
    target_url: str,
    crm_type: str = "webhook",
    api_key: str = "",
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Test connection to a customer's CRM endpoint or webhook URL with a lightweight ping payload."""
    ping_payload = {
        "event": "crm_ping",
        "system": "Dakini AI Geographical Scraping & Intelligence",
        "crm_type": crm_type,
        "message": "Connection diagnostic successful. Ready to receive city leads data.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    req_headers = build_request_headers(
        crm_type=crm_type,
        api_key=api_key,
        custom_headers=headers,
    )

    success, code, body, err = send_payload_to_crm(
        target_url=target_url,
        payload=ping_payload,
        headers=req_headers,
        timeout=timeout,
        max_retries=1,
    )

    return {
        "connected": success,
        "status_code": code,
        "response": body,
        "error": err if not success else None,
        "message": "Connection successful" if success else f"Connection test failed: {err}",
    }
