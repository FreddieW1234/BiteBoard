"""Smoke-test FedEx sandbox: OAuth → rates → optional test label.

Usage (from backend/ with env vars set):
  python -m scripts.fedex_smoke_test
  python -m scripts.fedex_smoke_test --label
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="FedEx sandbox smoke test")
    parser.add_argument("--label", action="store_true", help="Also create a test label")
    args = parser.parse_args()

    from scripts import fedex_api  # type: ignore
    from scripts.shipping import ship_from_address  # type: ignore

    print("Base URL:", fedex_api._base_url())
    print("Configured:", fedex_api.configured())
    if not fedex_api.configured():
        print(
            "Missing FEDEX_CLIENT_ID / FEDEX_CLIENT_SECRET / FEDEX_ACCOUNT_NUMBER",
            file=sys.stderr,
        )
        return 1

    print("Requesting OAuth token…")
    token = fedex_api.get_access_token(force=True)
    print("Token OK:", token[:16] + "…")

    ship_from = ship_from_address()
    if not ship_from.get("address1") or not ship_from.get("zip"):
        # Sandbox virtualized responses often ignore address details.
        ship_from = {
            "name": "Bite Warehouse",
            "phone": "02000000000",
            "address1": "1 Test Street",
            "city": "London",
            "zip": "EC1A 1BB",
            "country_code": "GB",
        }
        print("SHIP_FROM_* incomplete — using sandbox placeholder origin.")

    ship_to = {
        "name": "Freddie Wadley",
        "phone": "07555142782",
        "address1": "Ashgrove",
        "address2": "Lunnon, Parkmill",
        "city": "Swansea",
        "zip": "SA3 2EJ",
        "country_code": "GB",
        "residential": True,
    }

    print("Requesting rates…")
    rates = fedex_api.get_rates(
        ship_from=ship_from,
        ship_to=ship_to,
        weight_kg=0.7,
        length_cm=20,
        width_cm=15,
        height_cm=10,
    )
    print(f"Got {len(rates)} rate(s):")
    for r in rates[:8]:
        print(
            f"  {r.get('service_type')} | {r.get('service_code')} | "
            f"{r.get('currency')} {r.get('price')} | {r.get('rate_id')}"
        )

    if not rates:
        print("No rates returned — check sandbox project APIs / account association.")
        return 2

    if args.label:
        chosen = rates[0]
        print("Creating test label for", chosen.get("service_code"), "…")
        service, packaging = fedex_api.parse_rate_id(chosen["rate_id"])
        label = fedex_api.create_label(
            ship_from=ship_from,
            ship_to=ship_to,
            weight_kg=0.7,
            service_type=service,
            packaging_type=packaging,
            length_cm=20,
            width_cm=15,
            height_cm=10,
            order_name="#TEST",
        )
        print("Tracking:", label.get("tracking_number"))
        print("Label bytes:", len(label.get("label_bytes") or b""))
        print("Label URL:", (label.get("label_url") or "")[:120])

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
