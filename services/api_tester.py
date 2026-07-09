"""
services/api_tester.py
-------------------------
Tests connectivity to a configured JSON API endpoint -- used by the
"Test Connection" button on both the Sensors screen (per-sensor API
config) and the Attendance System screen (Step 7).

Design choice: this runs server-side (Flask makes the HTTP request),
not client-side via browser JS fetch(). Two reasons:
  1. Avoids CORS (Cross-Origin Resource Sharing) issues entirely --
     a factory's SCADA/attendance API almost certainly doesn't set
     CORS headers allowing browser-based requests from this app's origin.
  2. Keeps any API key/token in the headers off the browser network tab.

Returns a plain dict rather than raising, so callers never need a
try/except -- a failed test is a normal, expected outcome here, not an
error condition.
"""

import requests

# Keep this short -- a "Test Connection" button should never leave the
# user waiting more than a few seconds to find out an endpoint is down.
REQUEST_TIMEOUT_SECONDS = 6


def _parse_headers(raw_headers: str) -> dict:
    """Parses a textarea's worth of "Key: Value" lines (one header per
    line) into a dict. Blank lines and malformed lines (no colon) are
    silently skipped rather than raising -- a user-typed headers field
    is exactly the kind of input that will occasionally be malformed,
    and a test button should degrade gracefully, not 500."""
    headers = {}
    if not raw_headers:
        return headers
    for line in raw_headers.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key:
            headers[key] = value
    return headers


def test_endpoint(url: str, method: str = "GET", raw_headers: str = "") -> dict:
    """
    Attempts a single request against `url` and reports whether a
    response was received at all -- this is a connectivity/reachability
    check, not a validation of the response content.

    Returns:
        {
            "success": bool,          # True if any HTTP response came back
            "status_code": int|None,  # the HTTP status code, if a response arrived
            "message": str,           # human-readable summary for the UI
        }
    """
    if not url or not url.strip():
        return {"success": False, "status_code": None, "message": "No API URL configured."}

    headers = _parse_headers(raw_headers)
    method = (method or "GET").upper()

    try:
        if method == "POST":
            response = requests.post(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        else:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # Any response at all (even a 4xx/5xx) means the endpoint is
        # reachable -- we're testing connectivity, not authorization.
        # A 401/403 still proves the system is "up"; that's a config
        # problem for the user to fix in their auth headers, not a
        # reason to show a misleading "inactive" status.
        return {
            "success": True,
            "status_code": response.status_code,
            "message": f"Received HTTP {response.status_code} from the endpoint.",
        }

    except requests.exceptions.Timeout:
        return {"success": False, "status_code": None, "message": f"No response within {REQUEST_TIMEOUT_SECONDS}s (timed out)."}
    except requests.exceptions.ConnectionError:
        return {"success": False, "status_code": None, "message": "Could not connect to this URL (connection refused or unreachable)."}
    except requests.exceptions.MissingSchema:
        return {"success": False, "status_code": None, "message": "Invalid URL -- did you forget 'http://' or 'https://'?"}
    except requests.exceptions.RequestException as e:
        return {"success": False, "status_code": None, "message": f"Request failed: {e}"}
