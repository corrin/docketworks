-- This script drops and recreates the dw_msm_dev database
-- It preserves the character set and collation settings
-- Note: User accounts are preserved as they are stored in the MySQL system database

-- Show current databases before drop
SELECT 'Databases before drop:' as status;
SHOW DATABASES LIKE 'dw_msm_dev';

-- Drop the database
SELECT 'Dropping database...' as status;
DROP DATABASE IF EXISTS dw_msm_dev;

-- Confirm database was dropped
SELECT 'Databases after drop:' as status;
SHOW DATABASES LIKE 'dw_msm_dev';

-- Recreate the database with the same character set and collation
SELECT 'Creating database...' as status;
CREATE DATABASE dw_msm_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Confirm database was created
SELECT 'Databases after creation:' as status;
SHOW DATABASES LIKE 'dw_msm_dev';

-- Create the django_user (drop first if exists)
SELECT 'Creating database user...' as status;
DROP USER IF EXISTS 'django_user'@'%';
CREATE USER 'django_user'@'%' IDENTIFIED BY 'cur-fiasco-pectin';
-- NOTE: Password should match the one in the .env file
-- Obviously this is insecure.  This file is in git!
-- It does not matter as it's a dev-only password

-- Grant privileges to django_user@'%' (wildcard matches all hosts including 127.0.0.1)
SELECT 'Granting privileges...' as status;
GRANT ALL PRIVILEGES ON dw_msm_dev.* TO 'django_user'@'%';
GRANT ALL PRIVILEGES ON dw_msm_test.* TO 'django_user'@'%';

-- Flush privileges to ensure changes take effect
FLUSH PRIVILEGES;
SELECT 'Reset complete!' as status;
