# OpenAPI

Expose the FastAPI schema here once the backend dependencies are installed:

```powershell
python -c "from api.app.main import app; import json; print(json.dumps(app.openapi(), indent=2))" > shared/openapi/openapi.json
```
