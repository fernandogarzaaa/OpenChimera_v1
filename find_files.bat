@echo off
cd /d D:\appforge-main
findstr /s /m "invalidateQueries(" *.ts *.tsx 2>nul
