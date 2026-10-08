# The same checks CI runs, for use before a push.
.PHONY: check lint test golden scoreboard web web-measure

check: lint test

lint:
	ruff check src tests
	ruff format --check src tests
	pyright

test:
	pytest -q

# Regenerate the pinned regression numbers. Only after a change that was meant to move them.
golden:
	python -m tests.regression_cases

scoreboard:
	depot-twin scoreboard

# The front end: type-check, tests against the Python reference, and build.
web:
	cd web && npm ci && npm run typecheck && npm test && npm run build

# The measurable design laws on the built site. Needs a preview on port 4001 (cd web && npx vite preview --port 4001).
web-measure:
	cd web && npm run measure -- http://localhost:4001/
