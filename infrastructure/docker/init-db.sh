#!/bin/bash
# Creates the langfuse database alongside the main one (postgres image runs
# everything in docker-entrypoint-initdb.d on first boot).
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    SELECT 'CREATE DATABASE langfuse' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
EOSQL
