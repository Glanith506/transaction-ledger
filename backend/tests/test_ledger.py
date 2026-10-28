from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app import main

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', str(tmp_path / 'test.sqlite3'))
    with TestClient(main.app) as api:
        yield api

def create(client, name='Robin'):
    response = client.post('/api/accounts', json={'name':name})
    assert response.status_code == 201
    return response.json()['id']

def post(client, aid, amount='100.00', kind='credit', ref='r1'):
    return client.post(f'/api/accounts/{aid}/transactions', json={'type':kind,'amount':amount,'reference_id':ref,'description':'Test entry'})

def balance(client, aid):
    return client.get(f'/api/accounts/{aid}/balance').json()['balance']

def test_account_defaults_and_protected_fields(client):
    aid = create(client)
    assert balance(client,aid) == '0.00'
    for payload in ({'name':''},{'name':'   '},{'name':'A','balance':500},{'name':'A','id':'mine'},{'name':'A','created_at':'yesterday'}):
        assert client.post('/api/accounts',json=payload).status_code == 422

def test_balance_example(client):
    aid=create(client)
    for n,(amount,kind) in enumerate([('100','credit'),('50','credit'),('30','debit'),('20','debit')]):
        assert post(client,aid,amount,kind,str(n)).status_code == 201
    assert balance(client,aid)=='100.00'
    assert post(client,aid,'101','debit','failed').status_code == 409
    assert balance(client,aid)=='100.00'
    assert client.get(f'/api/accounts/{aid}/transactions').json()['total_records']==4

def test_duplicate_scope(client):
    a,b=create(client),create(client,'Other')
    assert post(client,a).status_code==201
    assert post(client,a).status_code==409
    assert post(client,b).status_code==201
    assert balance(client,a)=='100.00'

@pytest.mark.parametrize('change',[{'type':'other'},{'amount':'0'},{'amount':'-1'},{'amount':'1.001'},{'amount':'NaN'},{'amount':'Infinity'},{'reference_id':''},{'reference_id':'  '},{'balance':123}])
def test_invalid_transactions(client,change):
    aid=create(client)
    payload={'type':'credit','amount':'10','reference_id':'ok',**change}
    response=client.post(f'/api/accounts/{aid}/transactions',json=payload)
    assert response.status_code==422
    assert 'error' in response.json()
    assert balance(client,aid)=='0.00'

def test_history(client):
    aid=create(client)
    post(client,aid,'20','credit','first')
    post(client,aid,'5','debit','second')
    post(client,aid,'2','credit','third')
    result=client.get(f'/api/accounts/{aid}/transactions?limit=2').json()
    assert [r['reference_id'] for r in result['items']]==['third','second']
    assert (result['total_records'],result['total_pages'],result['current_page'])==(3,2,1)
    assert len(client.get(f'/api/accounts/{aid}/transactions?page=2&limit=2').json()['items'])==1
    assert client.get(f'/api/accounts/{aid}/transactions?type=debit').json()['total_records']==1
    for query in ('page=0','limit=0','limit=101','page=abc','type=bad'):
        assert client.get(f'/api/accounts/{aid}/transactions?{query}').status_code==422

def test_missing_account(client):
    assert client.get('/api/accounts/missing/balance').status_code==404
    assert client.get('/api/accounts/missing/transactions').status_code==404
    assert post(client,'missing').status_code==404

def test_immutability(client):
    aid=create(client)
    tid=post(client,aid).json()['id']
    assert client.patch(f'/api/accounts/{aid}/transactions',json={}).status_code==405
    assert client.delete(f'/api/accounts/{aid}/transactions').status_code==405
    with main.connect(write=True) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE transactions SET description=? WHERE id=?',('changed',tid))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('DELETE FROM transactions WHERE id=?',(tid,))

def transfer(client,a,b,amount='30',ref='transfer'):
    return client.post('/api/transfers',json={'source_account_id':a,'destination_account_id':b,'amount':amount,'reference_id':ref})

def test_transfer_and_replay(client):
    a,b=create(client),create(client,'B')
    post(client,a,'100');post(client,b,'50')
    assert transfer(client,a,b).status_code==201
    assert (balance(client,a),balance(client,b))==('70.00','80.00')
    assert transfer(client,a,b).status_code==409
    assert transfer(client,a,b,'1000','failed').status_code==409
    assert transfer(client,a,a).status_code==422
    assert transfer(client,a,'missing').status_code==404
    assert (balance(client,a),balance(client,b))==('70.00','80.00')

def test_transfer_rolls_back_if_destination_reference_conflicts(client):
    a,b=create(client),create(client,'B')
    post(client,a,'100');post(client,b,'10',ref='taken')
    assert transfer(client,a,b,ref='taken').status_code==409
    assert balance(client,a)=='100.00'
    assert client.get(f'/api/accounts/{a}/transactions').json()['total_records']==1

def test_transaction_rolls_back_on_database_failure(client):
    aid=create(client)
    with main.connect() as db:
        db.execute("CREATE TRIGGER fail_balance BEFORE UPDATE ON accounts BEGIN SELECT RAISE(ABORT, 'forced failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        post(client,aid)
    assert balance(client,aid)=='0.00'
    assert client.get(f'/api/accounts/{aid}/transactions').json()['total_records']==0

def test_concurrent_debits_do_not_overdraw(client):
    aid=create(client);post(client,aid,'100')
    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses=list(executor.map(lambda i:post(client,aid,'30','debit',f'd{i}').status_code,range(8)))
    assert statuses.count(201)==3
    assert statuses.count(409)==5
    assert balance(client,aid)=='10.00'

def test_concurrent_duplicate_is_applied_once(client):
    aid=create(client)
    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses=list(executor.map(lambda _:post(client,aid,'0.10').status_code,range(6)))
    assert statuses.count(201)==1
    assert statuses.count(409)==5
    assert balance(client,aid)=='0.10'
