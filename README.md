<div align="center">

# 🎣 AI Phishing Simulation Platform

**An enterprise-style AI platform for phishing simulation, employee risk scoring, and security-awareness training.**

Next.js · FastAPI · PostgreSQL · LangGraph · ChromaDB

![Status](https://img.shields.io/badge/status-planning-lightgrey)
![Track](https://img.shields.io/badge/track-Generative%20AI-blue)
![Domain](https://img.shields.io/badge/domain-Cybersecurity-red)
![License](https://img.shields.io/badge/license-Educational-green)

</div>

---

## 📌 Overview

Security teams often run phishing-awareness campaigns manually — writing emails by hand, distributing them ad hoc, and compiling results in spreadsheets. This is slow, inconsistent, and hard to scale across departments.

This platform automates that workflow with AI: it generates realistic, policy-grounded phishing simulations, tracks how employees respond, and turns the results into explainable risk scores and personalized coaching — all with a human reviewer in the loop at every step.



---

## ✨ Key Features

| | |
|---|---|
| 🎯 | Campaign & target-group management |
| 🤖 | AI-generated phishing templates, grounded via Retrieval-Augmented Generation (RAG) |
| ✅ | Human approval gate before any content is delivered |
| 📡 | Real-time interaction tracking (open / click / submit / report) |
| 🧮 | Explainable risk scoring engine |
| 💬 | LLM-generated campaign summaries and personalized employee coaching |
| 🕵️ | Full audit trail for compliance and traceability |
| 📊 | Analytics dashboard for org-wide awareness trends |

---

## 🛠️ Tech Stack

<div align="center">

| Layer | Technology |
|:---|:---|
| **Frontend** | React · Next.js · Tailwind CSS · React Query |
| **Backend / API** | FastAPI (Python) |
| **Database** | PostgreSQL |
| **AI Orchestration** | LangGraph (multi-agent state machine) |
| **Vector Store / RAG** | ChromaDB |
| **Deployment** | Docker · CI/CD |

</div>

---

## 🏗️ Architecture

```
Next.js (UI) → FastAPI (API + Orchestration) → LangGraph Multi-Agent Workflow
                                                      ├── Template Generation Agent
                                                      ├── Compliance Guard Agent
                                                      ├── Scoring Agent
                                                      ├── Explanation Agent
                                                      └── Coaching Agent
                                                      ↕
                                          ChromaDB (RAG retrieval) + LLM API
                                                      ↕
                                                PostgreSQL
```

The AI workflow is grounded in the retrieval-augmented generation approach from Lewis et al. (2020), *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, retrieving from an enterprise knowledge base of security policies and phishing patterns (plus a WikiQA-style grounding set) before any content is generated.

📂 Full architecture, data model, API spec, and design rationale live in [`docs/`](./docs).

---

## 🚦 Project Status

**Planning complete → Build not yet started.**

- [x] Business Requirements Document (BRD)
- [x] Product Requirements Document (PRD)
- [x] UX Requirements
- [x] Technical Requirements Document (TRD)
- [x] High-Level & Low-Level Design (HLD / LLD)
- [ ] Backend scaffolding
- [ ] Frontend scaffolding
- [ ] AI/RAG pipeline
- [ ] Deployment

📅 See the [12-week roadmap](./docs/17-roadmap.md) for the full build plan.

---

## 📚 Documentation

Complete project documentation — BRD, PRD, UX requirements, TRD, HLD, database design, API spec, LLD, GenAI architecture, security design, testing strategy, CI/CD, and deployment — lives in [`docs/`](./docs).

---

## 🚀 Getting Started

Setup instructions will be added once the backend and frontend scaffolding are in place.

---

<div align="center">



</div>
