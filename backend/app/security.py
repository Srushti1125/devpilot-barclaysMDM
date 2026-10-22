"""
Compatibility shim (W-6). JWT + password primitives live in app.core.security.
Re-exported so main.py / deps.py / tests share one implementation.
"""
from app.core.security import (ALGORITHM, create_access_token, decode_token_subject,  # noqa: F401
                               hash_password, token_subject, verify_password)
