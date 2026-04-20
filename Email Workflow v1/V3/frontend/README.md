# Frontend

This folder should contain the real product UI.

Recommended direction:

- React
- TypeScript
- Vite
- React Router
- TanStack Query

Use one frontend app with route-level sections for:

- end-user inbox and daily queue
- internal review and QA
- thread detail and draft workflow

The frontend should only call the backend API. It should never read local JSON files or import backend Python modules.
