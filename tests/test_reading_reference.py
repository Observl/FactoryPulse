from backend.reading_reference import ranges

def test_reference_uses_only_labelled_nonfault_samples_and_converts_units():
    rows=[{'equipment_id':'E1','failure':0,'motor_current_a':i,'process_temperature_k':273.15+i} for i in range(100)]
    rows.extend([{'equipment_id':'E1','failure':1,'motor_current_a':99999},{'equipment_id':'E1','motor_current_a':99999},{'equipment_id':'E1','failure':0,'motor_current_a':None}])
    result=ranges(rows)['E1']
    assert result['motor_current_a']['samples']==100
    assert result['motor_current_a']['low']==4.95
    assert result['motor_current_a']['high']==94.05
    assert result['process_temperature_c']['low']==4.95
    assert '不是厂家' in result['motor_current_a']['basis']

def test_reference_rejects_sparse_invalid_values_and_separates_devices():
    rows=[{'equipment_id':'E1','failure':0,'oil_temperature_c':i} for i in range(19)]
    rows += [{'equipment_id':'E1','failure':0,'oil_temperature_c':value} for value in [float('nan'),float('inf'),True,None,'bad']]
    rows += [{'equipment_id':'E2','failure':'0','oil_temperature_c':10} for _ in range(20)]
    result=ranges(rows)
    assert 'oil_temperature_c' not in result['E1']
    assert result['E2']['oil_temperature_c']['low']==10
