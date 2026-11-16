"""Unit tests for CRM Export REST API endpoints and integration services."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.main import (
    app,
    check_crm_connection,
    create_destination,
    delete_destination,
    export_leads_to_crm,
    get_crm_logs,
    get_destination_by_id,
    get_destinations,
    update_destination,
)
from app.models import (
    CRMDestinationCreate,
    CRMDestinationUpdate,
    CRMExportRequest,
    CRMTestConnectionRequest,
)
from app.services.crm_service import (
    _extract_domain,
    build_request_headers,
    export_city_leads_to_all_destinations,
    export_leads_dynamic,
    export_leads_to_destination,
    format_leads_payload,
    send_payload_to_crm,
    test_crm_connection,
    trigger_auto_crm_sync,
)
from app.services.persistence import (
    delete_crm_destination,
    get_crm_destination,
    get_crm_destinations_for_city,
    list_crm_destinations,
    list_crm_export_logs,
    log_crm_export,
    save_crm_destination,
    update_crm_destination,
)


class TestCRMPersistenceAndService(unittest.TestCase):
    def setUp(self):
        self.test_dest_id = "test_dest_123"
        self.dest_data = {
            "destination_id": self.test_dest_id,
            "customer_name": "Acme Corp",
            "crm_type": "webhook",
            "target_url": "https://webhook.site/test-uuid",
            "api_key": "secret-key-123",
            "city_filter": "Delhi, Mumbai",
            "headers": {"X-Custom-Auth": "AcmeToken"},
            "field_mapping": {"company_name": "Account_Name", "phone": "Mobile"},
            "auto_sync": True,
            "is_active": True,
        }

    def tearDown(self):
        delete_crm_destination(self.test_dest_id)

    def test_save_and_get_crm_destination(self):
        saved = save_crm_destination(**self.dest_data)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["destination_id"], self.test_dest_id)
        self.assertEqual(saved["customer_name"], "Acme Corp")
        self.assertEqual(saved["crm_type"], "webhook")
        self.assertEqual(saved["city_filter"], "Delhi, Mumbai")
        self.assertTrue(saved["has_api_key"])
        self.assertEqual(saved["headers"], {"X-Custom-Auth": "AcmeToken"})
        self.assertEqual(saved["field_mapping"], {"company_name": "Account_Name", "phone": "Mobile"})
        self.assertTrue(saved["auto_sync"])
        self.assertTrue(saved["is_active"])

        fetched = get_crm_destination(self.test_dest_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["customer_name"], "Acme Corp")

    def test_update_and_delete_crm_destination(self):
        save_crm_destination(**self.dest_data)
        updated = update_crm_destination(
            self.test_dest_id,
            {"customer_name": "Acme International", "auto_sync": False},
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["customer_name"], "Acme International")
        self.assertFalse(updated["auto_sync"])

        deleted = delete_crm_destination(self.test_dest_id)
        self.assertTrue(deleted)
        self.assertIsNone(get_crm_destination(self.test_dest_id))

    def test_city_filter_matching(self):
        save_crm_destination(**self.dest_data)

        delhi_dests = get_crm_destinations_for_city("delhi", auto_sync_only=True)
        self.assertTrue(any(d["destination_id"] == self.test_dest_id for d in delhi_dests))

        mumbai_dests = get_crm_destinations_for_city("Mumbai", auto_sync_only=True)
        self.assertTrue(any(d["destination_id"] == self.test_dest_id for d in mumbai_dests))

        bengaluru_dests = get_crm_destinations_for_city("Bengaluru", auto_sync_only=True)
        self.assertFalse(any(d["destination_id"] == self.test_dest_id for d in bengaluru_dests))

    def test_wildcard_city_filter(self):
        wildcard_id = "test_wildcard_dest"
        try:
            save_crm_destination(
                destination_id=wildcard_id,
                customer_name="Global Ingest",
                crm_type="generic_rest",
                target_url="https://api.crm.com/leads",
                city_filter="*",
                auto_sync=True,
                is_active=True,
            )
            any_city_dests = get_crm_destinations_for_city("Kolkata", auto_sync_only=True)
            self.assertTrue(any(d["destination_id"] == wildcard_id for d in any_city_dests))
        finally:
            delete_crm_destination(wildcard_id)

    def test_logging_and_retrieval(self):
        log_id = log_crm_export(
            destination_id=self.test_dest_id,
            customer_name="Acme Corp",
            city="Delhi",
            crm_type="webhook",
            leads_count=15,
            status="success",
            status_code=200,
            response_summary='{"ok": true}',
            trigger_type="test",
        )
        self.assertGreater(log_id, 0)

        logs = list_crm_export_logs(city="Delhi", limit=10)
        self.assertTrue(any(l["log_id"] == log_id for l in logs))


class TestCRMAdaptersAndPayloads(unittest.TestCase):
    def setUp(self):
        self.sample_leads = [
            {
                "company_name": "Vertex Media",
                "website": "https://www.vertexmedia.in",
                "phone": "+919876543210",
                "email": "contact@vertexmedia.in",
                "city": "Delhi",
                "state": "Delhi",
                "country": "India",
                "sector": "Digital Marketing",
                "services": ["SEO", "PPC", "Content Marketing"],
                "contact_person": "Rahul Sharma",
            }
        ]

    def test_extract_domain(self):
        self.assertEqual(_extract_domain("https://www.vertexmedia.in/about"), "vertexmedia.in")
        self.assertEqual(_extract_domain("http://example.com"), "example.com")
        self.assertEqual(_extract_domain(""), "")

    def test_webhook_payload_format(self):
        payload = format_leads_payload(self.sample_leads, crm_type="webhook", city="Delhi")
        self.assertEqual(payload["event"], "dakini_leads_export")
        self.assertEqual(payload["city"], "Delhi")
        self.assertEqual(payload["total_leads"], 1)
        self.assertEqual(payload["leads"][0]["company_name"], "Vertex Media")

    def test_webhook_field_mapping(self):
        mapping = {"company_name": "lead_name", "phone": "primary_contact"}
        payload = format_leads_payload(self.sample_leads, crm_type="webhook", city="Delhi", field_mapping=mapping)
        lead = payload["leads"][0]
        self.assertIn("lead_name", lead)
        self.assertEqual(lead["lead_name"], "Vertex Media")
        self.assertIn("primary_contact", lead)
        self.assertEqual(lead["primary_contact"], "+919876543210")

    def test_hubspot_payload_format(self):
        payload = format_leads_payload(self.sample_leads, crm_type="hubspot", city="Delhi")
        self.assertIn("inputs", payload)
        self.assertEqual(len(payload["inputs"]), 1)
        props = payload["inputs"][0]["properties"]
        self.assertEqual(props["name"], "Vertex Media")
        self.assertEqual(props["domain"], "vertexmedia.in")
        self.assertEqual(props["phone"], "+919876543210")
        self.assertEqual(props["city"], "Delhi")

    def test_zoho_payload_format(self):
        payload = format_leads_payload(self.sample_leads, crm_type="zoho", city="Delhi")
        self.assertIn("data", payload)
        self.assertEqual(len(payload["data"]), 1)
        record = payload["data"][0]
        self.assertEqual(record["Company"], "Vertex Media")
        self.assertEqual(record["Phone"], "+919876543210")
        self.assertEqual(record["Last_Name"], "Sharma")
        self.assertEqual(record["City"], "Delhi")

    def test_build_request_headers(self):
        h_hub = build_request_headers("hubspot", api_key="pat-na1-12345")
        self.assertEqual(h_hub["Authorization"], "Bearer pat-na1-12345")

        h_zoho = build_request_headers("zoho", api_key="1000.abc123xyz")
        self.assertEqual(h_zoho["Authorization"], "Zoho-oauthtoken 1000.abc123xyz")

        h_custom = build_request_headers("webhook", custom_headers={"X-Agency": "Dakini"})
        self.assertEqual(h_custom["X-Agency"], "Dakini")


class TestCRMAPIRoutes(unittest.TestCase):
    def setUp(self):
        self.created_dest_ids = []

    def tearDown(self):
        for did in self.created_dest_ids:
            delete_crm_destination(did)

    def test_destination_crud_endpoints(self):
        create_req = CRMDestinationCreate(
            customer_name="Beta CRM Client",
            crm_type="generic_rest",
            target_url="https://customer-crm.com/api/v1/leads",
            api_key="api-token-999",
            city_filter="Delhi",
            auto_sync=True,
            is_active=True,
        )
        created = create_destination(create_req)
        dest_id = created["destination_id"]
        self.created_dest_ids.append(dest_id)

        self.assertEqual(created["customer_name"], "Beta CRM Client")
        self.assertEqual(created["city_filter"], "Delhi")
        self.assertTrue(created["has_api_key"])

        # GET by ID
        fetched = get_destination_by_id(dest_id)
        self.assertEqual(fetched["destination_id"], dest_id)

        # PUT update
        update_req = CRMDestinationUpdate(customer_name="Beta CRM Renamed")
        updated = update_destination(dest_id, update_req)
        self.assertEqual(updated["customer_name"], "Beta CRM Renamed")

        # GET list
        all_dests = get_destinations(city="Delhi")
        self.assertTrue(any(d["destination_id"] == dest_id for d in all_dests))

        # DELETE
        del_resp = delete_destination(dest_id)
        self.assertTrue(del_resp["success"])
        with self.assertRaises(HTTPException):
            get_destination_by_id(dest_id)

    @patch("requests.post")
    def test_export_leads_by_destination_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true, "imported": 5}'
        mock_post.return_value = mock_resp

        create_req = CRMDestinationCreate(
            customer_name="Export Target Client",
            crm_type="webhook",
            target_url="https://webhook.site/mock-target",
            city_filter="Delhi",
            auto_sync=True,
        )
        created = create_destination(create_req)
        dest_id = created["destination_id"]
        self.created_dest_ids.append(dest_id)

        export_req = CRMExportRequest(
            city="Delhi",
            destination_id=dest_id,
            limit=5,
        )
        result = export_leads_to_crm(export_req)
        self.assertTrue(result["success"])
        self.assertEqual(result["destination_id"], dest_id)
        self.assertEqual(result["status_code"], 200)

    @patch("requests.post")
    def test_export_leads_dynamic_one_off(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = '{"created": 10}'
        mock_post.return_value = mock_resp

        export_req = CRMExportRequest(
            city="Delhi",
            target_url="https://dynamic-webhook.org/leads",
            crm_type="webhook",
            limit=10,
        )
        result = export_leads_to_crm(export_req)
        self.assertTrue(result["success"])
        self.assertEqual(result["city"], "Delhi")
        self.assertEqual(result["status_code"], 201)

    @patch("requests.post")
    def test_test_connection_endpoint(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"pong": true}'
        mock_post.return_value = mock_resp

        test_req = CRMTestConnectionRequest(
            target_url="https://crm.test/ping",
            crm_type="webhook",
        )
        diag = check_crm_connection(test_req)
        self.assertTrue(diag["connected"])
        self.assertEqual(diag["status_code"], 200)


if __name__ == "__main__":
    unittest.main()
