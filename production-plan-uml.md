# Production Plan (Aligned to UML Diagrams)

## Scope
Air-gapped vendor comparison platform with: ingestion, multi-agent evaluation, human review, and Excel output.

## Stage 1: Secure Ingestion and Decomposition
### Inputs
- Master specification checklist (Excel).
- 10 vendor submissions (PDF and Excel).

### Steps
- Accept files into a secure staging folder.
- Parse PDFs into layout-aware blocks.
- Extract and normalize tables into text matrices.
- Persist parsed blocks with coordinates in parsed_documents.

### Outputs
- Parsed cache with page and bounding-box references.

## Stage 2: Autonomous Multi-Agent Council Analysis
### Orchestration
- Slice context per spec parameter.
- Dispatch to three agents:
  - Technical Auditor (strict compliance, temp 0.0).
  - Risk Evaluator (legal, delivery, penalties, temp 0.0).
  - Fallback Specialist (nearly OK search, temp 0.1).
- Consensus Judge validates against citations.

### Outputs
- Structured JSON with: status, verbatim citation, reasoning, confidence.
- Persist to compliance_matrix.

## Stage 3: Human-in-the-Loop Verification
### Review
- Render color-coded grid with citations.
- Allow engineer overrides with justification.

### Persistence
- Update compliance_matrix.
- Insert override records into autonomous_feedback_loop.

## Stage 4: Matrix Consolidation and Output Generation
### Compilation
- Lock audited rows.
- Aggregate scores across vendors.
- Select best vendor per spec and overall.

### Export
- Excel matrix with citations and summary sheet.

## System Components
- Ingestor: PDF/Excel parsing, OCR if needed.
- Orchestrator: spec-by-vendor dispatch.
- Agents: technical, risk, fallback.
- Consensus judge: final decision and citation check.
- Review UI: overrides and audit trail.
- Report engine: Excel generation.

## Data Stores
- parsed_documents: raw blocks with coordinates.
- compliance_matrix: evaluations and citations.
- autonomous_feedback_loop: overrides for learning.

## Security Controls
- No network egress.
- Local-only file access.
- Audit log for overrides.
- Optional encryption at rest.

## Non-Functional Requirements
- Deterministic runs with temp 0.0 for final verdicts.
- Traceable citations to page and block.
- Recoverable state via transactional DB writes.

## Delivery Milestones
1) Ingestion + parsed cache.
2) Multi-agent evaluation + matrix.
3) Human review + overrides.
4) Excel reporting + best vendor ranking.

## Open Decisions
- Deployment target (workstation vs server).
- Model size and hardware.
- OCR accuracy thresholds.
