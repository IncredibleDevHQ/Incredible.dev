-- The browser never gets this role or its credential. Each verified Auth user has a
-- non-exposed schema owned by the trusted application, with RLS enabled on its tables.
DO $$
DECLARE credential text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM vault.secrets WHERE name = 'incredible_app_database_password') THEN
    PERFORM vault.create_secret(encode(extensions.gen_random_bytes(32), 'hex'), 'incredible_app_database_password');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'incredible_app') THEN
    SELECT decrypted_secret INTO credential FROM vault.decrypted_secrets WHERE name = 'incredible_app_database_password';
    EXECUTE format('CREATE ROLE incredible_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS', credential);
  END IF;
END $$;
GRANT CONNECT, CREATE ON DATABASE postgres TO incredible_app;
ALTER ROLE incredible_app SET statement_timeout = '60s';
ALTER ROLE incredible_app SET idle_in_transaction_session_timeout = '30s';
