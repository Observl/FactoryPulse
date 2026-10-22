"""Authenticated encryption for Linux cloud credentials; master key lives outside /data."""
import os
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet
from .cloud_mode import read_secret_file

def cipher():return Fernet(read_secret_file('FACTORYPULSE_CREDENTIAL_KEY_FILE').encode('ascii'))

def load_secret(directory):
    path=Path(directory)/'credentials'/'ai-key.fernet'
    if not path.exists():return ''
    # A lost/wrong master key must be reported, never silently treated as an empty key.
    return cipher().decrypt(path.read_bytes()).decode('utf-8')

def save_secret(directory,value):
    path=Path(directory)/'credentials'/'ai-key.fernet'
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        encrypted=cipher().encrypt(value.encode('utf-8'))
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
            temporary=Path(handle.name);handle.write(encrypted);handle.flush();os.fsync(handle.fileno())
        os.chmod(temporary,0o600);os.replace(temporary,path)
        return True
    except (OSError,ValueError):return False
    finally:
        if temporary:temporary.unlink(missing_ok=True)
