"""Expose rule inputs and arithmetic without inventing a formula for workbook scores."""
import math

def rule_details(risk,reading):
    source=risk.get('data_origin','WORKBOOK_OR_EXTERNAL_SCORE')
    def number(key):
        try:value=float(reading[key]);return value if math.isfinite(value) else None
        except (KeyError,ValueError,TypeError):return None
    if source=='SYNTHETIC_SENSOR_THRESHOLD_BASELINE':
        fields=[('vibration_mm_s',2.2,.12),('motor_current_a',9,.05)];base=.04
    elif source=='CNC_THRESHOLD_BASELINE':
        fields=[('vibration_mm_s',2.5,.12),('process_temperature_k',315,.025),('spindle_load_pct',70,.012)];base=.02
    else:return {'source':source,'stored_score':risk.get('risk_score'),'formula_available':False,'note':'此分数由工作簿或外部来源提供，未保存其完整计算过程，不能伪造推导公式。'}
    terms=[{'feature':key,'value':number(key),'threshold':threshold,'coefficient':coefficient,'contribution':max(0,number(key)-threshold)*coefficient if number(key) is not None else None} for key,threshold,coefficient in fields]
    complete=all(term['contribution'] is not None for term in terms)
    reconstructed=round(min(.98,base+sum(term['contribution'] for term in terms)),4) if complete else None
    return {'source':source,'formula_available':True,'base':base,'cap':.98,'terms':terms,'reconstructed_score':reconstructed,'stored_score':risk.get('risk_score'),'matches_stored':reconstructed is not None and abs(reconstructed-float(risk.get('risk_score',0)))<.00001}
