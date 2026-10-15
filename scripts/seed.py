"""Populate a demo database: customers, drivers and shipments in every state.

    python -m scripts.seed
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cargo_bot.config import settings
from cargo_bot.models import (
    Driver,
    ShipmentStatus,
    build_engine,
    build_session_factory,
    init_db,
)
from cargo_bot.services import (
    advance,
    assign_driver,
    create_shipment,
    get_or_create_customer,
    register_driver,
    stats,
)

ROUTES = [
    ("Kyiv, Khreschatyk 1", "Lviv, Svobody Ave 2", "boxes", 12.5, 40.0),
    ("Kyiv, Dniprovska 4", "Odesa, Deyabosha 9", "furniture", 85.0, 260.0),
    ("Kharkiv, Sumska 32", "Dnipro, Yevropska 11", "electronics", 6.0, 55.0),
    ("Vinnytsia, Soborna 5", "Chernivtsi, Centralna 3", "documents", 1.2, 28.0),
    ("Lviv, Bandery 21", "Warsaw, Krucza 12", "auto parts", 240.0, 780.0),
    ("Kyiv, Lesi Ukrainky 7", "Istanbul, Istiklal 100", "textiles", 35.0, 410.0),
    ("Zaporizhzhia, Naberezhna 3", "Kyiv, Arsenalna 8", "tools", 48.0, 165.0),
]


def main() -> int:
    url = os.getenv("DATABASE_URL", settings.database_url)
    engine = build_engine(url)
    init_db(engine)
    session = build_session_factory(engine)()

    customers = [
        get_or_create_customer(session, telegram_id=1001 + i, name=name, phone=phone)
        for i, (name, phone) in enumerate(
            [
                ("Alex", "+380501112233"),
                ("Maria", "+380501112244"),
                ("Taras", "+380501112255"),
            ]
        )
    ]

    driver_a = register_driver(session, 2001, "Sam Kovalenko", "+380667778899")
    driver_b = register_driver(session, 2002, "Oleksandr Bondar", "+380667778800")

    created = []
    for idx, (pickup, dropoff, cargo, weight, price) in enumerate(ROUTES):
        customer = customers[idx % len(customers)]
        created.append(
            create_shipment(
                session,
                customer,
                pickup=pickup,
                dropoff=dropoff,
                cargo_type=cargo,
                weight_kg=weight,
                price=price,
            )
        )

    # Walk the first five shipments through different lifecycle stages.
    for shipment in created[:2]:
        assign_driver(session, shipment.code, driver_a)
        advance(session, shipment.code, ShipmentStatus.PICKED_UP)
        advance(session, shipment.code, ShipmentStatus.IN_TRANSIT)
        advance(session, shipment.code, ShipmentStatus.DELIVERED)

    third = created[2]
    assign_driver(session, third.code, driver_b)
    advance(session, third.code, ShipmentStatus.PICKED_UP)
    advance(session, third.code, ShipmentStatus.IN_TRANSIT)

    fourth = created[3]
    assign_driver(session, fourth.code, driver_a)
    advance(session, fourth.code, ShipmentStatus.PICKED_UP)

    fifth = created[4]
    assign_driver(session, fifth.code, driver_b)
    advance(session, fifth.code, ShipmentStatus.PICKED_UP)

    created[5].created_at = datetime.now(timezone.utc) - timedelta(days=2)
    session.commit()

    print(f"Seeded database: {url}")
    print(f"  shipments: {len(created)}")
    print(f"  codes: {', '.join(s.code for s in created)}")
    print(f"  stats: {stats(session)}")
    session.close()
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())