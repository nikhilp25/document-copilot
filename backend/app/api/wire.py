"""The shared wire convention for every route module.

camelCase on the wire, snake_case in Python. The TypeScript client and the AI
SDK both expect camelCase; translating once here beats every frontend call site
spelling `created_at`.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class WireModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
