# Database design

Keep this codebase free of foreign keys. Do not add foreign-key constraints,
SQL `REFERENCES` clauses, or enable SQLite foreign-key enforcement.
Handle any required relationship validation explicitly in application code.
