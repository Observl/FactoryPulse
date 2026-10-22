"""Server-owned tool contracts. Models may select tools, never handlers or SQL."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Text = Annotated[str, Field(min_length=1, max_length=100, pattern=r".*\S.*")]
Note = Annotated[str, Field(min_length=1, max_length=500, pattern=r".*\S.*")]
Money = Annotated[float, Field(ge=0)]

class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

class Equipment(Arguments):
    equipment_id: Text | None = None

    @field_validator("equipment_id", mode="before")
    @classmethod
    def empty_means_overview(cls,value):
        return None if value == "" else value

class History(Arguments):
    equipment_id: Text

class Schedule(Arguments):
    scenario_id: Text
    start_at: Text | None = None

class Constraints(Arguments):
    scenario_id: Text
    note: Note
    budget: Money | None = None
    staff_count: Annotated[int, Field(ge=1, le=1000)] | None = None
    max_downtime_h: Annotated[float, Field(gt=0)] | None = None

class Compare(Arguments):
    scenario_id: Text | None = None
    budget: Money | None = None
    max_downtime_h: Money | None = None

class Draft(History):
    note: Note

class Context(Arguments):
    category: Literal["staff", "orders", "inventory", "scenarios", "requirements", "work_orders"]
    equipment_id: Text | None = None
    offset: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1, le=50)] = 20

class Flow(Arguments):
    work_order_id: Text

class Change(Arguments):
    kind: Literal["equipment", "staff", "orders", "scenarios"]
    identifier: Text
    values: dict
    reason: Note

    @classmethod
    def model_json_schema(cls, **kwargs):
        from .resources import StaffInput, OrderInput, ScenarioInput
        schema = super().model_json_schema(**kwargs)
        equipment = {"type":"object", "additionalProperties":False,
                     "required":["equipment_name","equipment_type"],
                     "properties":{k:{"type":"string","minLength":1,"maxLength":100} for k in ("equipment_name","equipment_type")}}
        shapes = {"equipment":equipment, **{kind:model.model_json_schema() for kind,model in
                  (("staff",StaffInput),("orders",OrderInput),("scenarios",ScenarioInput))}}
        for shape in shapes.values(): shape["additionalProperties"] = False
        schema["allOf"] = [{"if":{"properties":{"kind":{"const":kind}}},
                            "then":{"properties":{"values":shape}}} for kind,shape in shapes.items()]
        return schema

# name: (argument model, description, creates a draft)
REGISTRY = {
    "request_change": (Change, "申请修改现有设备名称/类型、人员班次、订单时间表或情景参数。values须提供资源完整可编辑字段；先查询资源。仅生成权限请求，不直接执行。", True),
    "equipment": (Equipment, "查询指定设备风险及工况；无编号时仅返回风险前十，不代表全厂完整清单", False),
    "history": (History, "查询指定设备时序、维修记录；分析复发与趋势须先读取", False),
    "evaluation": (Arguments, "读取时间外评估、真实故障数量及证据限制；分数不是概率", False),
    "compare_plans": (Compare, "比较维护任务取舍；不是正式排程，不证明班次或订单无冲突", False),
    "draft_work_order": (Draft, "起草维护需求，必须人工确认，不创建或批准正式工单", True),
    "draft_constraints": (Constraints, "起草预算、人数或工时调整，必须人工确认", True),
    "draft_schedule": (Schedule, "按情景约束计算排程草案，返回人员时间和冲突；须人工确认及审批", True),
    "operations_context": (Context, "分页查询当前数据版本的人员班次、生产订单、库存、维护参数、排程条件或工单。返回总数和截断标记；工单不能跨数据版本混算", False),
    "work_order_flow": (Flow, "读取当前数据版本指定工单状态、执行履历和审计记录；不修改工单", False),
}

def validate_arguments(name, arguments):
    if name not in REGISTRY:
        raise ValueError("未注册的工具")
    if not isinstance(arguments, dict):
        raise ValueError("工具参数必须是字段对象")
    return REGISTRY[name][0].model_validate(arguments).model_dump(exclude_unset=True,exclude_none=True)

def tool_definitions(read_only=False, disabled=()):
    return [{"type": "function", "function": {"name": name, "description": description,
             "parameters": schema.model_json_schema()}}
            for name, (schema, description, draft) in REGISTRY.items()
            if name not in disabled and not (read_only and draft)]
