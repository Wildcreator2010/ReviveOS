from pydantic import BaseModel


class Score(BaseModel):
    total: float
    components: dict[str, float]
