"""Independent checker must reject corrupt outputs, not mirror solver logic."""
import copy
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('comparison',ROOT/'scripts/compare_schedulers.py')
comparison=importlib.util.module_from_spec(spec);spec.loader.exec_module(comparison)


def sample():
    f=json.loads((ROOT/'tests/fixtures/scheduler-comparison.json').read_text())[0]
    row=dict(f['tasks'][0],staff_ids=['P0'],start_at='2026-10-20 08:00:00',end_at='2026-10-20 10:00:00')
    r=dict(scheduled=[row],conflicts=[dict(equipment_id=k,reason='not selected') for k in ['B','C']])
    return f,r


def test_valid_result():
    f,r=sample()
    assert comparison.validate(f,r)['hard_constraint_errors']==[]
    assert comparison.validate(f,r)['person_hours']==2


def test_checker_rejects_independent_constraint_violations():
    changes=[lambda f,r:f.update(budget=0),lambda f,r:f.update(max_hours=1),lambda f,r:f['stock'].update({'轴承':0}),lambda f,r:f['staff'][0].update(skills='电气'),lambda f,r:f['staff'][0].update(available_hours=1),lambda f,r:f['staff'][0].update(shift_start='2026-10-20T09:00:00'),lambda f,r:f['tasks'][0].update(people=2),lambda f,r:r['scheduled'][0].update(end_at='2026-10-20 09:00:00'),lambda f,r:f['orders'].append(dict(equipment_id='A',start_at='2026-10-20T09:00:00',end_at='2026-10-20T11:00:00')),lambda f,r:r['scheduled'].append(copy.deepcopy(r['scheduled'][0])),lambda f,r:r.update(conflicts=[]),lambda f,r:f.update(staff_limit=0)]
    for mutate in changes:
        f,r=sample();mutate(f,r)
        assert comparison.validate(f,r)['hard_constraint_errors']


def test_fixture_contract():
    cases=json.loads((ROOT/'tests/fixtures/scheduler-comparison.json').read_text())
    for f in cases:
        assert len({t['equipment_id'] for t in f['tasks']})==len(f['tasks'])
        for t in f['tasks']:
            assert t['priority_weight']=={'高':9000,'中':6000,'低':3000}[t['priority']]
