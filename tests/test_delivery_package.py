import hashlib,importlib.util,json,zipfile
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('delivery_package',Path(__file__).resolve().parents[1]/'scripts/package-local-delivery.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def fixture(root):
    names=['backend/main.py','backend/build_artifact.py','backend/requirements.txt','scripts/start-local.ps1','scripts/stop-local.ps1','scripts/install-offline.ps1','scripts/final-acceptance.py','docs/LOCAL-DEPLOYMENT.md','docs/OPERATOR-GUIDE.md','docs/BACKUP-RECOVERY.md','docs/OPERATOR-TRIAL.md','dist/index.html','data/model-validation/dataset.json','data/model-validation/manifest.json','.env','operator.sqlite3','outputs/private.log']
    for name in names:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name,'utf-8')
    for name in ('exercise-recovery.py','verify-local-deployment.py','export-prediction-evidence.py'):(root/'scripts'/name).write_text(name,'utf-8')
    page=(root/'dist/index.html').read_bytes()
    (root/'dist/factorypulse-build.json').write_text(json.dumps({'schema_version':1,'app':'FactoryPulse','build_mode':'local_service','asset_base':'/','api_prefix':'/api','files':[{'path':'index.html','size':len(page),'sha256':hashlib.sha256(page).hexdigest()}]}),'utf-8')

def test_delivery_is_allowlisted_and_every_recorded_hash_matches_archive(tmp_path):
    source=tmp_path/'project';fixture(source)
    path,manifest=module.package(source,tmp_path/'delivery',True)
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        assert '.env' not in names and 'operator.sqlite3' not in names and 'outputs/private.log' not in names
        assert 'data/model-validation/dataset.json' in names
        for item in manifest['files']:
            data=archive.read(item['path']);assert len(data)==item['size'] and hashlib.sha256(data).hexdigest()==item['sha256']
    assert manifest['installation_verified'] is False and manifest['wheelhouse_included'] is False

def test_delivery_rejects_tampered_ui_and_missing_runtime_sources(tmp_path):
    source=tmp_path/'project';fixture(source)
    (source/'dist/index.html').write_text('changed','utf-8')
    with pytest.raises(ValueError,match='不一致'):module.package(source,tmp_path/'delivery')
    fixture(source);(source/'backend/main.py').unlink()
    with pytest.raises(ValueError,match='后端入口'):module.package(source,tmp_path/'delivery')
