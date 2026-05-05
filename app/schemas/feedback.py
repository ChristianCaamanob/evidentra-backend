from pydantic import BaseModel


class FeedbackArtifactOut(BaseModel):
    artifact_type: str
    title: str
    items: list[str]
