# OpenAPI

`openapi.json` is the source of truth for the API contract. The frontend generates
`src/types/api.ts` from it — never edit that file by hand.

## Regenerate the schema (run after any backend schema change)

```powershell
# From the project root
python -c "from api.app.main import app; import json; print(json.dumps(app.openapi(), indent=2))" > shared/openapi/openapi.json
```

## Regenerate frontend types

```bash
cd frontend
npm run generate:types    # writes src/types/api.ts from shared/openapi/openapi.json
```

## Check for drift (CI)

```bash
cd frontend
npm run check:types-drift  # exits 1 if src/types/api.ts is out of sync
```

## Workflow for schema changes

1. Change a Pydantic schema in `api/app/schemas/`.
2. Regenerate `openapi.json` (command above).
3. Run `npm run generate:types` in `frontend/`.
4. Commit both files together.
