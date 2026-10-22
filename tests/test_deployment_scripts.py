"""Exercise refusal branches in isolated folders, without launching a server."""
import os
import shutil
import subprocess
from pathlib import Path
import pytest

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows deployment scripts')
ROOT=Path(__file__).resolve().parents[1]

def invoke(script,*arguments):
    return subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),*arguments],capture_output=True,timeout=20)

def expected_refusal(script,pattern,*arguments):
    def literal(value):return "'"+str(value).replace("'","''")+"'"
    command='& '+literal(script)+' '+ ' '.join(value if value in {'-PythonExecutable','-Wheelhouse','-RequirementsFile'} else literal(value) for value in arguments)
    wrapper=script.parent/'expect-refusal.ps1'
    wrapper.write_text("$ErrorActionPreference='Stop'\ntry { "+command+"; exit 9 } catch { if ($_.Exception.Message -like "+literal(pattern)+") { Write-Output 'EXPECTED_REFUSAL'; exit 0 }; throw }",'utf-8-sig')
    response=invoke(wrapper)
    assert response.returncode==0,(response.stdout,response.stderr)
    assert b'EXPECTED_REFUSAL' in response.stdout

def test_start_refuses_incomplete_install_before_creating_data_or_launching(tmp_path):
    scripts=tmp_path/'scripts';scripts.mkdir()
    shutil.copy2(ROOT/'scripts/start-local.ps1',scripts/'start-local.ps1')
    marker=tmp_path/'.factorypulse-install-incomplete';marker.touch()
    expected_refusal(scripts/'start-local.ps1','*离线安装未完成*')
    assert marker.exists() and not (tmp_path/'.venv').exists()
    assert not list(tmp_path.rglob('service-*.json'))

def test_installer_preserves_existing_environment_and_pending_marker(tmp_path):
    scripts=tmp_path/'scripts';scripts.mkdir()
    shutil.copy2(ROOT/'scripts/install-offline.ps1',scripts/'install-offline.ps1')
    environment=tmp_path/'.venv';environment.mkdir()
    sentinel=environment/'keep.txt';sentinel.write_text('existing runtime','utf-8')
    expected_refusal(scripts/'install-offline.ps1','*已有 .venv*','-PythonExecutable','missing.exe','-Wheelhouse','missing-wheels')
    assert sentinel.read_text('utf-8')=='existing runtime'
    assert not (tmp_path/'.factorypulse-install-incomplete').exists()
    marker=tmp_path/'.factorypulse-install-incomplete';marker.touch()
    expected_refusal(scripts/'install-offline.ps1','*上次离线安装未完成*','-PythonExecutable','missing.exe','-Wheelhouse','missing-wheels')
    assert marker.exists() and sentinel.exists()

def test_offline_installer_rejects_network_requirements_before_creating_environment(tmp_path):
    scripts=tmp_path/'scripts';scripts.mkdir();shutil.copy2(ROOT/'scripts/install-offline.ps1',scripts/'install-offline.ps1')
    python=tmp_path/'python.exe';python.touch()
    wheels=tmp_path/'wheels';wheels.mkdir()
    requirements=tmp_path/'requirements.txt'
    for entry in ['package @ https://example.invalid/a.whl','-r nested.txt','--extra-index-url https://example.invalid','https://example.invalid/a.whl']:
        requirements.write_text(entry,'utf-8')
        expected_refusal(scripts/'install-offline.ps1','*不能包含URL*','-PythonExecutable',str(python),'-Wheelhouse',str(wheels),'-RequirementsFile',str(requirements))
        assert not (tmp_path/'.venv').exists() and not (tmp_path/'.factorypulse-install-incomplete').exists()
