from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TableFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: int = Field(ge=0, le=99999, strict=True)
    operator: Literal["eq", "ne", "contains", "gt", "gte", "lt", "lte"]
    value: str = Field(max_length=2048, strict=True)


class TableAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    table_id: str = Field(min_length=1, max_length=128)
    collection_id: str = Field(default="enterprise", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    operation: Literal["count", "sum", "mean", "min", "max", "group_count", "group_sum"]
    column: int | None = Field(default=None, ge=0, le=99999, strict=True)
    group_by: int | None = Field(default=None, ge=0, le=99999, strict=True)
    filters: list[TableFilter] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def required_columns(self):
        numerical = self.operation in {"sum", "mean", "min", "max", "group_sum"}
        grouped = self.operation in {"group_count", "group_sum"}
        if numerical != (self.column is not None):
            raise ValueError("数值运算必须指定 column；计数运算不接受 column。列索引从 0 开始。")
        if grouped != (self.group_by is not None):
            raise ValueError("分组运算必须指定 group_by；非分组运算不接受 group_by。")
        return self
