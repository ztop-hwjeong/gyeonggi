SELECT 'CREATE DATABASE gyeonggi_prefect OWNER gyeonggi'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'gyeonggi_prefect')
\gexec
