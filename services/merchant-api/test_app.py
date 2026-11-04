import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app as module


@pytest.fixture
def test_client():
    with tempfile.TemporaryDirectory() as temp:
        module.DB_PATH = Path(temp) / 'db.sqlite3'
        module.init_db()
        with TestClient(module.app) as client:
            yield client


def test_health(test_client):
    res = test_client.get('/health')
    assert res.status_code == 200
    assert res.json() == {'status': 'ok'}


def test_merchant_workflow(test_client):
    assert test_client.get('/health').json()['status'] == 'ok'
    assert len(test_client.get('/api/products').json()) == 3
    p = test_client.post('/api/products', json={'name': 'Test Hat', 'category': 'Clothing', 'price': 20, 'stock': 2})
    assert p.status_code == 201
    pid = p.json()['id']
    assert test_client.patch(f'/api/products/{pid}/stock', json={'stock': 0}).json()['stock'] == 0
    assert test_client.get('/api/stats').json()['out_of_stock'] == 2
    assert test_client.post('/api/discount-preview', json={'price': 50, 'percent': 20}).json()['final'] == 40
    assert test_client.post('/api/products', json={'name': 'X', 'category': 'C', 'price': -1, 'stock': 3}).status_code == 422
    assert test_client.delete(f'/api/products/{pid}').status_code == 204
    assert test_client.patch(f'/api/products/{pid}/stock', json={'stock': 4}).status_code == 404


def test_product_search_and_filtering(test_client):
    # Initial seeded items: Canvas Tote, Ceramic Mug, Desk Lamp
    all_products = test_client.get('/api/products').json()
    assert len(all_products) == 3

    # Case-insensitive substring search
    mugs = test_client.get('/api/products?search=mug').json()
    assert len(mugs) == 1
    assert mugs[0]['name'] == 'Ceramic Mug'

    caps_search = test_client.get('/api/products?search=LAMP').json()
    assert len(caps_search) == 1
    assert caps_search[0]['name'] == 'Desk Lamp'

    # Non-matching search
    assert test_client.get('/api/products?search=nonexistent_xyz').json() == []


def test_product_creation_boundary_validation(test_client):
    # Valid product with boundary values
    res = test_client.post('/api/products', json={
        'name': 'AB',
        'category': 'CD',
        'price': 0.0,
        'stock': 0
    })
    assert res.status_code == 201
    created = res.json()
    assert created['name'] == 'AB'
    assert created['price'] == 0.0

    # Negative price rejected (422)
    assert test_client.post('/api/products', json={'name': 'Item', 'category': 'Cat', 'price': -0.01, 'stock': 5}).status_code == 422

    # Negative stock rejected (422)
    assert test_client.post('/api/products', json={'name': 'Item', 'category': 'Cat', 'price': 10, 'stock': -1}).status_code == 422

    # Excessive values (> 1,000,000) rejected
    assert test_client.post('/api/products', json={'name': 'Item', 'category': 'Cat', 'price': 1000001, 'stock': 1}).status_code == 422
    assert test_client.post('/api/products', json={'name': 'Item', 'category': 'Cat', 'price': 10, 'stock': 1000001}).status_code == 422

    # Name too short (< 2 chars)
    assert test_client.post('/api/products', json={'name': 'A', 'category': 'Cat', 'price': 10, 'stock': 1}).status_code == 422

    # Name too long (> 100 chars)
    assert test_client.post('/api/products', json={'name': 'A' * 101, 'category': 'Cat', 'price': 10, 'stock': 1}).status_code == 422

    # Category too short (< 2 chars)
    assert test_client.post('/api/products', json={'name': 'Valid Name', 'category': 'C', 'price': 10, 'stock': 1}).status_code == 422

    # Missing fields
    assert test_client.post('/api/products', json={'name': 'No Category'}).status_code == 422
    assert test_client.post('/api/products', json={}).status_code == 422


def test_stats_calculation(test_client):
    # Initial seeds:
    # Canvas Tote: price 18.5, stock 22 -> 407.0
    # Ceramic Mug: price 12.0, stock 8 -> 96.0
    # Desk Lamp: price 44.0, stock 0 -> 0.0
    # Expected total count = 3, out_of_stock = 1, inventory_value = 503.0
    stats = test_client.get('/api/stats').json()
    assert stats['count'] == 3
    assert stats['out_of_stock'] == 1
    assert stats['inventory_value'] == 503.0

    # Add new product: price 50, stock 2 (+100 inventory_value)
    test_client.post('/api/products', json={'name': 'Leather Belt', 'category': 'Apparel', 'price': 50.0, 'stock': 2})
    stats_updated = test_client.get('/api/stats').json()
    assert stats_updated['count'] == 4
    assert stats_updated['out_of_stock'] == 1
    assert stats_updated['inventory_value'] == 603.0


def test_stock_update_and_not_found(test_client):
    # Valid stock update
    res = test_client.patch('/api/products/1/stock', json={'stock': 50})
    assert res.status_code == 200
    assert res.json() == {'id': 1, 'stock': 50}

    # Non-existent product ID returns 404
    assert test_client.patch('/api/products/99999/stock', json={'stock': 10}).status_code == 404

    # Negative stock returns 422
    assert test_client.patch('/api/products/1/stock', json={'stock': -5}).status_code == 422

    # Missing stock field returns 422
    assert test_client.patch('/api/products/1/stock', json={}).status_code == 422


def test_product_deletion_and_404(test_client):
    # Delete product 2
    res = test_client.delete('/api/products/2')
    assert res.status_code == 204

    # Verify it is no longer listed
    products = test_client.get('/api/products').json()
    assert not any(p['id'] == 2 for p in products)

    # Deleting again returns 404
    assert test_client.delete('/api/products/2').status_code == 404

    # Deleting non-existent ID returns 404
    assert test_client.delete('/api/products/99999').status_code == 404


def test_discount_preview_calculations(test_client):
    # Standard discount
    res = test_client.post('/api/discount-preview', json={'price': 100.0, 'percent': 25.0})
    assert res.status_code == 200
    assert res.json() == {'original': 100.0, 'discount_percent': 25.0, 'final': 75.0}

    # Zero percent discount (no change)
    res_zero = test_client.post('/api/discount-preview', json={'price': 49.99, 'percent': 0.0})
    assert res_zero.json()['final'] == 49.99

    # 100 percent discount (free)
    res_free = test_client.post('/api/discount-preview', json={'price': 80.0, 'percent': 100.0})
    assert res_free.json()['final'] == 0.0

    # Rounding behavior: 19.99 with 15% discount -> 19.99 * 0.85 = 16.9915 -> 16.99
    res_round = test_client.post('/api/discount-preview', json={'price': 19.99, 'percent': 15.0})
    assert res_round.json()['final'] == 16.99

    # Boundary validations
    assert test_client.post('/api/discount-preview', json={'price': -10.0, 'percent': 10.0}).status_code == 422
    assert test_client.post('/api/discount-preview', json={'price': 50.0, 'percent': -5.0}).status_code == 422
    assert test_client.post('/api/discount-preview', json={'price': 50.0, 'percent': 105.0}).status_code == 422
