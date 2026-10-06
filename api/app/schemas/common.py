"""Shared schema helpers. Anything more than one schema module needs lives here."""


def _camel(name: str) -> str:
    """Turn a snake_case field name into the camelCase key the frontend expects.

    Used as a Pydantic `alias_generator`, so every schema that crosses the wire can keep Python's
    snake_case internally and camelCase in JSON. Task 7 imports this for the program schema.
    """
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)
