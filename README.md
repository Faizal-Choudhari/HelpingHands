# Volunteer Management System for NGOs

A runnable NGO volunteer management web application built with Python Flask, SQLite, HTML, CSS, Bootstrap, and JavaScript.

## Features

- Three roles: Admin, Volunteer, Event Coordinator
- Volunteer registration with administrator approval
- Role-specific dashboards
- Event creation, editing, cancellation, and coordinator assignment
- Volunteer event applications and approval/rejection
- Attendance tracking (Present, Absent, Late, Excused) and hours
- Volunteer activity reports with optional file attachments and review workflow
- Announcements and in-app notifications
- Volunteer and attendance CSV exports
- Responsive layout

## Requirements

- Windows 10/11, macOS, or Linux
- Python 3.10 or newer
- Internet connection for Bootstrap and icon CDN assets (the backend itself runs locally)

## Windows setup (PowerShell)

1. Extract the ZIP file.
2. Open the extracted `Volunteer_Management_System` folder in VS Code.
3. Open Terminal > New Terminal.
4. Create a virtual environment:

   ```powershell
   py -m venv .venv
   ```

5. Activate it:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, run this once in the same terminal:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```

6. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

7. Start the application:

   ```powershell
   python app.py
   ```

8. Open this address in your browser:

   http://127.0.0.1:5000

The SQLite database is created automatically at `instance/volunteer_management.db` the first time the app starts.

## Demonstration accounts

| Role | Email | Password |
|---|---|---|
| Admin | admin@ngo.org | admin123 |
| Volunteer | volunteer@ngo.org | volunteer123 |
| Coordinator | coordinator@ngo.org | coord123 |

New volunteer registrations are pending until approved by the admin.

## First-use walkthrough

1. Log in as Admin.
2. Open Volunteers and approve pending registrations.
3. Create an event and optionally assign the Coordinator account.
4. Log in as Volunteer and apply for the event.
5. Log in as Admin or the assigned Coordinator and approve the application.
6. Mark attendance and enter the hours contributed.
7. Log in as Volunteer and submit an activity report.
8. Review the report as Admin or the assigned Coordinator.

## Database reset

Stop the server and delete `instance/volunteer_management.db`. Start the app again to recreate the database and demonstration accounts.

## Important deployment notes

- This project is configured for local development.
- Before public deployment, set a strong random `SECRET_KEY` environment variable.
- Turn off Flask debug mode in production.
- Use HTTPS and a production WSGI server (for example, Waitress on Windows or Gunicorn on Linux).
- For production, use a managed database, restrict uploaded file access, and configure backups.
- Bootstrap and Font Awesome are loaded from CDNs.

## Current scope

PDF reporting is not included as a server-side PDF generator in this starter delivery. CSV exports are implemented, and browser print-to-PDF can be used from the report pages. Additional modules such as email delivery, password reset, QR attendance, and multi-NGO tenancy can be added later.
