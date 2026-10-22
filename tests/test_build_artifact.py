import hashlib,json
import pytest
from backend.build_artifact import validate_build

def build(root,**changes):
    page=b'<html>FactoryPulse</html>';(root/'index.html').write_bytes(page)
    manifest={'schema_version':1,'app':'FactoryPulse','version':'test','build_mode':'local_service','api_prefix':'/api','asset_base':'/',
              'files':[{'path':'index.html','size':len(page),'sha256':hashlib.sha256(page).hexdigest()}],**changes}
    (root/'factorypulse-build.json').write_text(json.dumps(manifest),'utf-8')
    return manifest

def test_local_bundle_is_verified_without_rendering(tmp_path):
    build(tmp_path);assert validate_build(tmp_path)['status']=='verified'

def test_public_demo_cannot_be_mistaken_for_local_application(tmp_path):
    build(tmp_path,build_mode='static_demo',asset_base='/FactoryPulse/')
    with pytest.raises(ValueError,match='不是本地服务版'):validate_build(tmp_path)

def test_tampered_asset_is_rejected(tmp_path):
    build(tmp_path);(tmp_path/'index.html').write_bytes(b'changed')
    with pytest.raises(ValueError,match='不一致'):validate_build(tmp_path)

def test_malformed_manifest_is_rejected_with_actionable_error(tmp_path):
    (tmp_path/'factorypulse-build.json').write_text('[]','utf-8')
    with pytest.raises(ValueError,match='必须为对象'):validate_build(tmp_path)
    build(tmp_path,files=[None])
    with pytest.raises(ValueError,match='格式无效'):validate_build(tmp_path)

def test_missing_asset_and_path_escape_are_rejected(tmp_path):
    manifest=build(tmp_path);manifest['files'].append({'path':'../outside','size':0,'sha256':''})
    (tmp_path/'factorypulse-build.json').write_text(json.dumps(manifest),'utf-8')
    with pytest.raises(ValueError,match='越界'):validate_build(tmp_path)
    (tmp_path/'factorypulse-build.json').unlink()
    with pytest.raises(FileNotFoundError):validate_build(tmp_path)
