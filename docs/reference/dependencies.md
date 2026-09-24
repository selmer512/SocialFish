---
type: reference
title: Dependency Reference
created: 2026-09-24
tags:
  - dependencies
  - operations
related:
  - '[[Simulation-Campaigns]]'
  - '[[AI-Scenario-Generation]]'
  - '[[Simulation-Delivery-Tracking]]'
  - '[[Simulation-Metrics]]'
  - '[[Entra-Directory-Integration]]'
  - '[[Simulation-Safety-Audit]]'
---

# Dependency Reference

This reference maps SocialFish runtime dependencies to the features that need them. Install from `requirements.txt` for local development, or build the Docker image for a containerized Python 3.12 runtime. Python 3.11 or newer is required because the simulation modernization uses `datetime.UTC` in database migration and shared timestamp helpers.

## Runtime Baseline

| Dependency | Constraint | Used by | Feature links |
| --- | --- | --- | --- |
| Python | 3.11+ | Core application runtime, SQLite migrations, UTC timestamp helpers | [[Simulation-Campaigns]], [[Simulation-Metrics]], [[Simulation-Safety-Audit]] |
| Flask | `==3.1.3` | Main web application, route handlers, templates, JSON APIs | [[Simulation-Campaigns]], [[AI-Scenario-Generation]], [[Simulation-Delivery-Tracking]], [[Simulation-Metrics]], [[Entra-Directory-Integration]], [[Simulation-Safety-Audit]] |
| Werkzeug | `>=2.3.0` | Flask request/response stack and local serving support | [[Simulation-Campaigns]] |
| Flask-Login | unpinned legacy dependency | Authenticated admin, simulation, provider, directory, audit, and export routes | [[Simulation-Campaigns]], [[Simulation-Safety-Audit]], [[Entra-Directory-Integration]] |
| requests | unpinned legacy dependency | Cloning, geolocation lookup, webhook posting, and tunnel helper HTTP calls | [[Simulation-Delivery-Tracking]], [[Simulation-Safety-Audit]] |
| colorama | unpinned legacy dependency | Console banner and terminal output formatting | [[Simulation-Safety-Audit]] |

## Real-Time And Browser Automation

| Dependency | Constraint | Used by | Feature links |
| --- | --- | --- | --- |
| flask-socketio | `>=5.3.0` | Live operator panel and Socket.IO event emission from `SocialFish.py` | [[Simulation-Delivery-Tracking]] |
| python-socketio | `>=5.9.0` | Socket.IO protocol dependency for Flask-SocketIO | [[Simulation-Delivery-Tracking]] |
| python-engineio | `>=4.7.0` | Engine.IO transport dependency for Flask-SocketIO | [[Simulation-Delivery-Tracking]] |
| eventlet | `>=0.33.3` | Optional async worker dependency documented with Socket.IO support | [[Simulation-Delivery-Tracking]] |
| playwright | `>=1.40.0` | Dynamic login-page recorder in `core/recorder_playwright.py`; browser binaries still require `playwright install chromium` | [[Simulation-Campaigns]] |
| selenium | `>=4.13.0` | Selenium recorder in `core/recorder_selenium.py` | [[Simulation-Campaigns]] |
| webdriver-manager | `>=4.0.0` | Chrome/Firefox driver discovery for Selenium recorder | [[Simulation-Campaigns]] |

## Legacy Reporting, Network, And Tunnel Support

| Dependency | Constraint | Used by | Feature links |
| --- | --- | --- | --- |
| pylatex | unpinned legacy dependency | Legacy PDF report generation in `core/report.py` | [[Simulation-Metrics]] |
| qrcode | unpinned legacy dependency | Token QR code generation in `core/genToken.py` | [[Simulation-Campaigns]] |
| python-nmap | unpinned legacy dependency | `nmap` module used by `core/scansf.py` | [[Simulation-Safety-Audit]] |
| python3-nmap | unpinned legacy dependency | Retained for compatibility with older setup paths and scanner environments | [[Simulation-Safety-Audit]] |
| pyngrok | `>=7.0.0` | Optional ngrok tunnel setup in `core/tunnel_manager.py` | [[Simulation-Delivery-Tracking]] |

## Configuration Notes

- `requirements.txt`, `setup.py`, and the Docker build now use the same dependency set. When adding a new import, update all three surfaces together.
- Keep exact pins only where the project already relies on a known version, such as Flask. Use lower-bound constraints for browser, Socket.IO, and tunnel packages where the existing project already tracks minimum compatible versions.
- Do not add provider SDKs for future AI, delivery, or Microsoft Graph integrations until the code imports and uses them. Current mock, dry-run, and configuration-shell workflows rely on the standard library plus the dependencies above.
- Docker uses Python 3.12 so simulation migrations and timestamp helpers work with `datetime.UTC`.
