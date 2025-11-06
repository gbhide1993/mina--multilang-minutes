# 💬 MinA — Your AI Meeting Assistant Inside WhatsApp  
**Built in Bharat. For Bharat. 🇮🇳**

---

## 🧠 Overview

**MinA** (short for *Meeting Intelligence Assistant*) is an **AI-powered WhatsApp agent** that listens to your meeting recordings, transcribes conversations, and summarizes them into clear, actionable notes — all *inside WhatsApp*.

No new app. No new login.  
Just the power of **AI + WhatsApp**, designed for professionals, freelancers, and SMBs across India.

---

## 🚀 Key Features

1. **WhatsApp-Native Assistant**  
   Works directly within WhatsApp — no installations or logins required.

2. **End-to-End Encrypted Transcription**  
   Every voice note or meeting recording is securely transcribed and summarized.

3. **Audio Upload Support**  
   Upload from your local device — supports MP3, M4A, OGG, WAV, and WhatsApp OPUS.

4. **On-the-Fly Recording**  
   Record live conversations directly from WhatsApp and get instant summaries.

5. **Understands 9 Indian Languages**  
   English, Hindi, Marathi, Tamil, Telugu, Gujarati, Kannada, Bengali, and Malayalam.

6. **Cross-Language Summarization**  
   Handles mixed-language (e.g., English + Hindi) audio and delivers unified summaries.

7. **Enterprise-Grade Security**  
   Data encrypted with **AES-256**, processed *statelessly*, and auto-purged after summary generation.

8. **Transparent Pricing**  
   First 30 minutes free, then **₹299/month** for unlimited usage.

---

## ⚙️ Architecture Overview

MinA’s backend is designed for scalability, privacy, and speed.

### 🧩 Core Tech Stack
- **Python (Flask)** — Backend framework  
- **Twilio WhatsApp API** — Communication layer  
- **OpenAI Whisper** — Speech-to-text transcription  
- **GPT-4o-mini / GPT-3.5** — Summarization engine  
- **Redis Queue** — Asynchronous task handling  
- **Docker Containers** — Modular deployment  
- **Razorpay API** — Subscription & payments  

### 🔒 Data Flow
1. User sends voice note / recording via WhatsApp.  
2. Twilio webhook forwards it to MinA backend.  
3. Audio is transcribed using **Whisper**.  
4. Text is summarized via **GPT-based model**.  
5. Output is formatted into:
   - 📝 Summary  
   - ✅ Action Items  
   - 📋 Key Decisions  
   - 📊 Context (if relevant)  
6. Summary is sent back on WhatsApp.  
7. Audio and text are deleted instantly from server memory.

---

## 🔐 Security Model

| Layer | Technology | Purpose |
|-------|-------------|----------|
| **Encryption** | AES-256 | Protects user data during transit and processing |
| **Stateless Processing** | Ephemeral containers | No session data retained |
| **Auto-Purge** | Background tasks | Deletes files post-processing |
| **WhatsApp E2E Encryption** | Meta platform | Secures message layer |

MinA never stores your meeting content, summaries, or metadata — ensuring **complete data privacy**.

---

## 🌍 Why MinA?

- 🇮🇳 Built for Indian professionals — multilingual, mobile-first, and affordable.  
- 💬 Works in WhatsApp — no onboarding or friction.  
- 🔒 Data never leaves encrypted environment.  
- 🧠 Built using cutting-edge AI tech (Whisper + GPT).  
- ☕ Priced at less than a chai per day — ₹299/month.  

---

## 💰 Pricing

| Tier | Description | Price |
|------|--------------|-------|
| **Free** | 30 minutes transcription/summarization | ₹0 |
| **Pro** | Unlimited usage | ₹299/month |
| **Team (Coming Soon)** | Shared workspace & exports | ₹699/month |

---

## 📈 Roadmap

- [ ] Integration with Google Drive & Docs  
- [ ] Custom AI tone & summary length settings  
- [ ] Support for 12+ Indian languages  
- [ ] Export summaries as PDFs  
- [ ] Multi-user “Team Mode”  

---

## 🤝 Collaborations

MinA integrates with:
- **Meta (WhatsApp Cloud API)**  
- **OpenAI (Whisper + GPT APIs)**  
- **Twilio (Communication Layer)**  
- **Razorpay (Payments Gateway)**  

Looking ahead, MinA aims to collaborate with:
- **Zoho, Freshworks, Haptik, and Yellow.ai** for AI automation and enterprise solutions.

---

## 🧩 Getting Started (For Developers)

> This repo documents MinA’s architecture and workflow for community contributors and AI developers.

### Prerequisites
- Python 3.10+  
- Twilio account with WhatsApp Sandbox  
- OpenAI API key  
- Redis & Docker installed locally  

### Setup
```bash
git clone https://github.com/yourusername/mina-ai.git
cd mina-ai
docker-compose up --build
