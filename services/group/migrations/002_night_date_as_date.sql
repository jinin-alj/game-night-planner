-- night_date has held YYYY-MM-DD text since 001; as a real DATE the database itself rejects impossible dates and sorts nights in true date order, and SQL Server converts every existing ISO date in place, so no night loses its date
ALTER TABLE nights ALTER COLUMN night_date DATE NOT NULL;
