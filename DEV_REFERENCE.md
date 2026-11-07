# DevResolve AI — Master Developer & Architecture Reference

> **Important Developer Notice**: This file is the single-source-of-truth reference for the DevResolve AI codebase. When modifying, creating, or inspecting any feature, consult this document first instead of reading through all repository files. Keep this document updated whenever any routes, models, schemas, or workflows change.

---

## 1. Quick System Overview & Running Status

- **App Name**: DevResolve AI
- **Framework**: FastAPI (Python 3.13) + Uvicorn
- **Frontend**: Jinja2 Server-Side Templates + Tailwind CSS (CDN) + FontAwesome 6.5 + Vanilla JS
- **Database**: SQLite (SQLAlchemy ORM) at `data/devresolve.db`
- **Vector Store**: Qdrant Cloud (`Runbookpilot_google` collection)
- **Embedding Engine**: Google Gemini Embeddings (`gemini-embedding-001`, 768 dims)
- **LLM Engine**: Groq API (`openai/gpt-oss-120b`)
- **Default Port**: `8000` (`http://localhost:8000` or `http://127.0.0.1:8000`)
- **Startup Command**:
  ```powershell
  python -m uvicorn app:app --host 0.0.0.0 --port 8000
  ```

### Pre-Seeded Default Accounts

| Role | Name | Email | Password | Status / Assigned Team |
| :--- | :--- | :--- | :--- | :--- |
| **Project Manager** | System Manager | `admin@devresolve.ai` | `Admin@123` | Manager of *DevResolve Platform* |
| **Frontend Dev** | Alex Rivera | `frontend@example.test` | `Dev@123` | Approved, `frontend` role |
| **Backend Dev 1** | Rahul Sharma | `backend1@example.test` | `Dev@123` | Approved, `backend` role |
| **Backend Dev 2** | David Kim | `backend2@example.test` | `Dev@123` | Approved, `backend` role |
| **QA Engineer** | Sara Jenkins | `qa@example.test` | `Dev@123` | Approved, `qa` role |
| **Pending Dev** | Elena Rostova | `pending@example.test` | `Dev@123` | Pending access request |

> **Development Mode OTP**:
> - When testing locally (without live SMTP credentials), the active OTP is displayed directly on the verification screen with a 1-click **Auto Fill** button.
> - Additionally, master code `123456` is universally accepted for any account in development mode.

---

## 2. Complete File & Directory Map

```
d:\Ai project\DevResolve AI/
├── app.py                      # FastAPI app instance, middleware, startup hooks, root & health routes
├── DEV_REFERENCE.md            # [THIS FILE] Master reference guide
├── .env                        # Production/local API keys and environment variables
├── .env.example                # Example environment file template
├── requirements.txt            # Python dependencies
├── data/
│   ├── devresolve.db           # SQLite database for users, tickets, projects, updates
│   └── rag_memory.sqlite       # SQLite checkpointer for LangGraph Self-RAG memory
├── documents/                  # Reference runbooks & markdown docs ready for RAG ingestion
├── uploads/                    # User-uploaded documents (PDF, MD, DOCX, TXT)
├── src/
│   ├── config.py               # Pydantic Settings: loads .env, holds LLM, DB, and OAuth configs
│   ├── database.py             # SQLAlchemy models, engine, session factory, enum definitions & default seeder
│   ├── templates.py            # render_template helper function for Starlette >= 0.35 Jinja2 compatibility
│   ├── auth/
│   │   ├── hash.py             # bcrypt-based password hashing & verification (Python 3.13 clean)
│   │   ├── jwt_handler.py      # JWT creation, decoding, cookie extraction, role dependency guards
│   │   ├── otp.py              # 6-digit OTP generation, expiration check, and SMTP email dispatcher
│   │   └── google_oauth.py     # Authlib Google OAuth2 client integration
│   ├── rag/
│   │   ├── vectorstore.py      # Qdrant client connection & Google GenerativeAI Embeddings setup
│   │   ├── ingestion.py        # File loader (PDF, DOCX, TXT, MD), recursive chunker, Qdrant indexing
│   │   └── self_rag.py         # LangGraph Self-RAG ticket issue diagnosis & grounded solution generator
│   └── routers/
│       ├── auth.py             # Authentication router: /auth/login, /auth/register, /auth/verify-otp, /auth/google
│       ├── manager.py          # Manager router: /manager/dashboard, /manager/requests, /manager/tickets, /manager/team
│       └── developer.py        # Developer router: /developer/dashboard, /developer/my-issues, /developer/ticket/{id}
└── templates/
    ├── base.html               # Main layout: Tailwind, FontAwesome, global toast & modal handlers
    ├── landing.html            # Public marketing landing page with features & workflow steps
    ├── auth/
    │   ├── login.html          # Dual tab login (Developer with Google/OTP, Manager direct)
    │   ├── register.html       # Developer registration with dynamic project manager lookup
    │   ├── otp_verify.html     # 6-digit OTP input form with countdown timer
    │   ├── google_register.html# Google OAuth onboarding project selection form
    │   └── pending.html        # "Waiting for Manager Approval" screen
    ├── manager/
    │   ├── _sidebar.html       # Manager navigation sidebar partial
    │   ├── dashboard.html      # KPI stats, recent access requests, recent tickets table
    │   ├── requests.html       # Pending access requests review + role assignment (Approve/Reject)
    │   ├── tickets.html        # Comprehensive ticket list, filters, manager resolution approval
    │   ├── team.html           # Active project developers list and role reassignment controls
    │   └── documents.html      # Project documentation list with indexed chunk counts
    └── developer/
        ├── _sidebar.html       # Developer navigation sidebar partial
        ├── dashboard.html      # Dev metrics, team queue tickets, daily updates, upload doc modal
        ├── my_issues.html      # Raised tickets list with status filters & "+ Raise a Query" modal
        └── ticket_detail.html  # Ticket view, AI RAG solution display, team claim button, resolution remark box
```

---

## 3. Database Schema & Data Models (`src/database.py`)

### Enums
- **`UserRole`**: `manager`, `developer`
- **`DevRole`**: `frontend`, `backend`, `database`, `devops`, `qa`, `fullstack`, `mobile`, `unassigned`
- **`AccessStatus`**: `pending`, `approved`, `rejected`
- **`TicketStatus`**: `open`, `in_progress`, `resolved`, `closed`
- **`TicketPriority`**: `low`, `medium`, `high`, `critical`
- **`TicketTeam`**: `frontend`, `backend`, `database`, `devops`, `qa`, `fullstack`, `mobile`

### Core Tables

#### 1. `projects`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | Integer | PK, Auto | Project unique ID |
| `name` | String(200) | Unique, Not Null | Project name |
| `description`| Text | Default "" | Description |
| `manager_id` | Integer | FK(`users.id`) | Assigned Project Manager |
| `created_at` | DateTime| UTC Default | Creation timestamp |

#### 2. `users`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | Integer | PK, Auto | User unique ID |
| `email` | String(255)| Unique, Index | User email address |
| `name` | String(255)| Not Null | User full name |
| `role` | Enum(`UserRole`) | Not Null | `manager` or `developer` |
| `dev_role` | Enum(`DevRole`) | Default `unassigned` | Technical specialization |
| `google_id` | String(255)| Nullable, Unique | Google OAuth subject ID |
| `password_hash`| String(255)| Nullable | bcrypt password hash |
| `otp_secret` | String(100)| Nullable | Current active 6-digit OTP |
| `otp_expires_at`| DateTime| Nullable | OTP expiration time |
| `is_approved`| Boolean | Default `False` | Manager approval status |
| `is_active` | Boolean | Default `True` | Account active flag |
| `avatar_url` | String(500)| Nullable | Avatar image URL |
| `project_id` | Integer | FK(`projects.id`) | Project foreign key |
| `created_at` | DateTime| UTC Default | Signup timestamp |

#### 3. `access_requests`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | Integer | PK, Auto | Request unique ID |
| `developer_id`| Integer | FK(`users.id`) | Requesting developer |
| `project_id` | Integer | FK(`projects.id`) | Requested project |
| `status` | Enum(`AccessStatus`)| Default `pending`| `pending`, `approved`, `rejected` |
| `created_at` | DateTime| UTC Default | Submission timestamp |
| `reviewed_at`| DateTime| Nullable | Manager decision timestamp |

#### 4. `tickets`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | Integer | PK, Auto | Ticket unique ID |
| `title` | String(500)| Not Null | Issue headline |
| `description`| Text | Not Null | Detailed repro steps / error details |
| `raised_by_id`| Integer | FK(`users.id`) | Ticket reporter |
| `project_id` | Integer | FK(`projects.id`) | Associated project |
| `assigned_team`| Enum(`TicketTeam`)| Not Null | Team responsible (e.g. `backend`) |
| `priority` | Enum(`TicketPriority`)| Default `medium` | `low`, `medium`, `high`, `critical` |
| `status` | Enum(`TicketStatus`)| Default `open` | `open`, `in_progress`, `resolved` |
| `ai_solution`| Text | Nullable | Markdown solution generated by Self-RAG |
| `ai_route` | String(100)| Nullable | Knowledge origin ("Project Documentation" or "General Knowledge") |
| `ai_sources` | Text | Nullable | JSON array of retrieved documents & pages |
| `created_at` | DateTime| UTC Default | Created timestamp |
| `updated_at` | DateTime| UTC Default | Last updated timestamp |

#### 5. `ticket_assignments`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | Integer | PK, Auto | Assignment unique ID |
| `ticket_id` | Integer | FK(`tickets.id`) | Foreign key to ticket |
| `developer_id`| Integer | FK(`users.id`) | Assigned developer |
| `is_accepted`| Boolean | Default `False` | `True` when dev claims the ticket |
| `accepted_at`| DateTime| Nullable | Timestamp of claim |
| `remark` | Text | Nullable | Developer resolution explanation |
| `remark_locked`| Boolean | Default `False` | Set to `True` once manager approves |
| `is_resolved`| Boolean | Default `False` | Completion flag |

#### 6. `daily_updates`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | Integer | PK, Auto | Update unique ID |
| `developer_id`| Integer | FK(`users.id`) | Developer who posted |
| `content` | Text | Not Null | Daily work report content |
| `created_at` | DateTime| UTC Default | Timestamp |

#### 7. `documents`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | Integer | PK, Auto | Document ID |
| `filename` | String(500)| Not Null | Stored file name in `uploads/` |
| `original_name`| String(500)| Not Null | Uploaded file name |
| `project_id` | Integer | FK(`projects.id`) | Associated project |
| `uploaded_by_id`| Integer | FK(`users.id`) | Developer/Manager uploader |
| `chunks_indexed`| Integer | Default 0 | Number of vector chunks in Qdrant |
| `file_size` | Integer | Default 0 | File size in bytes |
| `created_at` | DateTime| UTC Default | Upload timestamp |

---

## 4. API Endpoints Directory

### Authentication (`src/routers/auth.py`)
- `GET /auth/login` → Render login view (tabs for Dev and Manager).
- `POST /auth/login` → Authenticate user credentials. Generates 6-digit OTP and renders OTP verification.
- `POST /auth/verify-otp` → Verifies submitted OTP against expiry, sets HTTP-only JWT cookie `access_token`, redirects to dashboard.
- `GET /auth/register` → Render developer registration form.
- `POST /auth/register` → Create developer record with `is_approved=False` and creates an `AccessRequest`.
- `GET /auth/google` → Redirects to Google OAuth authorization URL.
- `GET /auth/google/callback` → Google OAuth return callback.
- `POST /auth/google/register` → Finalize Google user onboarding with project selection.
- `GET /auth/project-info/{project_id}` → Returns JSON `{"project_name": str, "manager_name": str, "manager_email": str}`.
- `GET /auth/logout` → Deletes `access_token` cookie and redirects to login.

### Manager Portal (`src/routers/manager.py`)
- `GET /manager/dashboard` → KPI cards (Pending requests, active devs, open tickets, resolved tickets), recent request queue, and tickets table.
- `GET /manager/requests` → List of pending access requests and historical reviews.
- `POST /manager/requests/{req_id}/approve` → Approves access request, sets developer `is_approved=True`, assigns `dev_role` (e.g. `frontend`, `backend`), sends welcome email.
- `POST /manager/requests/{req_id}/reject` → Sets access request to `rejected`.
- `GET /manager/tickets` → Complete project ticket overview with status/team search filters and approve resolution action.
- `POST /manager/tickets/{ticket_id}/approve-resolution` → Changes ticket status to `resolved` and sets `remark_locked=True` on the assignment.
- `GET /manager/team` → Displays all approved team members and their roles.
- `POST /manager/team/{dev_id}/update-role` → Updates developer's `dev_role`.
- `GET /manager/documents` → Displays all uploaded project documentation and Qdrant index counts.

### Developer Portal (`src/routers/developer.py`)
- `GET /developer/dashboard` → Metrics (Total raised, in progress, open/pending, resolved), active team tickets, daily update history.
- `GET /developer/my-issues` → List of tickets raised by logged-in developer with filters and modal trigger to raise a new query.
- `POST /developer/raise-ticket` → Creates new ticket, auto-assigns it to all project developers with matching `dev_role`, runs the AI Self-RAG pipeline asynchronously to generate solution, stores solution and citations on ticket.
- `GET /developer/ticket/{ticket_id}` → Protected ticket view displaying description, AI solution, assigned devs, claim action, and resolution remark box.
- `POST /developer/ticket/{ticket_id}/accept` → **Atomic Claim**: If not claimed yet, marks `is_accepted=True` for this developer and sets ticket status to `in_progress`.
- `POST /developer/ticket/{ticket_id}/remark` → Assignee submits solution remark (allowed only if `remark_locked == False`).
- `POST /developer/daily-update` → Appends a daily report entry to developer's timeline.
- `POST /developer/upload-document` → Handles multipart file upload (PDF, TXT, MD, DOCX), splits into 800-char chunks, creates embeddings, uploads to Qdrant, and saves `Document` record.

---

## 5. End-to-End Business Logic & Workflows

### A. Developer Registration & Project Manager Linkage
1. Developer registers via Google OAuth or Email+Password.
2. Selects target project from dropdown.
3. The UI queries `/auth/project-info/{id}` and automatically displays the Project Manager's name.
4. An `AccessRequest` record is created in `pending` state. Developer is shown `auth/pending.html`.
5. The Project Manager sees the request in `/manager/requests` and chooses a technical role (`frontend`, `backend`, `database`, `devops`, `qa`).
6. Once approved, the developer can sign in and enter the Developer Workspace.

### B. Smart Ticket Assignment & Multi-Developer Team Queue
1. A developer (e.g., Frontend) experiences an issue (e.g., "Submit button fails on checkout form / API returns 500").
2. The developer clicks "+ Raise a Query", writes the description, and selects the target team (e.g., `backend`).
3. The ticket is created and automatically linked to **all** active project developers possessing the `backend` role via `ticket_assignments` records.
4. All backend team members see the new ticket in their Team Queue on `/developer/dashboard`.

### C. Single-Developer Atomic Claim Mechanism
1. Multiple backend developers can inspect the ticket and preview the issue.
2. The first developer to click **"Accept This Ticket"** claims ownership:
   - Sets `ticket_assignments.is_accepted = True`.
   - Sets `ticket_assignments.accepted_at = NOW()`.
   - Sets `tickets.status = 'in_progress'`.
3. Other backend developers viewing the ticket now see:
   > *"This ticket was accepted by [Developer Name] and is being handled."*
4. Only the accepting developer is granted permission to enter and submit the resolution remark.

### D. AI Self-RAG Solution Generation
1. Upon ticket submission, `src.rag.self_rag.solve_ticket` is triggered:
   - Formulates search query incorporating team role and problem text.
   - Searches Qdrant Vector DB using Google Gemini Embeddings (`gemini-embedding-001`, 768 dims).
   - Retrieves top matching document chunks from project runbooks.
   - Groq LLM (`openai/gpt-oss-120b`) evaluates chunk relevance.
   - Generates a grounded 3-part structured solution: `Problem Analysis`, `Suggested Solution`, and `Prevention Tips`.
   - Assesses faithfulness against the documentation and records citation sources.
2. The AI solution and sources are immediately attached to the ticket and displayed in an interactive card.

### E. Manager Resolution Review & Permanent Lock
1. Once the developer finishes the fix, they enter their resolution remark on the ticket page.
2. The ticket is flagged for manager review.
3. In `/manager/tickets`, the Project Manager reviews the issue, AI suggestions, and developer's remark.
4. The Manager clicks **"Approve"**:
   - Ticket status becomes `resolved`.
   - `ticket_assignments.remark_locked` is set to `True`.
   - Once locked, the remark cannot be edited or tampered with by any developer, preserving an immutable audit record.

---

## 6. How to Use & Update this Reference File

When working on any feature in DevResolve AI, follow these simple rules:
1. **Check this file first**: Verify the model name, table column, or route name here before modifying code.
2. **Do not perform redundant full-codebase scans**: All model names, enums, endpoints, and file locations are documented here.
3. **Update this file when modifying components**:
   - If you add a new model or column in `src/database.py`, update Section 3.
   - If you add or modify a route in `src/routers/`, update Section 4.
   - If you add a new template in `templates/`, update Section 2.
   - If you update configuration or LLM keys in `.env` / `src/config.py`, update Section 1.
