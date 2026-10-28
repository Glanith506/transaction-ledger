"""PostgreSQL integration tests. Set POSTGRES_TEST_URL to run them.

Each test creates and removes its own uniquely named schema. Existing public
accounts and transactions are not used or deleted. Use a separate test project.
"""
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.fixture
def client(monkeypatch):
    url = os.getenv('POSTGRES_TEST_URL')
    if not url:
        pytest.skip('Set POSTGRES_TEST_URL to run PostgreSQL integration tests.')
    schema = 'ledger_test_' + uuid4().hex
    sslmode = os.getenv('DB_SSLMODE', 'require')
    with psycopg.connect(url, sslmode=sslmode) as db:
        db.execute(f'CREATE SCHEMA {schema}')

    original_connect = main.connect
    monkeypatch.setattr(main, 'DATABASE_URL', url)

    class ScopedConnection:
        def __init__(self, db):
            self.db = db

        def execute(self, query, *args, **kwargs):
            return self.db.execute(query.replace('public.', schema + '.'), *args, **kwargs)

    @contextmanager
    def scoped_connect(*, snapshot=False):
        with original_connect(snapshot=snapshot) as db:
            yield ScopedConnection(db)

    monkeypatch.setattr(main, 'connect', scoped_connect)
    try:
        with TestClient(main.app) as api:
            yield api
    finally:
        with psycopg.connect(url, sslmode=sslmode) as db:
            db.execute(f'DROP SCHEMA {schema} CASCADE')


def create(client, name='Robin'):
    response = client.post('/api/accounts', json={'name': name})
    assert response.status_code == 201
    return response.json()['id']


def post(client, aid, amount='100.00', kind='credit', ref='r1'):
    return client.post(f'/api/accounts/{aid}/transactions', json={
        'type': kind, 'amount': amount, 'reference_id': ref,
        'description': 'Test entry',
    })


def balance(client, aid):
    return client.get(f'/api/accounts/{aid}/balance').json()['balance']


def transfer(client, source, destination, amount='30', ref='move'):
    return client.post('/api/transfers', json={
        'source_account_id': source, 'destination_account_id': destination,
        'amount': amount, 'reference_id': ref,
    })


def test_account_defaults_and_protected_fields(client):
    aid = create(client)
    assert balance(client, aid) == '0.00'
    assert client.get('/api/accounts').json()[0]['created_at']
    for payload in ({'name': ''}, {'name': '  '}, {'name': 'A', 'balance': 5},
                    {'name': 'A', 'id': 'mine'}, {'name': 'A', 'created_at': 'yesterday'}):
        assert client.post('/api/accounts', json=payload).status_code == 422


def test_credit_debit_and_insufficient_funds(client):
    aid = create(client)
    for n, (amount, kind) in enumerate([('100', 'credit'), ('50', 'credit'),
                                      ('30', 'debit'), ('20', 'debit')]):
        assert post(client, aid, amount, kind, str(n)).status_code == 201
    assert balance(client, aid) == '100.00'
    assert post(client, aid, '101', 'debit', 'failed').status_code == 409
    assert balance(client, aid) == '100.00'
    assert client.get(f'/api/accounts/{aid}/transactions').json()['total_records'] == 4


def test_duplicate_scope(client):
    a, b = create(client), create(client, 'Other')
    assert post(client, a).status_code == 201
    assert post(client, a).status_code == 409
    assert post(client, b).status_code == 201
    assert balance(client, a) == '100.00'


@pytest.mark.parametrize('change', [
    {'type': 'other'}, {'amount': '0'}, {'amount': '-1'}, {'amount': '1.001'},
    {'amount': 'NaN'}, {'amount': 'Infinity'}, {'reference_id': ''},
    {'reference_id': '  '}, {'balance': 123},
])
def test_invalid_transaction(client, change):
    aid = create(client)
    payload = {'type': 'credit', 'amount': '10', 'reference_id': 'ok', **change}
    response = client.post(f'/api/accounts/{aid}/transactions', json=payload)
    assert response.status_code == 422
    assert 'error' in response.json()
    assert balance(client, aid) == '0.00'


def test_history_filters_and_pages(client):
    aid = create(client)
    post(client, aid, '20', 'credit', 'first')
    post(client, aid, '5', 'debit', 'second')
    post(client, aid, '2', 'credit', 'third')
    data = client.get(f'/api/accounts/{aid}/transactions?limit=2').json()
    assert [r['reference_id'] for r in data['items']] == ['third', 'second']
    assert (data['total_records'], data['total_pages']) == (3, 2)
    assert len(client.get(f'/api/accounts/{aid}/transactions?page=2&limit=2').json()['items']) == 1
    assert client.get(f'/api/accounts/{aid}/transactions?type=debit').json()['total_records'] == 1
    for query in ('page=0', 'limit=0', 'limit=101', 'page=abc', 'type=bad'):
        assert client.get(f'/api/accounts/{aid}/transactions?{query}').status_code == 422


def test_missing_account(client):
    assert client.get('/api/accounts/missing/balance').status_code == 404
    assert client.get('/api/accounts/missing/transactions').status_code == 404
    assert post(client, 'missing').status_code == 404


def test_immutable_entries(client):
    aid = create(client)
    tid = post(client, aid).json()['id']
    assert client.patch(f'/api/accounts/{aid}/transactions', json={}).status_code == 405
    assert client.delete(f'/api/accounts/{aid}/transactions').status_code == 405
    for query in ('UPDATE public.transactions SET description = %s WHERE id = %s',
                  'DELETE FROM public.transactions WHERE id = %s'):
        with pytest.raises(psycopg.errors.CheckViolation):
            with main.connect() as db:
                args = ('changed', tid) if query.startswith('UPDATE') else (tid,)
                db.execute(query, args)


def test_transfer_success_and_failures(client):
    a, b = create(client), create(client, 'B')
    post(client, a, '100')
    post(client, b, '50')
    assert transfer(client, a, b).status_code == 201
    assert (balance(client, a), balance(client, b)) == ('70.00', '80.00')
    assert transfer(client, a, b).status_code == 409
    assert transfer(client, a, b, '1000', 'failed').status_code == 409
    assert transfer(client, a, a).status_code == 422
    assert transfer(client, a, 'missing').status_code == 404
    assert (balance(client, a), balance(client, b)) == ('70.00', '80.00')


def test_destination_duplicate_rolls_back_transfer(client):
    a, b = create(client), create(client, 'B')
    post(client, a, '100')
    post(client, b, '10', ref='taken')
    assert transfer(client, a, b, ref='taken').status_code == 409
    assert balance(client, a) == '100.00'
    assert client.get(f'/api/accounts/{a}/transactions').json()['total_records'] == 1


def test_concurrent_debits_do_not_overdraw(client):
    aid = create(client)
    post(client, aid, '100')
    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(lambda i: post(client, aid, '30', 'debit', f'd{i}').status_code, range(8)))
    assert statuses.count(201) == 3
    assert statuses.count(409) == 5
    assert balance(client, aid) == '10.00'


def test_concurrent_duplicate_is_applied_once(client):
    aid = create(client)
    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses = list(executor.map(lambda _: post(client, aid, '0.10').status_code, range(6)))
    assert statuses.count(201) == 1
    assert statuses.count(409) == 5
    assert balance(client, aid) == '0.10'


def test_reverse_transfers_lock_in_consistent_order(client):
    a, b = create(client), create(client, 'B')
    post(client, a, '100')
    post(client, b, '100')
    def move(i):
        source, destination = (a, b) if i % 2 == 0 else (b, a)
        return transfer(client, source, destination, '1', f'reverse-{i}').status_code
    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses = list(executor.map(move, range(12)))
    assert statuses == [201] * 12
    assert (balance(client, a), balance(client, b)) == ('100.00', '100.00')
