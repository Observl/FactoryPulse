import sys
from types import SimpleNamespace
from backend import credentials


def test_vault_failure_uses_encrypted_file_and_survives_reload(tmp_path,monkeypatch):
    def unavailable(*args): raise OSError("vault unavailable")
    monkeypatch.setitem(sys.modules,"keyring",SimpleNamespace(set_password=unavailable,get_password=lambda *a:"stale-vault-key"))
    # OS encryption is independently exercised on Windows; unit test persistence ordering.
    monkeypatch.setattr(credentials,"_dpapi",lambda value,decrypt=False:value[::-1])
    secret="synthetic-unit-test-key"
    assert credentials.save_secret(tmp_path,secret)
    assert secret.encode() not in credentials.encrypted_path(tmp_path).read_bytes()
    assert credentials.load_secret(tmp_path)==secret
    assert not list(credentials.encrypted_path(tmp_path).parent.glob("tmp*"))


def test_encryption_failure_never_writes_plaintext(tmp_path,monkeypatch):
    def unavailable(*args): raise OSError("unavailable")
    monkeypatch.setitem(sys.modules,"keyring",SimpleNamespace(set_password=unavailable,get_password=unavailable))
    monkeypatch.setattr(credentials,"_dpapi",unavailable)
    assert credentials.save_secret(tmp_path,"synthetic-key") is False
    assert not credentials.encrypted_path(tmp_path).exists()


def test_successful_vault_write_removes_stale_fallback(tmp_path,monkeypatch):
    path=credentials.encrypted_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"stale-encrypted-data")
    vault={}
    monkeypatch.setitem(sys.modules,"keyring",SimpleNamespace(set_password=lambda a,b,v:vault.update(value=v),get_password=lambda *a:vault.get("value")))
    assert credentials.save_secret(tmp_path,"new-synthetic-key")
    assert not path.exists()
    assert credentials.load_secret(tmp_path)=="new-synthetic-key"
