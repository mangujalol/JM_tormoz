from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import pandas as pd
import tempfile

app = FastAPI(title="JM Tormoz API")

# CORS sozlamalari (Frontend ulanishi uchun)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELS (Pydantic) ---
class PadReplaceRequest(BaseModel):
    wagon_code: str
    bogie_number: int
    pad_index: int

# --- SOXTA/MA'LUMOTLAR BAZASI (DB o'rniga namuna) ---
# Ishlab chiqish davrida SQLAlchemy DB modeliga moslaysiz
pads_db = []
logs_db = []

# Boshlang'ich ma'lumotlarni to'ldirish
wagons = ['TC1', '2', '3', '4', '5', '6', 'TC2']
bogie_map = {'TC1': [1, 2], '2': [3, 4], '3': [5, 6], '4': [7, 8], '5': [9, 10], '6': [11, 12], 'TC2': [13, 14]}

log_id_counter = 1

for w in wagons:
    for pad in range(1, 17):
        bogie = bogie_map[w][0] if pad <= 8 else bogie_map[w][1]
        pads_db.append({
            "wagon_code": w,
            "bogie_number": bogie,
            "pad_index": pad,
            "days_used": 0
        })

# --- ENDPOINTS ---

@app.get("/api/pads")
def get_all_pads():
    """Barcha kolodkalar holati va ishlatilgan kunlarini qaytaradi"""
    return pads_db

@app.get("/api/logs")
def get_all_logs():
    """Almashtirishlar tarixini (logs) qaytaradi (Oxirgi sanalar uchun)"""
    return logs_db

@app.post("/api/replace")
def replace_pad(req: PadReplaceRequest):
    """Kolodkani almashtirish va kunini 0 ga tushirish"""
    global log_id_counter
    
    # Pad-ni topish
    pad = next((p for p in pads_db if p["wagon_code"] == req.wagon_code and p["pad_index"] == req.pad_index), None)
    if not pad:
        raise HTTPException(status_code=404, detail="Kolodka topilmadi")

    prev_days = pad["days_used"]
    pad["days_used"] = 0  # Kunini 0 ga tushirish

    # Log yaratish
    new_log = {
        "id": log_id_counter,
        "wagon_code": req.wagon_code,
        "bogie_number": req.bogie_number,
        "pad_index": req.pad_index,
        "prev_days_used": prev_days,
        "created_at": datetime.now().isoformat()
    }
    logs_db.append(new_log)
    log_id_counter += 1

    return {"status": "success", "message": "Kolodka almashtirildi", "log": new_log}

@app.delete("/api/logs/{log_id}")
def delete_log(log_id: int):
    # log_id integer turida URL yo'li orqali qabul qilinadi
    log_idx = next((i for i, l in enumerate(logs_db) if l["id"] == log_id), None)
    
    if log_idx is None:
        raise HTTPException(status_code=404, detail="Bunday ID ga ega log topilmadi")

    log = logs_db.pop(log_idx)

    # Kolodkaning oldingi ishlatilgan kunini qayta tiklash
    pad = next((p for p in pads_db if p["wagon_code"] == log["wagon_code"] and p["pad_index"] == log["pad_index"]), None)
    if pad:
        pad["days_used"] = log["prev_days_used"]

    return {"status": "success", "message": f"Log #{log_id} o'chirildi"}

@app.get("/report/export-excel")
def export_excel():
    """Tarixni Excel fayl ko'rinishida yuklab berish"""
    if not logs_db:
        df = pd.DataFrame(columns=["ID", "Vagon", "Aravacha", "Kolodka", "Eski Kun", "Sana"])
    else:
        df = pd.DataFrame(logs_db)
        df.columns = ["ID", "Vagon", "Aravacha", "Kolodka Index", "Oldingi Kunlar", "Almashtirilgan Vaqt"]

    # Vaqtinchalik faylga saqlash va yuklash
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        df.to_excel(tmp.name, index=False, engine='openpyxl')
        return FileResponse(
            path=tmp.name,
            filename=f"JM_tormoz_hisobot_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )