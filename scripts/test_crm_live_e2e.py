"""Live End-to-End Integration Test for CRM & Webhook Dispatch System.

Spawns an in-process HTTP mock CRM server, executes real REST API endpoints,
dispatches real leads from the database, validates payload schemas (HubSpot, Zoho,
Webhook), tests automated background synchronization, and verifies SQLite audit logs.
"""
from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List
from urllib.parse import urlparse

# Ensure repository root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure app is in python path
from app.main import (
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
    export_city_leads_to_all_destinations,
    trigger_auto_crm_sync,
)
from app.services.persistence import (
    delete_crm_destination,
    list_crm_export_logs,
)

# Global store for captured requests at the mock CRM server
CAPTURED_REQUESTS: List[Dict[str, Any]] = []
_LOCK = threading.Lock()


class MockCRMHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass  # Quiet logger for clean test output

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        parsed_body = {}
        try:
            parsed_body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            parsed_body = {"raw": body_bytes.decode("utf-8", errors="replace")}

        req_info = {
            "path": self.path,
            "headers": dict(self.headers),
            "body": parsed_body,
            "timestamp": time.time(),
        }

        with _LOCK:
            CAPTURED_REQUESTS.append(req_info)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        resp_payload = {
            "success": True,
            "message": "Received by Mock CRM Server",
            "received_path": self.path,
            "items_count": len(parsed_body.get("inputs", parsed_body.get("data", parsed_body.get("leads", [])))),
        }
        self.wfile.write(json.dumps(resp_payload).encode("utf-8"))


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def run_live_crm_test() -> bool:
    port = find_free_port()
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, MockCRMHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    print(f"\n=======================================================")
    print(f" LIVE CRM & WEBHOOK SYSTEM INTEGRATION VERIFICATION")
    print(f" Mock Receiver Endpoint: {base_url}")
    print(f"=======================================================\n")

    all_passed = True
    created_dest_ids = []

    try:
        # -----------------------------------------------------------------
        # TEST 1: Diagnostic Ping (/api/crm/test) for All Adapters
        # -----------------------------------------------------------------
        print("[TEST 1] Testing Endpoint Connectivity & Ping (/api/crm/test)...")
        for crm_type in ["webhook", "hubspot", "zoho", "generic_rest"]:
            req = CRMTestConnectionRequest(
                target_url=f"{base_url}/ping/{crm_type}",
                crm_type=crm_type,
                api_key=f"test-token-{crm_type}",
            )
            diag = check_crm_connection(req)
            assert diag["connected"] is True, f"Ping failed for {crm_type}: {diag}"
            assert diag["status_code"] == 200, f"Expected 200, got {diag['status_code']}"
            print(f"  ✓ {crm_type.upper():12s} Ping: CONNECTED (HTTP {diag['status_code']})")

        with _LOCK:
            assert len(CAPTURED_REQUESTS) >= 4, "Mock server did not receive 4 pings"
            # Verify auth headers
            hub_req = next(r for r in CAPTURED_REQUESTS if "/ping/hubspot" in r["path"])
            assert hub_req["headers"].get("Authorization") == "Bearer test-token-hubspot"
            zoho_req = next(r for r in CAPTURED_REQUESTS if "/ping/zoho" in r["path"])
            assert zoho_req["headers"].get("Authorization") == "Zoho-oauthtoken test-token-zoho"
            print("  ✓ Authentication headers properly injected for HubSpot and Zoho CRM")

        # -----------------------------------------------------------------
        # TEST 2: Destination CRUD (/api/crm/destinations)
        # -----------------------------------------------------------------
        print("\n[TEST 2] Testing Destination Registration & Lifecycle CRUD...")
        # 2a. Register HubSpot Destination for Bhubaneswar
        dest_hub = create_destination(CRMDestinationCreate(
            customer_name="Vertex Enterprise (HubSpot)",
            crm_type="hubspot",
            target_url=f"{base_url}/crm/hubspot/companies/batch",
            api_key="pat-na1-987654321",
            city_filter="Bhubaneswar",
            auto_sync=True,
            is_active=True,
        ))
        created_dest_ids.append(dest_hub["destination_id"])
        print(f"  ✓ Created HubSpot destination '{dest_hub['customer_name']}' (ID: {dest_hub['destination_id']})")

        # 2b. Register Zoho CRM Destination for Delhi & Mumbai
        dest_zoho = create_destination(CRMDestinationCreate(
            customer_name="Nexus Capital (Zoho)",
            crm_type="zoho",
            target_url=f"{base_url}/crm/zoho/v2/Leads",
            api_key="1000.abc987xyz123",
            city_filter="Delhi, Mumbai",
            auto_sync=True,
            is_active=True,
        ))
        created_dest_ids.append(dest_zoho["destination_id"])
        print(f"  ✓ Created Zoho destination '{dest_zoho['customer_name']}' (ID: {dest_zoho['destination_id']})")

        # 2c. Register Universal Webhook Destination for All Metros (*)
        dest_webhook = create_destination(CRMDestinationCreate(
            customer_name="Global Data Lake (Webhook)",
            crm_type="webhook",
            target_url=f"{base_url}/webhooks/all-metros",
            city_filter="*",
            auto_sync=True,
            is_active=True,
        ))
        created_dest_ids.append(dest_webhook["destination_id"])
        print(f"  ✓ Created Wildcard Webhook destination '{dest_webhook['customer_name']}' (ID: {dest_webhook['destination_id']})")

        # 2d. Read & Update Test
        fetched = get_destination_by_id(dest_hub["destination_id"])
        assert fetched["customer_name"] == "Vertex Enterprise (HubSpot)"
        updated = update_destination(dest_hub["destination_id"], CRMDestinationUpdate(customer_name="Vertex Enterprise (HubSpot Production)"))
        assert updated["customer_name"] == "Vertex Enterprise (HubSpot Production)"
        print(f"  ✓ Successfully verified GET and PUT update operations")

        # 2e. List & Filtering Test
        dests_delhi = get_destinations(city="Delhi")
        delhi_names = [d["customer_name"] for d in dests_delhi]
        assert "Nexus Capital (Zoho)" in delhi_names, "Nexus Capital should match Delhi"
        assert "Global Data Lake (Webhook)" in delhi_names, "Global Data Lake (*) should match Delhi"
        assert "Vertex Enterprise (HubSpot Production)" not in delhi_names, "Vertex Enterprise should NOT match Delhi"
        print(f"  ✓ City filter matching correctly separated Delhi targets from Bhubaneswar targets")

        # -----------------------------------------------------------------
        # TEST 3: Live Lead Export to HubSpot (Batch Schema)
        # -----------------------------------------------------------------
        print("\n[TEST 3] Testing Live Leads Dispatch to HubSpot (Batch Companies Schema)...")
        with _LOCK:
            before_count = len(CAPTURED_REQUESTS)

        export_resp = export_leads_to_crm(CRMExportRequest(
            destination_id=dest_hub["destination_id"],
            city="Bhubaneswar",
            limit=5,
            phone_only=True,
        ))
        assert export_resp["success"] is True, f"Export failed: {export_resp}"
        assert export_resp["status_code"] == 200
        assert export_resp["leads_count"] == 5, f"Expected 5 leads, got {export_resp['leads_count']}"

        with _LOCK:
            hub_captured = [r for r in CAPTURED_REQUESTS if "/crm/hubspot" in r["path"]][-1]
            body = hub_captured["body"]
            assert "inputs" in body, "HubSpot payload missing 'inputs' wrapper"
            assert len(body["inputs"]) == 5, f"Expected 5 inputs, got {len(body['inputs'])}"
            first_props = body["inputs"][0]["properties"]
            assert "name" in first_props and first_props["name"], "Missing company name"
            assert "phone" in first_props and first_props["phone"], "Missing phone"
            assert first_props["city"].lower() == "bhubaneswar", f"Expected Bhubaneswar, got {first_props['city']}"
            print(f"  ✓ Dispatched {export_resp['leads_count']} phone-verified Bhubaneswar leads in HubSpot Companies schema")
            print(f"    Sample: {first_props['name']} | Phone: {first_props['phone']} | City: {first_props['city']}")

        # -----------------------------------------------------------------
        # TEST 4: Live Lead Export to Zoho CRM (Leads Schema)
        # -----------------------------------------------------------------
        print("\n[TEST 4] Testing Live Leads Dispatch to Zoho CRM (Leads Schema)...")
        export_resp_zoho = export_leads_to_crm(CRMExportRequest(
            destination_id=dest_zoho["destination_id"],
            city="Delhi",
            limit=4,
        ))
        assert export_resp_zoho["success"] is True
        assert export_resp_zoho["leads_count"] == 4

        with _LOCK:
            zoho_captured = [r for r in CAPTURED_REQUESTS if "/crm/zoho" in r["path"]][-1]
            body = zoho_captured["body"]
            assert "data" in body, "Zoho payload missing 'data' wrapper"
            assert len(body["data"]) == 4
            record = body["data"][0]
            assert "Company" in record and record["Company"]
            assert "Lead_Source" in record and "Dakini AI" in record["Lead_Source"]
            print(f"  ✓ Dispatched {export_resp_zoho['leads_count']} Delhi leads in Zoho CRM Leads schema")
            print(f"    Sample: {record['Company']} | Phone: {record.get('Phone')} | Source: {record['Lead_Source']}")

        # -----------------------------------------------------------------
        # TEST 5: Dynamic One-Off Webhook Export (Without pre-registration)
        # -----------------------------------------------------------------
        print("\n[TEST 5] Testing Dynamic One-Off Webhook Export...")
        dynamic_url = f"{base_url}/custom-webhook-receiver"
        dyn_resp = export_leads_to_crm(CRMExportRequest(
            target_url=dynamic_url,
            crm_type="webhook",
            city="Bhubaneswar",
            limit=3,
        ))
        assert dyn_resp["success"] is True
        assert dyn_resp["status_code"] == 200

        with _LOCK:
            dyn_captured = [r for r in CAPTURED_REQUESTS if "/custom-webhook-receiver" in r["path"]][-1]
            body = dyn_captured["body"]
            assert body.get("event") == "dakini_leads_export"
            assert body.get("city") == "Bhubaneswar"
            assert len(body.get("leads", [])) == 3
            print(f"  ✓ Dynamic export delivered event '{body['event']}' with {len(body['leads'])} leads to {dynamic_url}")

        # -----------------------------------------------------------------
        # TEST 6: City Broadcast to All Subscribed Destinations
        # -----------------------------------------------------------------
        print("\n[TEST 6] Testing Multi-Destination City Broadcast (/api/crm/export with city)...")
        with _LOCK:
            pre_bcast_count = len(CAPTURED_REQUESTS)

        # Broadcast for Bhubaneswar: should dispatch to HubSpot (Bhubaneswar) & Webhook (*), but skip Zoho (Delhi/Mumbai)
        bcast_results = export_leads_to_crm(CRMExportRequest(city="Bhubaneswar", limit=2))
        assert isinstance(bcast_results, list)
        assert len(bcast_results) == 2, f"Expected 2 matching destinations, got {len(bcast_results)}"
        assert all(r["success"] for r in bcast_results)
        print(f"  ✓ Broadcasted to 2 active subscribers: {[r['customer_name'] for r in bcast_results]}")

        # -----------------------------------------------------------------
        # TEST 7: Asynchronous Automated Background Hook (trigger_auto_crm_sync)
        # -----------------------------------------------------------------
        print("\n[TEST 7] Testing Automated Post-Scrape Synchronization Hook...")
        with _LOCK:
            pre_auto_count = len(CAPTURED_REQUESTS)

        # Trigger hook asynchronously as orchestrator does upon scrape completion
        trigger_auto_crm_sync(city="Bhubaneswar", run_id="run_live_test_999")
        # Give daemon worker thread a moment to fetch destinations and dispatch HTTP requests
        time.sleep(0.8)

        with _LOCK:
            post_auto_count = len(CAPTURED_REQUESTS)
            diff = post_auto_count - pre_auto_count
            assert diff >= 2, f"Expected at least 2 automated dispatches, observed {diff}"
            print(f"  ✓ Background worker dispatched {diff} automated push payloads to active subscribers without blocking main thread")

        # -----------------------------------------------------------------
        # TEST 8: Audit Logs & Telemetry Query (/api/crm/logs)
        # -----------------------------------------------------------------
        print("\n[TEST 8] Verifying SQLite Audit Logs & Telemetry (/api/crm/logs)...")
        logs = get_crm_logs(limit=20)
        assert len(logs) >= 5, f"Expected at least 5 audit records, found {len(logs)}"
        first_log = logs[0]
        assert "destination_id" in first_log
        assert "status" in first_log
        assert "status_code" in first_log
        assert "leads_count" in first_log
        assert first_log["status"] == "success"
        print(f"  ✓ Retrieved {len(logs)} audit entries from crm_export_logs")
        print(f"    Latest Log: Customer '{first_log.get('customer_name')}' | Status: {first_log['status']} ({first_log['status_code']}) | Leads: {first_log['leads_count']}")

        print("\n=======================================================")
        print(" ALL 8 INTEGRATION TESTS PASSED SUCCESSFULLY!")
        print("=======================================================\n")
        return True

    except Exception as exc:
        print(f"\n[FAIL] Test encountered error: {exc}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup registered test destinations
        for did in created_dest_ids:
            delete_crm_destination(did)
        httpd.shutdown()
        server_thread.join(timeout=1.0)


if __name__ == "__main__":
    success = run_live_crm_test()
    sys.exit(0 if success else 1)
