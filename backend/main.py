"""FactoryPulse local demo API. All returned equipment and risk scores are synthetic."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="FactoryPulse API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET"], allow_headers=["*"])

class Equipment(BaseModel):
    equipment_id: str
    equipment_name: str
    equipment_type: str = "CNC"
    status: str
    risk_score: float = Field(ge=0, le=1)
    temperature_k: float
    rotational_speed_rpm: int

DEMO_EQUIPMENT = [
    Equipment(equipment_id="CNC-001", equipment_name="立式加工中心 A", status="正常", risk_score=0.12, temperature_k=307.4, rotational_speed_rpm=1450),
    Equipment(equipment_id="CNC-002", equipment_name="精密铣削中心 B", status="预警", risk_score=0.76, temperature_k=313.2, rotational_speed_rpm=1710),
    Equipment(equipment_id="CNC-003", equipment_name="五轴加工中心 C", status="高风险", risk_score=0.89, temperature_k=317.1, rotational_speed_rpm=1820),
    Equipment(equipment_id="CNC-004", equipment_name="数控车床 D", status="正常", risk_score=0.19, temperature_k=305.7, rotational_speed_rpm=1310),
    Equipment(equipment_id="CNC-005", equipment_name="加工中心 E", status="正常", risk_score=0.31, temperature_k=309.1, rotational_speed_rpm=1540),
    Equipment(equipment_id="CNC-006", equipment_name="加工中心 F", status="预警", risk_score=0.68, temperature_k=312.4, rotational_speed_rpm=1690),
]

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}

@app.get("/api/equipment")
def list_equipment():
    return {"data_source": "API模拟数据", "devices": [item.model_dump() for item in DEMO_EQUIPMENT], "synthetic": True}
