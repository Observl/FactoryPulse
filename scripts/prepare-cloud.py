"""Create deployment secret files locally without printing or overwriting secrets."""
import argparse,getpass,os,sys,json
from pathlib import Path
from cryptography.fernet import Fernet
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.security import validate_password

def prepare(password=None):
    folder=ROOT/'.secrets';folder.mkdir(exist_ok=True);os.chmod(folder,0o700)
    password_file=folder/'cloud-admin-password'
    if not password_file.exists():
        value=password or getpass.getpass('Initial cloud admin password: ');validate_password(value)
        with password_file.open('x',encoding='utf-8') as handle:handle.write(value)
        os.chmod(password_file,0o600)
    key_file=folder/'cloud-credential-key'
    if not key_file.exists():
        with key_file.open('xb') as handle:handle.write(Fernet.generate_key())
        os.chmod(key_file,0o600)
    identity=folder/'identity.json'
    if identity.exists():
        cfg=json.loads(identity.read_text(encoding='utf-8'));cfg['token_file']='/run/secrets/d1_token'
        (folder/'identity.container.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    print('Deployment secret files are ready; existing files were preserved.')

if __name__=='__main__':prepare()
