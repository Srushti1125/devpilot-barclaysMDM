from langchain_core.output_parsers import PydanticOutputParser


def get_parser(schema_cls):
    return PydanticOutputParser(pydantic_object=schema_cls)
