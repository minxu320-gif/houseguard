-- =============================================================================
-- 不要用 CMD 直接执行本文件！请用 MySQL Workbench 打开后执行，或 mysql.exe 登录后再粘贴。
-- 详细步骤见：scripts/WINDOWS_MYSQL_执行说明.txt
-- =============================================================================
-- 将下面 YOUR_PASSWORD 改成你在 Workbench 里能登录 root 的密码（建议与 .env 里 MYSQL_PASSWORD 一致）。

ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'YOUR_PASSWORD';
FLUSH PRIVILEGES;

-- 若你实际登录身份是 root@127.0.0.1，可再执行一行（按需二选一或都执行）：
-- ALTER USER 'root'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY 'YOUR_PASSWORD';
-- FLUSH PRIVILEGES;
