# API

This folder is the HTTP boundary for V3.

Recommended direction:

- FastAPI as the transport layer
- request and response schemas in `app/schemas`
- routes in `app/routers`
- dependency wiring in `app/dependencies`

The API layer should stay thin:

- parse requests
- validate transport data
- call backend application services
- return HTTP responses

Business logic belongs in `V3/backend`, not here.
