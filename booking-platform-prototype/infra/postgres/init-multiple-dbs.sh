#!/bin/bash
# Создаёт по отдельной базе данных на каждый сервис, использующий PostgreSQL.
# Реализует паттерн "Database per Service" на одном экземпляре Postgres
# (в проде каждая БД выносится на свой инстанс/кластер).
set -e

for DB in user_db catalog_db booking_db payment_db; do
  echo "Creating database: $DB"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    SELECT 'CREATE DATABASE $DB'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB')\gexec
EOSQL
done
