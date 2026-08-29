"""End-to-end wiring test for the SQL Warehouse analyze endpoint (plan Phase 6).

Exercises the real FastAPI route (`GET /api/warehouses/{id}/analyze`) with the
Databricks and serving-endpoint clients stubbed, so the router -> LLMService ->
prompt-assembly -> response-model path is verified without workspace
credentials. Covers the success path, the structured fallback on LLM failure,
the degraded config-only path when the cost summary fails, and the 500 path
when warehouse details fail.

Run: uv run python claude_scripts/test_sql_warehouse_analysis_wiring.py
"""

import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.models.job_spend import SqlWarehouseDetails
from server.routers import sql_warehouses as router_mod
from server.services.llm_service import (
    SQL_WAREHOUSE_ANALYSIS_PROMPT,
    SQL_WAREHOUSE_MAX_TOKENS,
    LLMService,
)

DETAILS = SqlWarehouseDetails(
    warehouse_id='wh-pro-1',
    warehouse_name='Shared Endpoint',
    warehouse_type='PRO',
    warehouse_size='SMALL',
    creator_id='guid-1',
    auto_stop_mins=45,
    min_clusters=1,
    max_clusters=4,
    tags={'team': 'finops'},
    cost_basis='dbu_only',
)

COST_SUMMARY = {
    'total_cost': 1234.5,
    'total_dbu_cost': 1234.5,
    'active_days': 12,
    'avg_daily_cost': 102.875,
    'warehouse_type': 'PRO',
    'warehouse_name': 'Shared Endpoint',
    'lookback_days': 30,
    'start_date': '2026-07-28',
    'end_date': '2026-08-26',
    'cost_basis': 'dbu_only',
}


class StubDatabricksService:
    """Stands in for DatabricksService (whose __init__ needs credentials)."""

    def __init__(self, details=DETAILS, cost=COST_SUMMARY):
        self._details = details
        self._cost = cost

    async def get_sql_warehouse_details(self, warehouse_id):
        if isinstance(self._details, Exception):
            raise self._details
        return self._details

    async def get_sql_warehouse_cost_summary(self, warehouse_id, start_date, end_date):
        if isinstance(self._cost, Exception):
            raise self._cost
        return self._cost


def make_llm(query_impl):
    """Build a real LLMService with only the serving-endpoint call stubbed."""
    llm = LLMService.__new__(LLMService)
    llm.model_name = 'stub-model'
    llm.client = SimpleNamespace(serving_endpoints=SimpleNamespace(query=query_impl))
    return llm


def build_client(databricks_service, llm_service):
    router_mod._databricks_service = databricks_service
    router_mod._llm_service = llm_service
    app = FastAPI()
    app.include_router(router_mod.router)
    return TestClient(app, raise_server_exceptions=False)


failures: list[str] = []


def check(label, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    print(f'  [{status}] {label}' + (f' -- {detail}' if detail and not condition else ''))
    if not condition:
        failures.append(label)


# ---------------------------------------------------------------------------
print('\n=== 1. Success path: LLM returns analysis text ===')
captured = {}


def ok_query(name, messages, max_tokens, temperature):
    captured['name'] = name
    captured['messages'] = messages
    captured['max_tokens'] = max_tokens
    captured['temperature'] = temperature
    msg = SimpleNamespace(content='  ## 1. Overall Rating [NEEDS ATTENTION]\nreal analysis  ')
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


client = build_client(StubDatabricksService(), make_llm(ok_query))
resp = client.get('/api/warehouses/wh-pro-1/analyze?start_date=2026-07-28&end_date=2026-08-26')
check('HTTP 200', resp.status_code == 200, f'got {resp.status_code}: {resp.text[:200]}')
body = resp.json()
check('warehouse_id echoed', body.get('warehouse_id') == 'wh-pro-1')
check(
    'analysis is LLM text (stripped)',
    body.get('analysis', '').startswith('## 1. Overall Rating')
    and body['analysis'].endswith('real analysis'),
)
check('timestamp present', bool(body.get('timestamp')))
check(
    'analysis window echoed',
    body.get('start_date') == '2026-07-28' and body.get('end_date') == '2026-08-26',
)
check('cost basis echoed', body.get('cost_basis') == 'dbu_only')

system_msg, user_msg = captured['messages']
check(
    'SYSTEM prompt is SQL_WAREHOUSE_ANALYSIS_PROMPT',
    system_msg.content == SQL_WAREHOUSE_ANALYSIS_PROMPT,
)
check(
    f'max_tokens == {SQL_WAREHOUSE_MAX_TOKENS}', captured['max_tokens'] == SQL_WAREHOUSE_MAX_TOKENS
)

um = user_msg.content
check('USER msg carries warehouse type', 'Warehouse Type: PRO' in um)
check(
    'USER msg flags auto-stop > 30 threshold',
    'Auto-Stop: 45 minutes (above the 30-minute threshold' in um,
)
check('USER msg carries cost figures', '$1,234.50' in um and 'Active Days: 12' in um)
check(
    'USER msg discloses Classic/Pro DBU-only scope', 'Classic/Pro tracked spend is DBU-only' in um
)

# ---------------------------------------------------------------------------
print('\n=== 2. LLM failure -> structured fallback (still HTTP 200) ===')


def boom_query(**kwargs):
    raise RuntimeError('serving endpoint unavailable')


client = build_client(StubDatabricksService(), make_llm(boom_query))
resp = client.get('/api/warehouses/wh-pro-1/analyze')
check('HTTP 200 (graceful)', resp.status_code == 200, f'got {resp.status_code}')
analysis = resp.json().get('analysis', '')
for section in (
    '## 1. Overall Rating',
    '## 2. Right-Sizing Assessment',
    '## 3. Cost Optimization',
    '## 4. Configuration Gaps',
    '## 5. Recommendations',
):
    check(f'fallback has {section!r}', section in analysis)
check('fallback carries config', 'Type: PRO | Size: SMALL' in analysis)
check('fallback carries cost', '$1,234.50' in analysis)
check(
    'fallback leaks no raw exception',
    'serving endpoint unavailable' not in analysis and 'Traceback' not in analysis,
)
check(
    'fallback discloses DBU-only cloud gap',
    'DBU-only' in analysis and 'customer-cloud infrastructure' in analysis,
)

# ---------------------------------------------------------------------------
print('\n=== 3. Cost-summary failure -> config-only analysis, not a 500 ===')
seen = {}


def capture_query(name, messages, max_tokens, temperature):
    seen['user'] = messages[1].content
    msg = SimpleNamespace(content='config-only analysis')
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


client = build_client(
    StubDatabricksService(cost=RuntimeError('cost query failed')),
    make_llm(capture_query),
)
resp = client.get('/api/warehouses/wh-pro-1/analyze')
check('HTTP 200 (degraded)', resp.status_code == 200, f'got {resp.status_code}')
check('LLM still invoked', resp.json().get('analysis') == 'config-only analysis')
check('cost summary rendered as unavailable', 'Cost data unavailable.' in seen.get('user', ''))
check('config still present', 'Warehouse Type: PRO' in seen.get('user', ''))

# ---------------------------------------------------------------------------
print('\n=== 4. Details failure -> HTTP 500 ===')
client = build_client(
    StubDatabricksService(details=RuntimeError('details query failed')),
    make_llm(ok_query),
)
resp = client.get('/api/warehouses/wh-pro-1/analyze')
check('HTTP 500', resp.status_code == 500, f'got {resp.status_code}')
check('generic detail, no internals leaked', 'details query failed' not in resp.text)

# ---------------------------------------------------------------------------
print('\n=== 5. Metadata-missing warehouse renders neutral, no raise ===')
missing = SqlWarehouseDetails(warehouse_id='made-up', metadata_missing=True)
zero = {
    'total_cost': 0.0,
    'total_dbu_cost': 0.0,
    'active_days': 0,
    'avg_daily_cost': 0.0,
    'warehouse_type': None,
    'warehouse_name': None,
    'lookback_days': 30,
}
client = build_client(StubDatabricksService(details=missing, cost=zero), make_llm(capture_query))
resp = client.get('/api/warehouses/made-up/analyze')
check('HTTP 200', resp.status_code == 200, f'got {resp.status_code}')
um = seen.get('user', '')
check('metadata state flagged unavailable', 'Metadata Available: No' in um)
check('name falls back to id', 'Warehouse Name: Warehouse made-up' in um)
check('zero-spend window stated', 'No spend data available for this warehouse' in um)

# ---------------------------------------------------------------------------
print()
if failures:
    print(f'{len(failures)} CHECK(S) FAILED:')
    for f in failures:
        print(f'  - {f}')
    sys.exit(1)
print('ALL CHECKS PASSED')
