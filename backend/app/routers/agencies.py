from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import audit, schemas
from ..auth import get_current_admin, get_current_user
from ..database import get_db
from ..models import Agency, AgencyTool, Epi, User
from ..models_p5 import MaintenanceTicket, StockItem
from ..models_p6 import Site

router = APIRouter(prefix="/agencies", tags=["agencies"])


@router.get("", response_model=list[schemas.AgencyOut])
def list_agencies(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Agency)
    if not (include_inactive and current_user.role.value == "admin"):
        query = query.filter(Agency.is_active.is_(True))
    return query.order_by(Agency.name).all()


@router.post("", response_model=schemas.AgencyOut, status_code=status.HTTP_201_CREATED)
def create_agency(
    payload: schemas.AgencyCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    name = payload.name.strip()
    if db.query(Agency).filter(Agency.name == name).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cette agence existe déjà")
    agency = Agency(name=name, code=payload.code, excel_registry_name=payload.excel_registry_name)
    db.add(agency)
    db.flush()
    audit.record(db, "agency_created", current_user.id, "agency", agency.id, request, {"name": name})
    db.commit()
    db.refresh(agency)
    return agency


@router.patch("/{agency_id}", response_model=schemas.AgencyOut)
def update_agency(
    agency_id: int,
    payload: schemas.AgencyUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if not agency:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agence introuvable")

    data = payload.model_dump(exclude_unset=True)
    old_name = agency.name

    if "name" in data:
        new_name = data["name"].strip()
        if new_name != old_name:
            if db.query(Agency).filter(Agency.name == new_name).first():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce nom d'agence existe déjà")
            for model in (User, AgencyTool, Epi, Site, StockItem, MaintenanceTicket):
                db.query(model).filter(model.agency_number == old_name).update(
                    {"agency_number": new_name}, synchronize_session=False
                )
            db.query(AgencyTool).filter(AgencyTool.home_agency == old_name).update(
                {"home_agency": new_name}, synchronize_session=False
            )
            agency.name = new_name
        data.pop("name")

    for field, value in data.items():
        setattr(agency, field, value)

    audit.record(db, "agency_updated", current_user.id, "agency", agency.id, request,
                 {"old_name": old_name, "fields": sorted(payload.model_dump(exclude_unset=True).keys())})
    db.commit()
    db.refresh(agency)
    return agency


@router.delete("/{agency_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agency(
    agency_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if not agency:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agence introuvable")

    used = (
        db.query(User).filter(User.agency_number == agency.name).count()
        + db.query(AgencyTool).filter(AgencyTool.agency_number == agency.name).count()
        + db.query(Epi).filter(Epi.agency_number == agency.name).count()
    )
    if used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette agence est utilisée par des comptes ou du matériel : désactivez-la plutôt que de la supprimer",
        )

    audit.record(db, "agency_deleted", current_user.id, "agency", agency.id, request, {"name": agency.name})
    db.delete(agency)
    db.commit()
    return None
