# Module 3 (Employee Documents): Decisions

Recorded 2026-11-03. These decisions follow the owner's Module 3 instructions:
- follow the frontend contract exactly;
- secure upload and download;
- check file content, MIME type, extension and size;
- keep documents in private storage, with no permanent public URLs;
- enforce role, employee and document access;
- audit every important action;
- metadata, verification, expiry and history only where the frontend contract asks for them;
- invent no HR document policies;
- keep no keys or secrets in source code or ZIPs.

## Security decisions (implemented)

| Topic | Decision |
|---|---|
| **Endpoints** | Exactly the 7 the frontend calls (B5): list, upload, download, checklist, compliance list, summary, attention. Plus `GET/PUT /hr/setup/document-settings` for the expiry window, which HR configures. There is **no delete** (the contract reserves it until the retention policy, R4, is decided) and **no verify/reject** endpoint (contract D24: not specified, and no permission exists for it). |
| **Permissions** | Read endpoints need `hr.documents:view`; upload needs `hr.documents:upload`. |
| **Employee-level access** | The employee must be inside the caller's organizational scope, using the role scopes from Module 2 (Q12). Otherwise the response is 404, as if the employee did not exist. |
| **Document-level access** | A document is reachable only through its own employee's URL; any other employee ID returns 404. The compliance views include only employees in the caller's scope. |
| **Content check** | The real format is detected from the bytes: the signature plus a structural end marker. PDF needs `%PDF-` and `%%EOF`; JPEG needs `FFD8FF` … `FFD9`; PNG needs its 8-byte signature and an `IEND` chunk. The detected format must match the file's extension. The stored `contentType` comes from detection, never from the browser. Renamed executables, HTML and truncated files are refused (422 on `file`). |
| **Extension** | The extension must be in the document type's allowed list **and** be a format the service can verify (`.pdf .jpg .jpeg .png`). Document-type setup now refuses other extensions, so HR cannot configure a type that can never be uploaded. |
| **Size** | The limit is the smaller of the document type's limit and `MAX_UPLOAD_BYTES`; over it returns **413**. Requests are refused from `Content-Length` before the body is read, and uploads with no declared length get 411. Empty files are refused. |
| **Malware scan** | ClamAV through `clamd` (INSTREAM). It **fails closed**: if the scanner is down, the upload is refused (503) and nothing is stored. An infected file gets 422 on `file`, an audit entry, and is never stored. `MALWARE_SCANNER=none` is refused in production. |
| **Private storage** | Files are stored under `STORAGE_DIR/documents`, which no web server serves. Folders are 0700 and files 0600. File names are random UUIDs that reveal nothing. |
| **Encryption at rest** | Each file is encrypted with Fernet using `DOCUMENT_ENCRYPTION_KEYS`, separate from the payroll keys. A SHA-256 of the original file is checked on every download; a tampered or missing file returns 503 and nothing is served. |
| **No URLs** | Clients never receive a storage path, key or URL. The only way to a file is `GET …/content`, which checks the permission, the scope and the document's owner on every request. |
| **Download headers** | The detected `Content-Type`; `Content-Disposition: attachment` with an ASCII `filename` plus a UTF-8 `filename*`; `X-Content-Type-Options: nosniff`; `Cache-Control: no-store, private`; `Content-Security-Policy: default-src 'none'; sandbox`. |
| **File names** | Only the base name is kept, without path or control characters, at most 200 characters. It is shown to users, but kept out of history: history says only "Document uploaded: <type>", because file names can themselves be sensitive. |
| **Audit** | Upload, download, list view, checklist view, compliance views, malware rejection, settings changes, and every refused request. |
| **Verification** | A new copy is always `pending` with a history event "Uploaded" (B5). It never becomes verified automatically. The history table is append-only (database trigger). |
| **Keys and secrets** | None in source code or ZIPs. Development keys live only in `.env`, which is excluded. The test suite generates fresh keys and secrets on every run and deletes its synthetic files afterwards. No real documents are used in development or tests. |

## Checklist and completion rules

The contract proposes these rules (D23, "the backend decides"); they are pending HR confirmation.

| Rule | Implemented as | Configurable |
|---|---|---|
| Which document types exist and which are required | HR configuration (Module 1 document types); the template is pending HR | Yes, `/hr/setup/document-types` |
| Who a required type applies to | All tracked employees (the configuration has no per-department or per-type rules) | Pending HR (D23) |
| Which copy decides a type's state | The latest copy | Contract proposal |
| States | missing / pending_verification / verified / rejected / expired. Expired means the expiry date is before today (company time zone). | Contract proposal |
| Completed | A required type whose latest copy is verified or awaiting verification | Contract proposal |
| Overall status | `documents_pending` → `awaiting_verification` → `complete`, as in the contract | Contract proposal |
| Expiring-soon window | **30 days**, the contract example's value, stored in `document_settings` | Yes, `/hr/setup/document-settings` (1–366) |
| Employees included in completion | Excludes statuses marked `employmentEnded` (the same HR setting as in Module 2) | Yes, per status |
| Order of types | Required first, then category, then name (the frontend's documented order) | — |

## Still requiring HR, management or IT confirmation

These are added to `HR_CONFIRMATION_PENDING.md` as items 32–39.

| # | Item | Who |
|---|---|---|
| 32 | Which document types are required, and for whom (all employees, or per employment type, department or designation) (D23) | HR |
| 33 | Expiring-soon window (30 days) | HR |
| 34 | Whether a copy awaiting verification counts as completed; whether exited employees are excluded (D23) | HR |
| 35 | The verification workflow: who verifies or rejects, under which permission, whether a comment is mandatory on rejection, and the endpoint (D24) | HR + management |
| 36 | The retention and deletion policy for documents (R4); there is no delete endpoint until it is decided | HR + Legal |
| 37 | File types and size limits per document type (template values) | HR + IT |
| 38 | The malware scanner: where `clamd` runs, its update policy, and the scan timeout | IT |
| 39 | Backup and key custody for `DOCUMENT_ENCRYPTION_KEYS`, which must be stored apart from the backups | IT + management |
