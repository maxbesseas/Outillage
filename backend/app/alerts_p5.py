from datetime import datetime

from sqlalchemy.orm import Session

from . import notify
from .alerts import generator
from .models_p5 import StockItem


@generator("stock_low")
def stock_low(db: Session, now: datetime) -> int:
    week = now.isocalendar()
    low = [i for i in db.query(StockItem).filter(StockItem.is_active.is_(True), StockItem.threshold > 0)
           if i.quantity <= i.threshold]
    by_agency = {}
    for item in low:
        by_agency.setdefault(item.agency_number, []).append(item)
    count = 0
    for agency, items in by_agency.items():
        listing = ", ".join(f"{i.name} ({i.quantity:g}/{i.threshold:g} {i.unit})" for i in items[:8])
        count += notify.create_many(
            db, notify.agency_managers(db, agency), "stock_low", f"{len(items)} article(s) sous le seuil de stock",
            listing + (f" et {len(items) - 8} autre(s)" if len(items) > 8 else ""), link="#/stock",
            dedup_prefix=f"stock_low_week:{agency}:{week[0]}-{week[1]}",
        )
    return count
