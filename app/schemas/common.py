from pydantic import BaseModel, ConfigDict


class ORMBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BootstrapOut(BaseModel):
    course_id: str | None
    assessment_id: str | None
    scan_id: str | None
