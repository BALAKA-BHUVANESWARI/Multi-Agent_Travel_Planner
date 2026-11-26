"""The shapes of the data that moves between the agents and out through the API.

These are ``TypedDict``s: at run time the data is plain dictionaries (easy to save as JSON), and these classes
document exactly which keys exist. ``app/tests/test_services/test_schemas.py`` runs real plans and fails if the
code and these shapes ever drift apart. Request bodies, which FastAPI validates, are in ``requests.py``.
"""
