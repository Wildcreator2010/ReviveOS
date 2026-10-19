from pydantic import BaseModel


class Manifest(BaseModel):
    model_config = {"extra": "allow"}
