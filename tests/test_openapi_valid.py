# tests/test_openapi_valid.py
import json

import pytest
from django.test import Client


@pytest.mark.django_db
def test_openapi_schema_has_minimal_keys():
    c = Client()
    # 强制 JSON 渲染器
    r = c.get("/api/schema/?format=json")
    assert r.status_code == 200
    # 不用 r.json()，直接解析字节串，避免 Content-Type 限制
    schema = json.loads(r.content)
    for key in ["openapi", "info", "paths"]:
        assert key in schema
