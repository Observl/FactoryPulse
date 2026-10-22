import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

spec=importlib.util.spec_from_file_location('offline_requirements',Path(__file__).resolve().parents[1]/'scripts/prepare-offline-requirements.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_closure_preserves_extras_markers_and_transitive_versions():
    packages={'a':SimpleNamespace(version='1.2',requires=['b>=2','c; extra=="feature"','missing; python_version<"2"']),
              'b':SimpleNamespace(version='2.3',requires=['a[feature]>=1']),
              'c':SimpleNamespace(version='3.4',requires=[])}
    assert module.dependency_closure('a>=1,<2',packages.__getitem__)=={'a':'1.2','b':'2.3','c':'3.4'}

def test_conflicting_installed_versions_are_not_exported_as_valid():
    with pytest.raises(ValueError,match='不满足'):
        module.dependency_closure('a>=2',lambda name:SimpleNamespace(version='1',requires=[]))
    with pytest.raises(ValueError,match='URL'):
        module.dependency_closure('a @ https://example.invalid/a.whl')
