import json
from backend.demo_business import initialize_demo_stock
from backend.main import connect,settings_get
from tests.test_api import client


def test_reload_cnc_demo_initializes_new_scope_with_simulated_inventory():
    for _ in range(2):
        response=client.post('/api/sync/cnc-demo')
        assert response.status_code==200,response.text
        scope=settings_get('inventory_scope')
        with connect() as connection:
            stock=connection.execute('SELECT * FROM inventory_stock WHERE scope=?',(scope,)).fetchall()
            assert stock and all(row['source']=='simulated_count' for row in stock)
            assert all(row['on_hand']==24 for row in stock)


def test_demo_stock_reinitialization_does_not_replenish_consumed_or_counted_stock():
    assert client.post('/api/sync/cnc-demo').status_code==200
    with connect() as connection:
        scope=settings_get('inventory_scope')
        connection.execute('UPDATE inventory_stock SET on_hand=7 WHERE scope=?',(scope,))
        data={'maintenance_rules':[json.loads(row[0]) for row in connection.execute("SELECT content FROM records WHERE table_name='maintenance_rules'")]}
        initialize_demo_stock(connection,data,scope)
        assert connection.execute('SELECT on_hand FROM inventory_stock WHERE scope=?',(scope,)).fetchone()[0]==7


def test_demo_stock_helper_does_not_seed_unmarked_enterprise_parts():
    with connect() as connection:
        initialize_demo_stock(connection,{'maintenance_rules':[{'data_origin':'USER_IMPORTED_OPERATIONAL','spare_parts':[{'part_name':'真实库存','quantity':1,'available_quantity':100}]}]},'enterprise')
        assert connection.execute("SELECT COUNT(*) FROM inventory_stock WHERE scope='enterprise'").fetchone()[0]==0


def test_cached_nasa_business_overlay_preserves_monitoring_and_uses_bearing_parts(tmp_path,monkeypatch):
    from backend import nasa_ims
    original=[{'equipment_id':'IMS-B1','timestamp':'2004-04-01 00:00:00','vibration_g':.12,'failure':0,'future_failure':None}]
    tables={'equipment':[{'equipment_id':'IMS-B1'}],'readings':original,'maintenance_rules':[{'equipment_id':'IMS-B1','required_skill':'轴承','inspection_duration_h':1,'repair_duration_h':3,'inspection_cost_cny':300,'repair_cost_cny':2400}], 'staff':[{'staff_id':'T1','staff_name':'维修员'}],'orders':[{'order_id':'O1','equipment_id':'IMS-B1'}],'scenarios':[{'scenario_id':'NASA-IMS-BASE'}],'maintenance_history':[]}
    cache=tmp_path/'nasa.json';cache.write_text(json.dumps({'tables':tables,'source_date':'2004-04-01'}),'utf-8')
    monkeypatch.setattr(nasa_ims,'CACHE_FILE',cache)
    result,date=nasa_ims.build_nasa_ims()
    assert result['readings']==original and date=='2004-04-01'
    assert all('轴承' in row['skills'] for row in result['staff'])
    assert '轴承' in result['maintenance_rules'][0]['spare_parts'][0]['part_name']
    assert result['orders'][0]['end_at']<=result['maintenance_rules'][0]['window_end']
    assert json.loads(cache.read_text('utf-8'))['tables']['readings']==original
