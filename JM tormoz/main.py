import os
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# ---------------------------------------------------------
# BAZA VA FAYL TIZIMI SOZLAMALARI (Render moslashuvi)
# ---------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "/tmp/train_brakes.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------
# DATABASE MODELLARI
# ---------------------------------------------------------
class BrakeReplacement(Base):
    __tablename__ = "replacements"

    id = Column(Integer, primary_key=True, index=True)
    wagon_number = Column(Integer, nullable=False)  # 1 - 7
    bogie_number = Column(Integer, nullable=False)  # 1 - 14
    pad_position = Column(Integer, nullable=False)  # 1 - 16
    replaced_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(String, nullable=True)


# Jadvallarni yaratish (Tuzatilgan qism)
Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# PYDANTIC SCHEMAS
# ---------------------------------------------------------
class ReplacementCreate(BaseModel):
    wagon_number: int
    bogie_number: int
    pad_position: int
    notes: Optional[str] = None


class ReplacementResponse(BaseModel):
    id: int
    wagon_number: int
    bogie_number: int
    pad_position: int
    replaced_at: datetime
    notes: Optional[str]

    class Config:
        from_attributes = True


# ---------------------------------------------------------
# FASTAPI ILOVA SOZLAMALARI
# ---------------------------------------------------------
app = FastAPI(
    title="JM Train Brake Management System",
    description="7 vagonli poyezd tormoz kalodkalari monitoringi backend API",
)

# CORS sozlamalari
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------
# API ENDPOINTLARI
# ---------------------------------------------------------
@app.get("/")
def read_root():
    return {
        "status": "online",
        "system": "JM Train Brake API",
        "version": "1.0.0",
    }


# 1. Barcha joriy kalodkalar holatini olish
@app.get("/api/replacements", response_model=List[ReplacementResponse])
def get_all_replacements(db: Session = Depends(get_db)):
    return (
        db.query(BrakeReplacement)
        .order_by(BrakeReplacement.replaced_at.desc())
        .all()
    )


# 2. Yangi kalodka almashtirish logini qo'shish
@app.post(
    "/api/replacements",
    response_model=ReplacementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_replacement(
    data: ReplacementCreate, db: Session = Depends(get_db)
):
    if not (1 <= data.wagon_number <= 7):
        raise HTTPException(
            status_code=400, detail="Vagon raqami 1 va 7 orasida bo'lishi kerak"
        )
    if not (1 <= data.bogie_number <= 14):
        raise HTTPException(
            status_code=400, detail="Telejka raqami 1 va 14 orasida bo'lishi kerak"
        )
    if not (1 <= data.pad_position <= 16):
        raise HTTPException(
            status_code=400,
            detail="Kalodka pozitsiyasi 1 va 16 orasida bo'lishi kerak",
        )

    new_record = BrakeReplacement(
        wagon_number=data.wagon_number,
        bogie_number=data.bogie_number,
        pad_position=data.pad_position,
        notes=data.notes,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return new_record


# 3. Yozuvni tahrirlash (2 kunlik muddat cheklovi bilan)
@app.put("/api/replacements/{item_id}", response_model=ReplacementResponse)
def update_replacement(
    item_id: int, data: ReplacementCreate, db: Session = Depends(get_db)
):
    record = (
        db.query(BrakeReplacement)
        .filter(BrakeReplacement.id == item_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")

    if datetime.utcnow() - record.replaced_at > timedelta(days=2):
        raise HTTPException(
            status_code=403,
            detail=(
                "Yozuv yaratilganidan beri 2 kundan ortiq vaqt o'tdi."
                " Tahrirlash taqiqlangan."
            ),
        )

    record.wagon_number = data.wagon_number
    record.bogie_number = data.bogie_number
    record.pad_position = data.pad_position
    record.notes = data.notes

    db.commit()
    db.refresh(record)
    return record


# 4. Yozuvni o'chirish (2 kunlik muddat cheklovi bilan)
@app.delete("/api/replacements/{item_id}")
def delete_replacement(item_id: int, db: Session = Depends(get_db)):
    record = (
        db.query(BrakeReplacement)
        .filter(BrakeReplacement.id == item_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")

    if datetime.utcnow() - record.replaced_at > timedelta(days=2):
        raise HTTPException(
            status_code=403,
            detail=(
                "Yozuv yaratilganidan beri 2 kundan ortiq vaqt o'tdi."
                " O'chirish taqiqlangan."
            ),
        )

    db.delete(record)
    db.commit()
    return {"message": "Yozuv muvaffaqiyatli o'chirildi", "id": item_id}


# 5. Excel hisobotini yuklab olish
@app.get("/api/reports/excel")
def export_excel_report(db: Session = Depends(get_db)):
    records = (
        db.query(BrakeReplacement)
        .order_by(BrakeReplacement.replaced_at.desc())
        .all()
    )

    data = []
    for r in records:
        data.append({
            "ID": r.id,
            "Vagon №": r.wagon_number,
            "Telejka №": r.bogie_number,
            "Kalodka pozitsiyasi": r.pad_position,
            "Almashtirilgan sana (UTC)": r.replaced_at.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "Izohlar": r.notes or "",
        })

    df = pd.DataFrame(data)
    export_path = "/tmp/jm_tormoz_hisobot.xlsx"
    df.to_excel(export_path, index=False, engine="openpyxl")

    return FileResponse(
        path=export_path,
        filename=f"JM_Tormoz_Hisobot_{datetime.now().strftime('%Y%m%d')}.xlsx",
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )