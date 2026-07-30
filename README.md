# GitGuardian AI — Agentic Security on Every Push

> An open-source AI agent that detects, classifies, and **fixes** security issues on every push — then opens a PR and waits for human approval.

## Problem

Developers push secrets, vulnerabilities, and misconfigurations to GitHub daily. Current tools detect issues but don't fix them. Code review bottlenecks mean vulnerabilities sit in repos for days.

GitGuardian AI closes the loop: **detect → classify → generate fix → test fix → open PR → wait for human approval.**

## Why It Matters

- One leaked API key can kill a company. Every startup has this problem.
- GitHub Advanced Security is $21/dev/month — startups can't afford it.
- Snyk requires complex setup. This agent is install-and-forget.

## How It Works

```
GitHub Push ──► Webhook Receiver (FastAPI)
                     │
                     ▼
            ┌─────────────────┐
            │ Security Scanner │
            │ (Semgrep+Gitleaks)│
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │ Classification  │
            │ Agent (severity) │
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │ Fix Generation  │
            │ Agent (Claude)   │
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │ Test Generation │
            │ Agent (pytest)   │
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │ PR Creation     │
            │ (GitHub API)     │
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │ HITL Approval   │
            │ Queue (Dashboard)│
            └─────────────────┘
```

## Agent Architecture

| Agent | Responsibility |
|---|---|
| **Router Agent** | Classifies push event → routes to scanner |
| **Scanner Agent** | Runs Semgrep/Gitleaks, parses SARIF |
| **Classifier Agent** | Scores severity (Critical/High/Medium/Low) |
| **Fix Agent** | Generates patched code with context awareness |
| **Test Agent** | Generates pytest tests for the fix |
| **PR Agent** | Creates branch, commits fix, opens PR with description |

All agents traced in LangSmith with cost tracking.

## Tech Stack

- **Backend:** FastAPI, LangGraph, LangChain
- **AI:** Claude (fix generation), GPT-4o-mini (classification)
- **Security:** Semgrep, Gitleaks, Bandit
- **Testing:** Pytest, Docker-in-Docker for isolation
- **Database:** PostgreSQL (scan history), Redis (queue)
- **Observability:** LangSmith
- **Auth:** GitHub App JWT
- **Deployment:** Docker, GitHub Actions, Azure

## Feature Roadmap

| Week | Feature | Deliverable |
|---|---|---|
| 1 | GitHub App + Webhooks | Push events captured, signatures verified |
| 2 | Security Scanning | Semgrep + Gitleaks integration, SARIF parsing |
| 3 | AI Fix Generation | Claude generates patched code with diffs |
| 4 | Test Generation | Pytest tests auto-generated, run in Docker isolation |
| 5 | PR Creation + HITL | Auto-branch, apply fix, push, open PR, human approval gate |
| 6 | Dashboard + Evals | Cost tracking, accuracy metrics, 50 test cases |
| 7 | Deployment + Docs | Docker, CI/CD, demo video, architecture docs |

## Folder Structure

```
gitguardian-ai/
├── apps/
│   ├── api/                    # FastAPI webhook receiver
│   └── dashboard/              # Next.js approval dashboard
├── agents/
│   ├── router/                 # Push event routing
│   ├── scanner/                # Security scanning logic
│   ├── classifier/             # Severity classification
│   ├── fix_generator/          # Code fix generation
│   ├── test_generator/         # Test generation
│   └── pr_creator/             # GitHub PR creation
├── security/
│   ├── rules/                  # Custom Semgrep rules
│   └── parsers/                # SARIF output parsers
├── evals/
│   ├── datasets/               # Vulnerable code samples
│   ├── metrics/                # Fix accuracy, test pass rate
│   └── benchmarks/             # Performance tests
├── infrastructure/
│   ├── docker/                 # Dockerfiles, compose
│   └── github-actions/         # CI/CD workflows
├── docs/
│   ├── architecture/           # Diagrams, ADRs
│   └── api/                    # OpenAPI specs
└── README.md
```

## Deployment

- Docker Compose for local/dev
- Azure Container Apps for production
- GitHub Actions: lint → test → security scan → build → deploy
- Health checks for each agent service
- Circuit breakers for GitHub API

## Future Improvements

- MCP server for IDE integration (VS Code extension)
- Fine-tuned classification model
- Support for more languages (currently Python/JS)
- Auto-merge for low-severity fixes (configurable)

## License

MIT — open source, contributions welcome.
