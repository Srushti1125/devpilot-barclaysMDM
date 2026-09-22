from pydantic import BaseModel


class ApiField(BaseModel):
    name: str
    type: str
    required: bool = True
    description: str = ""


class ApiErrorCode(BaseModel):
    code: int
    reason: str


class ApiEndpoint(BaseModel):
    method: str
    path: str
    description: str
    request_schema: list[ApiField] = []
    response_schema: list[ApiField] = []
    error_codes: list[ApiErrorCode] = []


class ApiSpecList(BaseModel):
    endpoints: list[ApiEndpoint]
