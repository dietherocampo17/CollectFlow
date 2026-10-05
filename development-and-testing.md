# CollectFlow Development and Testing Plan

## 1. Development Phase Overview

The Week 7–10 phase implements the collection workflow, MySQL-backed persistence, authentication, and server-enforced RBAC for the five proposal roles.

## 2. Core Features to Implement

### Collection Account Workflow
- add new collection accounts
- assign and reassign accounts to active collectors
- collector and supervisor account status updates
- record collection interactions in an account timeline
- view account age and risk score

### Promise-to-Pay Management
- create payment promise
- track promise date
- mark as kept or broken
- track payment method and received payment records
- trigger a follow-up task when a promise is broken

### Collector Queue Management
- sort accounts by priority and age
- calculate workload per collector
- display daily queue by status
- complete and monitor assigned follow-up tasks

### Reporting and Analytics
- compute portfolio recovery rate
- calculate overdue account counts
- show balance by risk group

## 3. Sprint Plan

### Sprint 1: Core data and account management
- define account model and MySQL persistence
- create add/edit account functionality
- build queue rendering

### Sprint 2: Promise and task workflow
- add promise form
- implement overdue detection
- create follow-up actions

### Sprint 3: Reporting and QA
- render summary metrics
- run logic tests
- verify business rules and UI flows
- verify authenticated routes and role-level API access
- validate user administration, session handling, and audit events
- validate role navigation, assignment scoping, and admin-only deletion

## 4. Testing Strategy

### Unit Testing
- verify account age calculations
- verify promise-to-pay status transitions
- verify recovery rate formula
- verify workload assignment rules

### Integration Testing
- ensure queue updates when account is re-assigned
- ensure dashboard stats refresh after new account entry

### UI/Behavior Testing
- check add-account interaction
- check promise form input validation
- confirm risk badges and statuses render correctly

## 5. QA Checklist

- accounts render in priority order
- all required fields are validated
- promise due dates are compared correctly
- overdue accounts are highlighted
- dashboard summary counts match table data

## 6. Risks and Mitigation

- inconsistent status naming across modules
  - solution: use centralized status constants
- broken promise logic being duplicated in multiple places
  - solution: central data update functions
- dashboard numbers drifting from underlying data
  - solution: derive stats from one shared data model
- unauthorized access to sensitive portfolio data
  - solution: enforce permissions and client/collector scoping in backend routes, not only in the UI

## 7. Expected Outcome

The prototype now demonstrates MySQL persistence, authenticated role-aware access, user management, auditing, and the core collection workflow. Payment processing, automated notifications, AI service integration, and background scheduling remain future modules.
