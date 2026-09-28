# Provider Adapters

**Purpose**: Complete specification for the standalone adapter model. Every provider's architecture, authentication, known quirks, and implementation requirements.

---

## Table of Contents

1. [Adapter Contract](#1-adapter-contract)
2. [GHL Public API Adapter](#2-ghl-public-api-adapter)
3. [GHL Workflow API Adapter](#3-ghl-workflow-api-adapter)
4. [Notion Adapter](#4-notion-adapter)
5. [Google Workspace Adapter](#5-google-workspace-adapter)
6. [Airtable Adapter](#6-airtable-adapter)
7. [Adapter Testing](#7-adapter-testing)
8. [Adding a New Provider](#8-adding-a-new-provider)

---

## 1. Adapter Contract

### The ProviderAdapter Interface

```python
class BaseAdapter(ABC):
    """Standard interface every provider must implement."""

    @abstractmethod
    async def call(self, kernel_op_id: str, params: dict,
                   binding: BindingRow, context: ExecutionContext) -> KernelResult:
        """Execute a kernel operation. NEVER raises — always returns KernelResult."""
        pass

    @abstractmethod
    async def validate_params(self, kernel_op_id: str,
                              params: dict) -> ValidationResult:
        """Validate params against the kernel's input schema."""
        pass

    @abstractmethod
    def get_kernel_meta(self, kernel_op_id: str) -> KernelMeta | None:
        """Return metadata for a kernel operation."""
        pass

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check if the provider API is reachable."""
        pass

    @abstractmethod
    def capabilities(self) -> list[str]:
        """List all kernel_op_ids this adapter supports."""
        pass
```

### Adapter Contract Rules (NON-NEGOTIABLE)

1. **NEVER raise exceptions** — always return `KernelResult(status="error", error=...)`
2. **NEVER call the control plane** — adapters are leaves
3. **NEVER make authorization decisions** — that's the SafetyGate's job
4. **NEVER modify ExecutionContext** — it's frozen
5. **NEVER call other adapters** — complete isolation
6. **ALWAYS classify errors** — into the Error Hierarchy

### The SafeAdapterWrapper

```python
class SafeAdapterWrapper:
    """Wraps any adapter to guarantee the NEVER-raise contract."""

    def __init__(self, adapter: BaseAdapter):
        self._adapter = adapter

    async def call(self, kernel_op_id: str, params: dict,
                   binding: BindingRow, context: ExecutionContext) -> KernelResult:
        try:
            return await self._adapter.call(kernel_op_id, params, binding, context)
        except Exception as e:
            logger.error(f"Adapter {type(self._adapter).__name__} raised: {type(e).__name__}: {e}")
            return KernelResult(
                status="error",
                error=str(e),
                kernel=kernel_op_id,
                attempt=0,
                metadata={"exception_type": type(e).__name__, "exception_message": str(e)},
            )
```

### Adapter Internal Structure

```python
class GHLPublicAdapter(BaseAdapter):
    def __init__(self, config: AdapterConfig, db: Database):
        self._config = config
        self._db = db
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(35.0),  # CRIT-006: 35s client timeout > default 30s step timeout
        )
        self._token_manager = GHLTokenManager(db)

    async def call(self, kernel_op_id: str, params: dict,
                   binding: BindingRow, context: ExecutionContext) -> KernelResult:
        # 1. Look up kernel in KERNEL_MAP
        meta = self.get_kernel_meta(kernel_op_id)
        if meta is None:
            return KernelResult(status="error", error=f"Unknown kernel: {kernel_op_id}", kernel=kernel_op_id)

        # 2. Validate params
        validation = await self.validate_params(kernel_op_id, params)
        if not validation.valid:
            return KernelResult(status="error", error=validation.error, kernel=kernel_op_id)

        # 3. Ensure auth
        token = await self._token_manager.ensure_valid_token(context.tenant_id)
        if token is None:
            return KernelResult(status="error", error="Authentication failed", kernel=kernel_op_id)

        # 4. Build request
        request = meta.build_request(params, token)

        # 5. Execute
        try:
            response = await self._client.request(
                method=meta.method,
                url=meta.endpoint,
                json=request.body,
                params=request.query_params,
            )
        except httpx.TimeoutException:
            # CRIT-005: Return UNKNOWN, not "error" — the guard needs to probe
            return KernelResult(status="UNKNOWN", error="Request timed out — outcome unknown, probe required",
                                kernel=kernel_op_id, metadata={"requires_probe": True})
        except httpx.NetworkError:
            return KernelResult(status="UNKNOWN", error="Network error — outcome unknown, probe required",
                                kernel=kernel_op_id, metadata={"requires_probe": True})

        # 6. Parse response
        return meta.parse_response(response)
```

---

## 2. GHL Public API Adapter

### Overview

| Attribute | Value |
|-----------|-------|
| Provider | GoHighLevel (CRM) |
| Adapter Class | `GHLPublicAdapter` |
| Auth System | PIT (Private Integration Token) via GHLTokenManager |
| Capabilities | 15 kernel operations |
| Base URL | `https://rest.gohighlevel.com/v1` |
| Rate Limit | 100 requests/minute per location |

### Authentication

Uses PIT tokens stored per-tenant. Tokens are managed by `GHLTokenManager` which handles:
- Token storage in database (encrypted)
- Automatic refresh before expiry
- Per-tenant token isolation

```python
class GHLTokenManager:
    async def ensure_valid_token(self, tenant_id: str) -> str | None:
        """Return a valid PIT token for the tenant.

        Note: Database must be initialized with row_factory=sqlite3.Row
        to enable dict-style access on query results.
        """
        token_data = self._db.execute(
            "SELECT encrypted_token, expires_at FROM provider_tokens WHERE tenant_id = ? AND provider = 'ghl'",
            (tenant_id,)
        ).fetchone()

        if token_data is None:
            return None

        # Refresh if expiring within 5 minutes
        if token_data["expires_at"] - time.time() < 300:
            # Decrypt before refresh
            current_token = self._decrypt(token_data["encrypted_token"])
            new_token = await self._refresh_token(current_token)
            self._db.execute(
                "UPDATE provider_tokens SET encrypted_token = ?, expires_at = ? WHERE tenant_id = ?",
                (self._encrypt(new_token), time.time() + 3600, tenant_id)
            )

        return self._decrypt(token_data["encrypted_token"])
```

### Kernel Operations (15)

| Kernel | Mutation | Description |
|--------|----------|-------------|
| `ghl.contact_search` | R | Search contacts by query |
| `ghl.contact_get` | R | Get a single contact by ID |
| `ghl.contact_create` | W | Create a new contact |
| `ghl.contact_update` | W | Update an existing contact |
| `ghl.contact_delete` | D | Delete a contact |
| `ghl.contact_tags` | W | Add/remove tags from a contact |
| `ghl.contact_notes` | W | Add a note to a contact |
| `ghl.campaign_list` | R | List campaigns |
| `ghl.campaign_get` | R | Get a single campaign |
| `ghl.opportunity_list` | R | List opportunities for a contact |
| `ghl.opportunity_create` | W | Create an opportunity |
| `ghl.appointment_list` | R | List appointments |
| `ghl.appointment_create` | W | Create an appointment |
| `ghl.appointment_delete` | D | Delete an appointment |
| `ghl.custom_field_list` | R | List custom fields |

### Known Issues

| Issue | Severity | Mitigation |
|-------|----------|------------|
| Two auth systems (PIT + Firebase JWT) | HIGH | Check both independently, never mix |
| 5 deprecated kernels still in registry | MEDIUM | Mark retired explicitly with replacement |
| Token expiry not checked before API call | MEDIUM | GHLTokenManager.ensure_valid_token() before every call |

---

## 3. GHL Workflow API Adapter

### Overview

| Attribute | Value |
|-----------|-------|
| Provider | GoHighLevel (Workflow Engine) |
| Adapter Class | `GHLWorkflowAdapter` |
| Auth System | Firebase JWT (separate from PIT) |
| Capabilities | 12 kernel operations |
| Base URL | `https://api.gohighlevel.com/workflows/v1` |

### Authentication

Uses Firebase JWT tokens, completely separate from the PIT system. Must be stored and managed independently.

### Known Issues

| Issue | Severity | Mitigation |
|-------|----------|------------|
| Separate auth from GHLPublicAdapter | HIGH | Ensure Firebase JWT is managed independently |
| Workflow API has different rate limits | MEDIUM | Separate circuit breaker |

---

## 4. Notion Adapter

### Overview

| Attribute | Value |
|-----------|-------|
| Provider | Notion |
| Adapter Class | `NotionAdapter` |
| Auth System | Bearer token (per-account) |
| Capabilities | 12 kernel operations |
| Base URL | `https://api.notion.com/v1` |
| Rate Limit | ~3 requests/second per integration token |

### Authentication

Bearer token stored per-account. Supports multi-tenant:
```python
class NotionAdapter(BaseAdapter):
    def __init__(self, config: AdapterConfig, accounts_store: EncryptedAccountsStore):
        self._config = config
        self._accounts = accounts_store  # Encrypted multi-account store

    async def _get_token(self, account_id: str) -> str:
        accounts = self._accounts.load()
        account = accounts.get(account_id)
        if account is None:
            raise ValueError(f"Unknown Notion account: {account_id}")
        return account["token"]
```

### Multi-Account Support

The adapter supports multiple Notion accounts. Account selection is via the `binding`:
```python
@dataclass(frozen=True)
class NotionBindingRow(BindingRow):
    notion_account_id: str  # Which Notion workspace/account to use
    database_id: str        # Target database (for database operations)
```

### Known Issues

| Issue | Severity | Mitigation |
|-------|----------|------------|
| Multi-account tokens in plaintext | HIGH | Encrypt with Fernet or use OS keychain |
| No batch writes — one API call per operation | MEDIUM | Rate limiter, batch with 10s delay |
| `partialSuccess: true` with HTTP 200 | HIGH | Check partialSuccess field explicitly |
| Notion API v1 vs legacy endpoints | MEDIUM | Always use v1 endpoints |

### Partial Success Handling

Notion's batch operations can return HTTP 200 with `partialSuccess: true`:
```python
def parse_response(self, response: httpx.Response) -> KernelResult:
    data = response.json()
    if data.get("partialSuccess") is True:
        return KernelResult(
            status="partial",
            data=data.get("results", []),
            error=f"Partial success: {len(data.get('errors', []))} operations failed",
            kernel=self._current_kernel,
            metadata={"partial_success": True, "errors": data.get("errors", [])},
        )
    return KernelResult(status="ok", data=data, kernel=self._current_kernel)
```

---

## 5. Google Workspace Adapter

### Overview

| Attribute | Value |
|-----------|-------|
| Provider | Google (Calendar, Sheets, Drive, Docs, Forms, Meet, Gmail) |
| Adapter Class | `GoogleWorkspaceAdapter` |
| Auth System | OAuth 2.0 (service account + user delegation) |
| Capabilities | 20 kernel operations across 7 services |
| Base URLs | Multiple (calendar, sheets, drive, etc.) |
| Rate Limit | Per-service limits (varies) |

### Authentication

OAuth 2.0 with service account and user delegation:
```python
class GoogleWorkspaceAdapter(BaseAdapter):
    def __init__(self, config: AdapterConfig):
        self._config = config
        self._credentials = service_account.Credentials.from_service_account_file(
            config.service_account_file,
            scopes=["https://www.googleapis.com/auth/calendar", ...],
        )

    async def _get_delegated_credentials(self, user_email: str):
        """Delegate to a specific user's account."""
        return self._credentials.with_subject(user_email)
```

### Service Sub-Adapters

The Google adapter is composed of service-specific sub-adapters:

| Service | Sub-Adapter | Capabilities |
|---------|-------------|-------------|
| Calendar | `GoogleCalendarAdapter` | event_create, event_get, event_list, event_update, event_delete |
| Sheets | `GoogleSheetsAdapter` | spreadsheet_get, spreadsheet_values_get, spreadsheet_values_update |
| Drive | `GoogleDriveAdapter` | file_list, file_get, file_create, file_delete, file_share |
| Docs | `GoogleDocsAdapter` | document_create, document_get |
| Forms | `GoogleFormsAdapter` | form_create, form_get |
| Meet | `GoogleMeetAdapter` | meeting_create, meeting_get |
| Gmail | `GmailAdapter` | message_send, message_list, message_get |

### Known Issues

| Issue | Severity | Mitigation |
|-------|----------|------------|
| OAuth token expiry (1 hour) | HIGH | Automatic refresh before expiry |
| Per-service rate limits | MEDIUM | Separate circuit breaker per service |
| Large spreadsheet operations timeout | MEDIUM | Batch operations, increase timeout |

---

## 6. Airtable Adapter

### Overview

| Attribute | Value |
|-----------|-------|
| Provider | Airtable |
| Adapter Class | `AirtableAdapter` |
| Auth System | Personal access tokens (per-base) |
| Capabilities | 37 kernel operations |
| Base URL | `https://api.airtable.com/v1` |
| Rate Limit | 5 requests/second per base, 10/second per token |

### Authentication

Personal access tokens stored per-base:
```python
class AirtableAdapter(BaseAdapter):
    def __init__(self, config: AdapterConfig):
        self._config = config
        self._client = httpx.AsyncClient(
            base_url="https://api.airtable.com/v1",
            headers={"Authorization": f"Bearer {config.api_token}"},
            timeout=30.0,
        )
```

### Known Issues

| Issue | Severity | Mitigation |
|-------|----------|------------|
| Two-key circuit breaker needed (per-base + per-token) | HIGH | Two-key circuit breaker implementation |
| URL length limit (16K chars) | HIGH | Switch to POST when URL would exceed limit |
| API v0 deprecated | HIGH | Use API v1 endpoints only |
| Partial success handling | HIGH | Check records + errors in response |
| Missing 8 standard engine files | HIGH | Add all 8 files in rebuild |

### Two-Key Circuit Breaker

Airtable has two independent rate limits:
```python
class AirtableCircuitBreaker:
    """Two-key circuit breaker for per-base and per-token limits."""

    def __init__(self):
        self._base_breakers: dict[str, CircuitBreaker] = {}
        self._token_breaker = CircuitBreaker("airtable_global")

    def allow_request(self, base_id: str) -> bool:
        base_breaker = self._base_breakers.get(base_id)
        if base_breaker and not base_breaker.allow_request():
            return False
        return self._token_breaker.allow_request()
```

### URL Length Workaround

```python
def build_request(self, operation: str, params: dict) -> Request:
    url = self._build_url(operation, params)
    if len(url) > 16000:
        # Switch to POST with body params
        return Request(method="POST", endpoint=operation, body=params)
    return Request(method="GET", endpoint=operation, query_params=params)
```

---

## 7. Adapter Testing

### Contract Tests (Every Adapter Must Pass)

| Test | What It Validates |
|------|------------------|
| `test_adapter_never_raises` | call() always returns KernelResult, never raises |
| `test_adapter_does_not_mutate_params` | Input params dict is not modified |
| `test_all_kernels_have_meta` | Every capability has KERNEL_MAP entry |
| `test_all_kernels_have_schema` | Every capability has input/output schema |
| `test_health_check` | health_check() returns valid HealthStatus |
| `test_capabilities_list` | capabilities() returns all kernel_op_ids |
| `test_validate_params_rejects_invalid` | Invalid params return ValidationResult.error |
| `test_validate_params_accepts_valid` | Valid params return ValidationResult.ok |

### Param Mutation Detection

```python
@pytest.mark.parametrize("kernel_op_id", adapter.capabilities())
def test_adapter_does_not_mutate_params(kernel_op_id, adapter):
    params = {"key": "value"}
    original = copy.deepcopy(params)
    adapter.call(kernel_op_id, params, mock_binding)
    assert params == original, "Adapter mutated input params"
```

### CI Enforcement

```python
def test_all_adapters_complete():
    """Every adapter must have all 7 required files."""
    required = ["__init__.py", "adapter.py", "kernels.py", "kernel_meta.py",
                "aliases.py", "policy.py", "schema.py", "assertions.py"]
    for provider_dir in Path("engine/providers").iterdir():
        for required_file in required:
            assert (provider_dir / required_file).exists(), \
                f"Missing {required_file} in {provider_dir.name}"
```

---

## 8. Adding a New Provider

### Checklist

1. Create directory: `engine/providers/<new_provider>/`
2. Create all 8 files (__init__.py, adapter.py, kernels.py, kernel_meta.py, aliases.py, policy.py, schema.py, assertions.py, policy/execution.yaml)
3. Implement `BaseAdapter` in `adapter.py`
4. Define kernel classes in `kernels.py`
5. Add to `registry/kernel_definitions.yaml`
6. Run generators: `python -m tools.generate_kernel_meta`, `python -m tools.generate_tools`, `python -m tools.generate_migration`
7. Add to `ENGINE_MAP` in `engine/registry/engine_map.py`
8. Write contract tests in `tests/contract/`
9. Add provider-specific cautions to `CAUTIONS_BUGS.md`
10. CI must pass all checks

### Scaffold Command

```bash
make scaffold-adapter NAME=newprovider
```

This creates all 8 files with templates.

---

*End of Provider Adapters.*
