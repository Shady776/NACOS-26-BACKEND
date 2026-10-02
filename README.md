# University Connect: Backend

FastAPI + SQLite (PostgreSQL in production) API for the University Connect learning management system (NACOS Connect '26). It serves the student, teacher and admin dashboards.

- Runs on: http://127.0.0.1:8000
- Frontend: lives in a separate repo/folder (`nacoskdu`). See its own README. Both must be running at the same time, each in its own terminal.

Commands below are for **Windows PowerShell** in **VS Code**, run from the `University Connect` folder (the one that contains the `app` folder).

> **Deploying?** Set `ENVIRONMENT=production` and `DB_URL` (PostgreSQL) on your host. See [Deploying to production](#deploying-to-production).

---

## Prerequisites

- **Python 3.12** (the project's `.python-version` is 3.12). Check with `python --version`.
- **VS Code** with the **Python** extension installed.

---

## 1. Open the project

In VS Code: **File > Open Folder** and choose `University Connect`. Then open a terminal with **Ctrl + `** (backtick).

## 2. Create the virtual environment

```powershell
python -m venv venv
```

If you have several Python versions installed, use `py -3.12 -m venv venv` instead.

This creates a `venv` folder inside the project. Every project should have its own, so packages from one project never leak into another.

## 3. Select the interpreter in VS Code

1. Press **Ctrl + Shift + P**.
2. Type **Python: Select Interpreter** and press Enter.
3. Pick the one that shows `.\venv\Scripts\python.exe`. If it is not listed, choose **Enter interpreter path... > Find...** and browse to `University Connect\venv\Scripts\python.exe`.

## 4. Make the terminal use the venv

Close the current terminal (trash icon) and open a new one with **Ctrl + `**. Once the interpreter is selected, VS Code activates the venv automatically and your prompt starts with `(venv)`.

If it does not, activate it manually:

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell says running scripts is disabled, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**Check that you are using the right venv** (important if you have other projects on the same PC):

```powershell
python -c "import sys; print(sys.executable)"
```

The path printed must end with `University Connect\venv\Scripts\python.exe`. If it points to another project's folder, you are in the wrong environment. Repeat steps 3 and 4.

## 5. Install the requirements

With `(venv)` showing in the prompt:

```powershell
pip install -r requirements.txt
```

Whenever you add a new package, install it and add its name to `requirements.txt`.

## 6. Create the `.env` file

The app will not start without a `.env` file in the project root (next to the `app` folder, not inside it).

**How to know what goes in it:** open `app/config.py`. Every line in the `Settings` class is a variable the app needs:

```python
class Settings(BaseSettings):
    DB_URL: str
    SECRET_KEY: str
    ...
```

A field with no default value is **required**. If one is missing, the app stops at startup with an error that names the missing variable. So the process is: read `config.py`, make sure each name there exists in `.env`.

Create a file called `.env` and fill it in:

```env
# Database: keep this on SQLite locally (see "Deploying to production" below)
DB_URL=sqlite:///./database.db

# JWT / security
SECRET_KEY=paste-a-long-random-string-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15

# First admin account (created automatically on first startup)
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=choose-a-strong-password
ADMIN_FULLNAME=System Administrator

# AI grading (OpenRouter)
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=openai/gpt-oss-120b

# File uploads (Cloudinary)
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
```

Where each value comes from:

| Variable | What it is / where to get it |
| --- | --- |
| `DB_URL` | Required by `config.py`, so it must always be present. **Locally the app ignores it** and uses SQLite. It is only used when `ENVIRONMENT=production`. Local value: `sqlite:///./database.db`. Production value: your PostgreSQL URL. |
| `SECRET_KEY` | Signs login tokens. Generate one: `python -c "import secrets; print(secrets.token_hex(32))"`. Keep it private. |
| `ALGORITHM` | `HS256`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | How long the short-lived login token lasts, in minutes. Use `15` (the browser refreshes it automatically). |
| `ADMIN_USERNAME` | Admin login name. **Use lowercase**: the login page lowercases whatever is typed. |
| `ADMIN_EMAIL`, `ADMIN_FULLNAME` | Admin details. The full name appears in the sidebar. |
| `ADMIN_PASSWORD` | Admin password. |
| `OPENROUTER_API_KEY` | Create an account at https://openrouter.ai and make a key under **Keys**. |
| `OPENROUTER_MODEL` | A model ID copied from https://openrouter.ai/models, for example `openai/gpt-oss-120b`. Models ending in `:free` come and go: if grading fails with a 404 "model is unavailable", pick another model or use the paid version of the same one (it needs credit on your OpenRouter account). Restart the server after changing it. |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Create an account at https://cloudinary.com. All three are on the **Dashboard** (Product Environment Credentials). |

A copy of this template is in `.env.example`: copy it to `.env` and fill in the values.

### Optional variables (all have defaults)

You do **not** need these locally. They matter when you deploy (see [Deploying to production](#deploying-to-production)).

| Variable | Default | What it does |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `production` switches to PostgreSQL (`DB_URL`), hides `/docs` and makes cookies `Secure`. **Never set it in your local `.env`.** |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | How long a student stays logged in without typing their password again. |
| `ALLOWED_ORIGINS` | empty | Deployed frontend address(es), comma-separated. Needed for CORS and the CSRF check. Localhost addresses are always allowed. |
| `API_PATH_PREFIX` | empty | `/api` when the frontend host forwards `/api/*` to this backend. |
| `COOKIE_SAMESITE` | `lax` | Leave as is unless you know you need a cross-site setup. |
| `COOKIE_SECURE` | `false` | Cookies are already `Secure` in production. Rarely needed. |

Notes:
- **Keep your local `.env` on SQLite and do not set `ENVIRONMENT=production` locally.** Otherwise the app uses `DB_URL`, and if that is your hosted PostgreSQL database, running locally will read and change your **live data**.
- No spaces or quotes around values, and one variable per line.
- `.env` is listed in `.gitignore`. **Never commit it or share it**, because it holds your secrets. If a key is ever exposed, regenerate it.
- Changing the admin values after the admin already exists will not update that account. The admin is only created the first time.

## 7. Run the backend

From the project root, with `(venv)` active:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

`alembic upgrade head` updates your local `database.db` to the latest tables. You only need it once after pulling changes that add tables or columns (a brand-new `database.db` does not need it). After that, start the server with just the second line.

You should see `Uvicorn running on http://127.0.0.1:8000`. On the very first run you will also see `ADMIN CREATED SUCCESSFULLY!!!`.

- API: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs

`--reload` restarts the server whenever you save a file. Stop it with **Ctrl + C**.

Teacher and admin accounts are created from the admin dashboard (frontend). Students sign up on the signup page.

---

# Deploying to production

These steps work on any host that runs a Python web service and offers PostgreSQL: Railway, Render, Fly.io, Heroku-style platforms, or your own server (VPS). Only the place where you click differs.

SQLite is a single file, which is fine for development but not for deployment: most hosts wipe the app's disk on every redeploy, and SQLite does not handle many users at once. For production, use **PostgreSQL**.

The database is chosen by one variable, `ENVIRONMENT`. Nothing in the code needs editing:

- `ENVIRONMENT=production` uses PostgreSQL from `DB_URL`, hides `/docs`, and sends login cookies as `Secure`.
- Anything else (or not set) uses the local SQLite file `database.db`.

## Step 1: Create the database

1. Create a PostgreSQL database on your host (on Railway: **New > Database > PostgreSQL**).
2. Copy its connection URL:
   ```
   postgresql://USER:PASSWORD@HOST:PORT/DBNAME
   ```
   A URL starting with `postgres://` also works, because the app converts it automatically.

## Step 2: Set the environment variables

Set these in your host's **Variables / Environment** settings (never in a committed file). The complete list is in the block after this table:

| Variable | Production value |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `DB_URL` | The PostgreSQL URL from step 1. |
| `SECRET_KEY` | A new random value, not the one you use locally. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15`. The browser refreshes the login automatically, so this can be short. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Optional. Default `7`: students stay logged in up to 7 days. |
| `ALLOWED_ORIGINS` | The address(es) of the deployed frontend, comma-separated, for example `https://your-app.vercel.app`. This controls CORS and the CSRF origin check. |
| `API_PATH_PREFIX` | `/api` if the frontend host forwards `/api/*` to this backend (recommended, see "Login cookies" below). Empty if the browser calls the backend address directly. |
| `COOKIE_SAMESITE` | Optional. Default `lax`. Only use `none` for a cross-site setup (not recommended). |

A complete set for a typical deploy (Railway, Render, ...), with your own values:

```env
ENVIRONMENT=production
DB_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
SECRET_KEY=a-new-long-random-string
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
ALLOWED_ORIGINS=https://your-app.vercel.app
API_PATH_PREFIX=/api
ADMIN_USERNAME=admin
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=a-strong-password
ADMIN_FULLNAME=System Administrator
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=openai/gpt-oss-120b
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
```

## Step 3: Install and start the app

Install the requirements (`psycopg2-binary` must be listed in `requirements.txt`; it is the PostgreSQL driver), then set this as the host's **start command**:

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2 --proxy-headers --forwarded-allow-ips="*"
```

What each part does:

| Part | Why |
| --- | --- |
| `alembic upgrade head` | Updates the database tables to match the code. It is safe to run on every start: if nothing changed, it does nothing. Run it **before** uvicorn so the new code never meets old tables. |
| `--host 0.0.0.0` | Accept connections from outside the machine. |
| `--port $PORT` | Railway, Render and Heroku give you the port in a variable called `PORT`. On a VPS, use a fixed number such as `--port 8000` instead. |
| `--workers 2` | Two server processes. Password checking (bcrypt) is slow and uses one CPU core per process, so this roughly doubles how many students can log in at once. Use one worker per CPU core, up to about 4. |
| `--proxy-headers --forwarded-allow-ips="*"` | Behind the host's proxy, every request looks like it comes from the proxy. These flags make the app see each student's real IP, so rate limiting works per person. |

Do **not** use `--reload` in production.

On your own server (VPS), run the same command under a process manager (systemd, Docker, or similar) so it restarts after a crash, and put nginx or Caddy in front for HTTPS.

On first start the app creates all missing tables and the admin account.

## Step 4: Connect the frontend

Point the frontend at the deployed backend (see the frontend README).

## Login cookies

Login uses **HttpOnly cookies**: a short-lived access token (15 minutes) and a refresh token (7 days, stored hashed in the database, so logout really ends the session). The browser refreshes the access token automatically.

For cookies to work in every browser, **especially Safari on iPhone**, the browser must see the frontend and the API as **one site**. Pick one:

- **Recommended:** the frontend host forwards `/api/*` to this backend (on Vercel, a rewrite in `vercel.json`). Set `API_PATH_PREFIX=/api` here, and `VITE_API_URL=/api` on the frontend.
- Or put both under one domain: `app.yourdomain.com` and `api.yourdomain.com`. Leave `API_PATH_PREFIX` empty.

If the frontend and backend are on two unrelated domains (for example `something.vercel.app` and `something.up.railway.app`), Safari blocks the cookies and those students cannot log in.

## Database migrations (Alembic)

Tables are only created automatically, never changed. When you add, rename or remove a column, or add a new value to an enum (a role, a status), create a migration from the project root:

```bash
alembic revision -m "describe the change"   # then edit the new file in alembic/versions/
alembic upgrade head                        # apply it
```

- Locally, `alembic upgrade head` updates your `database.db`. Run it once after pulling these changes if you already have a `database.db`. You can skip it by deleting `database.db` and letting the app create a fresh one.
- In production it already runs on every start (Step 3).
- Alembic reads the database from the same place as the app (`ENVIRONMENT` and `DB_URL`), so you never configure a URL for it.
- The first migration after the baseline adds the `refresh_tokens` table, the `saved_answers` column, the one-attempt-per-student-per-test rule, and indexes. If students already have duplicate attempts for the same test, it stops and tells you; delete the extra rows and run it again.

## Before a live test

- Run a load test (Locust or k6, about 500 virtual users: staggered logins, then `/start`, then `/submit`) against the **deployed** setup, not a laptop.
- Ask students to log in 10 to 15 minutes early, because logins are the slowest step.
- Watch the host logs during the test. Lines starting with `timing` show slow `/start`, `/submit` and answer-save requests.

## Things to know

- **Your existing SQLite data does not move over.** A new PostgreSQL database starts empty. Re-create users and courses, or export and import the data yourself.
- **PostgreSQL enforces foreign keys, SQLite does not.** Deleting a record that other records depend on fails instead of silently leaving broken data. The delete code in this project handles this for users and courses.
- Never commit the database URL or password. It belongs in the host's environment variables only.
- Your local `.env` should not set `ENVIRONMENT=production`. If it does, and `DB_URL` points to the live database, running the app locally will read and change your **live data**.
- If a secret (`SECRET_KEY`, API keys, admin password) was ever shared or committed, replace it. Changing `SECRET_KEY` logs everyone out.

---

# Troubleshooting

| Problem | Fix |
| --- | --- |
| `ModuleNotFoundError: No module named ...` | The venv is not active or you are in the wrong one. Check that `(venv)` shows, check `sys.executable` (step 4), then run `pip install -r requirements.txt`. |
| Students are logged out right away, or login works on desktop but not on iPhone | Cookies are blocked because the frontend and API are on different sites. Forward `/api/*` from the frontend host to this backend and set `API_PATH_PREFIX=/api` (see "Login cookies"). |
| `ModuleNotFoundError: No module named 'psycopg2'` | `psycopg2-binary` is missing from `requirements.txt` on the deployed app. Add it and redeploy. |
| `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`. |
| `ValidationError ... Field required` on startup | A variable from `app/config.py` is missing in `.env`. The error names it. |
| `.env` changes are ignored | Run uvicorn from the project root, where `.env` lives, and restart the server. |
| Cannot log in as admin | Use the lowercase `ADMIN_USERNAME` from `.env`. Login is limited to 5 attempts per minute, so wait a minute after repeated failures. |
| Frontend shows a CORS error | The backend only allows the frontend on the origins listed in `allow_origins` in `app/main.py` (ports 8080 and 5173 locally). Add the deployed frontend address for production. |
| Deployed app works but data disappears after each redeploy | `ENVIRONMENT=production` is not set on the host, so the app is using SQLite. Set it, and set `DB_URL` (see [Deploying to production](#deploying-to-production)). |
| `NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgres` | The URL starts with `postgres://` and is not being converted. Make sure `ENVIRONMENT=production` is set, because only then does `database.py` use `_normalize_db_url(CONFIG.DB_URL)`. |
| `server closed the connection unexpectedly` on PostgreSQL | The host dropped an idle connection. `pool_pre_ping` and `pool_recycle` in `database.py` prevent this. Make sure they were not removed. |
| `character varying = uuid` or other SQL type errors on PostgreSQL | An ID from the URL was compared to the database without converting it to text. Declare route ID parameters as `str`, or wrap them in `str(...)`. |
| Port already in use | Another copy is running. Stop it with Ctrl + C, or use a different port: `uvicorn app.main:app --reload --port 8001` (then update `BASE_URL` in the frontend). |

---

# Project structure

```
University Connect/
├── app/
│   ├── main.py              app entry point
│   ├── config.py            reads .env, defines required variables
│   ├── database.py          database connection (SQLite locally, PostgreSQL in production)
│   ├── models.py            database tables
│   ├── schemas.py           request/response shapes
│   ├── oauth2.py            login cookies, access/refresh tokens, role checks
│   ├── routes/              API endpoints (admin, auth, courses, ...)
│   ├── services/            AI grading
│   └── utils/               helpers (admin setup, hashing, uploads, rate limit, HTML sanitizing)
├── alembic/                 database migrations (run: alembic upgrade head)
├── alembic.ini
├── .env                     your secrets (not committed)
├── requirements.txt
└── venv/                    virtual environment (not committed)
```