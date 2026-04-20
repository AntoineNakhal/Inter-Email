# Backend

This folder contains the product core.

Internal sub-layers:

- `core/`: config, logging, security, shared backend setup
- `application/`: use-case orchestration and workflows
- `domain/`: business concepts and pure rules
- `providers/`: Gmail and AI adapters
- `persistence/`: repositories, models, migrations
- `jobs/`: sync and analysis runners

This folder should be importable by both:

- the API service
- a future worker process

That keeps deployment simple now and flexible later.
