import json
import os
import secrets
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import jwt
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status, Request
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from src.app.run_pipeline import main as run_pipeline_main
from src.storage.db import get_connection, init_db
from src.utils.paths import PROJECT_ROOT

app = FastAPI(title="Vendor Comparison Platform")
LOCAL_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8501",
    "http://127.0.0.1:8501",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".xlsx"}

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    username: str
    full_name: str = ""
    disabled: bool = False


class HealthResponse(BaseModel):
    status: str


class UploadResponse(BaseModel):
    saved: list[str]


class PipelineRunResponse(BaseModel):
    run_id: str
    status: str


class PipelineStatusResponse(BaseModel):
    run_id: str
    status: str
    progress: float
    message: str
    error: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FileInfo(BaseModel):
    file_name: str
    extension: str
    size_bytes: int
    modified_at: str
    role: str


class FilesResponse(BaseModel):
    incoming: list[FileInfo]


class ResultsResponse(BaseModel):
    results: list[dict[str, Any]]
    count: int
    limit: int
    offset: int


class SummaryResponse(BaseModel):
    total_results: int
    status_counts: dict[str, int]
    vendor_counts: dict[str, int]
    spec_counts: dict[str, int]


class ParsedDocumentResponse(BaseModel):
    doc_id: str
    file_name: str
    page: int
    bbox: str
    text: str


class OverrideRequest(BaseModel):
    spec_id: str = Field(..., min_length=1)
    vendor_id: str = Field(..., min_length=1)
    new_status: str = Field(..., min_length=1)
    justification: str = Field(..., min_length=1)


class OverrideResponse(BaseModel):
    status: str
    spec_id: str
    vendor_id: str
    new_status: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


fake_users_db = {}


def _seed_default_user(conn) -> None:
    username = os.environ.get("API_ADMIN_USERNAME", "admin")
    password = os.environ.get("API_ADMIN_PASSWORD", "changeme")
    full_name = os.environ.get("API_ADMIN_FULL_NAME", "Administrator")
    row = conn.execute("SELECT username FROM application_users WHERE username=?", (username,)).fetchone()
    if row:
        return
    conn.execute(
        "INSERT INTO application_users (username, full_name, hashed_password, disabled) VALUES (?, ?, ?, ?)",
        (username, full_name, get_password_hash(password), 0),
    )


def _get_user_from_db(username: str) -> Optional[dict]:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        _seed_default_user(conn)
        conn.commit()
        row = conn.execute(
            "SELECT username, full_name, hashed_password, disabled FROM application_users WHERE username=?",
            (username,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return fake_users_db.get(username)
    return {
        "username": row[0],
        "full_name": row[1],
        "hashed_password": row[2],
        "disabled": bool(row[3]),
    }


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = _get_user_from_db(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub") or payload.get("username")
        if username is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception
    user = _get_user_from_db(username)
    if user is None:
        raise credentials_exception
    return user


def require_localhost(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Localhost access only")


def _db_path() -> Path:
    return PROJECT_ROOT / "data" / "parsed" / "app.db"


def _report_path() -> Path:
    return PROJECT_ROOT / "data" / "output" / "vendor_comparison_matrix.xlsx"


def _incoming_dir() -> Path:
    return PROJECT_ROOT / "data" / "incoming"


def _ensure_app_db() -> None:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(str(db_path))


def _dict_rows(conn, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn.row_factory = lambda cursor, row: {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
    return conn.execute(query, params).fetchall()


def _pipeline_run_from_row(row) -> dict[str, Any]:
    return {
        "run_id": row[0],
        "status": row[1],
        "progress": row[2],
        "message": row[3],
        "error": row[4],
        "created_at": row[5],
        "updated_at": row[6],
    }


def _file_role(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "vendor_pdf"
    if suffix in {".xlsx", ".xlsm"}:
        return "master_workbook"
    return "unsupported"


def _file_info(path: Path) -> FileInfo:
    stat = path.stat()
    return FileInfo(
        file_name=path.name,
        extension=path.suffix.lower(),
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        role=_file_role(path),
    )


def _set_run_state(run_id: str, status_value: str, message: str = "", progress: float = 0.0, error: str = "") -> None:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        conn.execute(
            "UPDATE pipeline_runs SET status=?, message=?, progress=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            (status_value, message, progress, error, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _run_pipeline_job(run_id: str) -> None:
    try:
        _set_run_state(run_id, "running", "Pipeline started", 0.0)
        run_pipeline_main(run_id=run_id)
        _set_run_state(run_id, "completed", "Pipeline completed", 100.0)
    except Exception as exc:
        _set_run_state(run_id, "failed", "Pipeline failed", 0.0, str(exc))


@app.post("/token", response_model=TokenResponse)
def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), _: None = Depends(require_localhost)):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": user["username"]})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/health", response_model=HealthResponse)
def health(_: None = Depends(require_localhost)) -> dict:
    return {"status": "ok"}


@app.get("/me", response_model=UserResponse)
def me_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    return {
        "username": current_user["username"],
        "full_name": current_user.get("full_name", ""),
        "disabled": bool(current_user.get("disabled", False)),
    }


@app.get("/files", response_model=FilesResponse)
def files_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    incoming = _incoming_dir()
    incoming.mkdir(parents=True, exist_ok=True)
    files = [
        _file_info(path)
        for path in sorted(incoming.iterdir(), key=lambda item: item.name.lower())
        if path.is_file()
    ]
    return {"incoming": files}


@app.post("/upload", response_model=UploadResponse)
def upload_files(current_user: dict = Depends(get_current_user), files: list[UploadFile] = File(...), _: None = Depends(require_localhost)) -> dict:
    incoming = PROJECT_ROOT / "data" / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    names = [Path(upload.filename).name for upload in files]
    workbook_count = sum(1 for name in names if Path(name).suffix.lower() == ".xlsx")
    pdf_count = sum(1 for name in names if Path(name).suffix.lower() == ".pdf")
    if workbook_count != 1 or pdf_count < 1:
        raise HTTPException(status_code=400, detail="Upload exactly one .xlsx workbook and at least one .pdf vendor file")
    saved = []
    for upload in files:
        dest_name = Path(upload.filename).name
        if Path(dest_name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {dest_name}")
        destination = incoming / dest_name
        size = 0
        with destination.open("wb") as target:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_MB} MB)")
                target.write(chunk)
        saved.append(destination.name)
    return {"saved": saved}


@app.post("/run-pipeline", response_model=PipelineRunResponse)
def run_pipeline_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    run_id = str(uuid.uuid4())
    conn = get_connection(str(_db_path()))
    try:
        active = conn.execute(
            "SELECT run_id FROM pipeline_runs WHERE status IN ('queued', 'running') ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail=f"Pipeline already active: {active[0]}")
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs (run_id, status, progress, message, error, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (run_id, "queued", 0.0, "Queued", ""),
        )
        conn.commit()
    finally:
        conn.close()

    thread = threading.Thread(target=_run_pipeline_job, args=(run_id,), daemon=True)
    thread.start()
    return {"run_id": run_id, "status": "queued"}


@app.get("/runs", response_model=list[PipelineStatusResponse])
def runs_endpoint(
    limit: int = 25,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_localhost),
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        rows = conn.execute(
            """
            SELECT run_id, status, progress, message, error, created_at, updated_at
            FROM pipeline_runs
            ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    finally:
        conn.close()
    return [_pipeline_run_from_row(row) for row in rows]


@app.get("/runs/{run_id}", response_model=PipelineStatusResponse)
def run_detail_endpoint(run_id: str, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    return status_endpoint(run_id, current_user, _)


@app.get("/status/{run_id}", response_model=PipelineStatusResponse)
def status_endpoint(run_id: str, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        row = conn.execute(
            "SELECT run_id, status, progress, message, error, created_at, updated_at FROM pipeline_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return _pipeline_run_from_row(row)


@app.get("/results", response_model=ResultsResponse)
def results_endpoint(
    vendor_id: Optional[str] = None,
    spec_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_localhost),
) -> dict:
    limit = max(1, min(limit, 5000))
    offset = max(0, offset)
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        clauses = []
        params: list[Any] = []
        if vendor_id:
            clauses.append("vendor_id=?")
            params.append(vendor_id)
        if spec_id:
            clauses.append("spec_id=?")
            params.append(spec_id)
        if status_filter:
            clauses.append("status=?")
            params.append(status_filter)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        count = conn.execute(f"SELECT COUNT(*) FROM compliance_matrix {where_sql}", tuple(params)).fetchone()[0]
        rows = _dict_rows(
            conn,
            f"SELECT * FROM compliance_matrix {where_sql} ORDER BY spec_id, vendor_id LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        )
    finally:
        conn.close()
    return {"results": rows, "count": count, "limit": limit, "offset": offset}


@app.get("/summary", response_model=SummaryResponse)
def summary_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        total_results = conn.execute("SELECT COUNT(*) FROM compliance_matrix").fetchone()[0]
        status_counts = dict(conn.execute("SELECT status, COUNT(*) FROM compliance_matrix GROUP BY status").fetchall())
        vendor_counts = dict(conn.execute("SELECT vendor_id, COUNT(*) FROM compliance_matrix GROUP BY vendor_id").fetchall())
        spec_counts = dict(conn.execute("SELECT spec_id, COUNT(*) FROM compliance_matrix GROUP BY spec_id").fetchall())
    finally:
        conn.close()
    return {
        "total_results": total_results,
        "status_counts": status_counts,
        "vendor_counts": vendor_counts,
        "spec_counts": spec_counts,
    }


@app.get("/parsed-document/{doc_id}", response_model=ParsedDocumentResponse)
def parsed_document_endpoint(doc_id: str, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        row = conn.execute(
            "SELECT doc_id, file_name, page, bbox, text FROM parsed_documents WHERE doc_id=?",
            (doc_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Parsed document not found")
    return {
        "doc_id": row[0],
        "file_name": row[1],
        "page": row[2],
        "bbox": row[3],
        "text": row[4],
    }


@app.get("/pdf/{file_name}")
def pdf_endpoint(file_name: str, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)):
    pdf_path = _incoming_dir() / Path(file_name).name
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=pdf_path.name)


@app.get("/audit-log")
def audit_log_endpoint(
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_localhost),
) -> dict:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        rows = _dict_rows(
            conn,
            """
            SELECT id, action, entity_type, entity_id, details, created_at
            FROM audit_log
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
    finally:
        conn.close()
    return {"events": rows, "count": count, "limit": limit, "offset": offset}


@app.get("/training-queue")
def training_queue_endpoint(
    processed: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_localhost),
) -> dict:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        clauses = []
        params: list[Any] = []
        if processed is not None:
            clauses.append("processed=?")
            params.append(1 if processed else 0)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        count = conn.execute(f"SELECT COUNT(*) FROM training_queue {where_sql}", tuple(params)).fetchone()[0]
        rows = _dict_rows(
            conn,
            f"""
            SELECT id, spec_id, vendor_id, doc_id, page, bbox, excerpt, label, processed, created_at
            FROM training_queue
            {where_sql}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
    finally:
        conn.close()
    return {"items": rows, "count": count, "limit": limit, "offset": offset}


@app.post("/override", response_model=OverrideResponse)
def override_endpoint(payload: OverrideRequest, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    spec_id = payload.spec_id.strip()
    vendor_id = payload.vendor_id.strip()
    new_status = payload.new_status.strip()
    justification = payload.justification.strip()
    if not spec_id or not vendor_id or not new_status or not justification:
        raise HTTPException(status_code=400, detail="spec_id, vendor_id, new_status, and justification are required")

    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        row = conn.execute(
            "SELECT status, citation_doc_id, citation_excerpt FROM compliance_matrix WHERE spec_id=? AND vendor_id=?",
            (spec_id, vendor_id),
        ).fetchone()
        original = row[0] if row else "UNKNOWN"
        citation_doc_id = row[1] if row and len(row) > 1 else None
        citation_excerpt = row[2] if row and len(row) > 2 and row[2] else ""
        conn.execute(
            "UPDATE compliance_matrix SET status=?, reasoning=? WHERE spec_id=? AND vendor_id=?",
            (new_status, f"[OVERRIDE] {justification}", spec_id, vendor_id),
        )
        conn.execute(
            "INSERT INTO autonomous_feedback_loop (spec_id, vendor_id, original_status, corrected_status, justification, context) VALUES (?, ?, ?, ?, ?, ?)",
            (spec_id, vendor_id, original, new_status, justification, citation_excerpt),
        )
        if citation_doc_id:
            pdrow = conn.execute(
                "SELECT page, bbox, text FROM parsed_documents WHERE doc_id=?",
                (citation_doc_id,),
            ).fetchone()
            page = pdrow[0] if pdrow else None
            bbox = pdrow[1] if pdrow else None
            excerpt = pdrow[2] if pdrow else citation_excerpt
            conn.execute(
                "INSERT INTO training_queue (spec_id, vendor_id, doc_id, page, bbox, excerpt, label) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (spec_id, vendor_id, citation_doc_id, page, bbox, excerpt, new_status),
            )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "spec_id": spec_id, "vendor_id": vendor_id, "new_status": new_status}


@app.get("/report")
def report_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)):
    report_path = _report_path()
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(report_path), filename=report_path.name)


@app.get("/secure")
def secure_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    return {"status": "ok", "user": current_user["username"]}
