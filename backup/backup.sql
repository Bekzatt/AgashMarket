DECLARE @BackupFileName NVARCHAR(255);
DECLARE @FileName NVARCHAR(255);
DECLARE @DateTime NVARCHAR(20);

-- Получаем текущее время в формате ГГГГММДД_ЧЧММСС
SET @DateTime = REPLACE(CONVERT(NVARCHAR, GETDATE(), 112), '-', '') + '_' + REPLACE(CONVERT(NVARCHAR, GETDATE(), 108), ':', '');
-- Формируем имя файла резервной копии
SET @BackupFileName = 'C:\\backup\\AgashGroup_' + @DateTime + '.bak';
SET @FileName = 'AgashGroup'+ @DateTime;
BACKUP DATABASE [AgashGroup]
TO DISK = @BackupFileName
WITH NOFORMAT, NOINIT,  NAME = @FileName, SKIP, NOREWIND, NOUNLOAD,  STATS = 10

--sqlcmd -S servername\instancename -U yourusername -P yourpassword -i C:\path\to\backup.sql
-- -S servername\instancename — имя вашего SQL Server (например, localhost\SQLEXPRESS).
-- -U yourusername — имя пользователя SQL Server.
-- -P yourpassword — пароль пользователя SQL Server.
-- -i C:\path\to\backup.sql — путь к файлу SQL, содержащему команду резервного копирования.
