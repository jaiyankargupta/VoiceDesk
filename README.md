# VoiceDesk — Conversational Voice Agent

[![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/jaiyankargupta/VoiceDesk)
[![LiveKit](https://img.shields.io/badge/Powered%20by-LiveKit-red)](https://livekit.io)
[![OpenAI](https://img.shields.io/badge/AI-OpenAI-green)](https://openai.com)
[![Twilio](https://img.shields.io/badge/Telephony-Twilio-blue)](https://twilio.com)

A production-ready voice agent application built with LiveKit, OpenAI, and Twilio. Features real-time appointment booking, live monitoring with take-over capability, and warm transfer to human agents.

## 📹 Demo Video

Watch the full demonstration of VoiceDesk in action, including booking, monitoring, and live takeover:

[![VoiceDesk Demo](https://img.shields.io/badge/Watch%20Demo-Loom-552586?style=for-the-badge&logo=loom)](https://www.loom.com/share/a5a7a6d2522345c29fb4af13fe7c5307)

[https://www.loom.com/share/a5a7a6d2522345c29fb4af13fe7c5307](https://www.loom.com/share/a5a7a6d2522345c29fb4af13fe7c5307)

---

## ⚙️ System Architecture

VoiceDesk uses a decoupled architecture with WebRTC for ultra-low latency voice and WebSockets for real-time monitoring and control.

```text
┌──────────────┐     WebRTC (Voice)  ┌──────────────┐
│  Next.js UI  │ ◄─────────────────► │  LiveKit Room│
│  (Caller)    │                     │              │
└──────────────┘                     │   Agent AI   │
                                     │  (Python)    │
┌──────────────┐   WebSocket         │              │
│  Monitor UI  │ ◄─────────────────► │  FastAPI     │
│  (Watcher)   │                     └──────┬───────┘
└──────────────┘                            │
                               ┌────────────┴───────────┐
                               │                        │
                          ┌────▼────┐              ┌────▼──────┐
                          │ SQLite  │              │  Cal.com  │
                          │ (local) │              │(Scheduling│
                          └─────────┘              └───────────┘
                               │
                          ┌────▼────┐
                          │ Twilio  │
                          │ (Warm   │
                          │ Transfer│
                          └─────────┘
```

### Core Components
1. **LiveKit Agent (Python)**: Handles speech-to-text (Deepgram), reasoning (OpenAI GPT-4o), and text-to-speech (ElevenLabs), alongside executing tools.
2. **FastAPI Backend**: Provides REST API, WebSocket event streaming for the monitor UI, and SQLite database connections.
3. **Next.js Frontend**: Contains the caller interface (WebRTC) and the watcher/monitor dashboard (WebSockets + REST).
4. **Cal.com**: External scheduling integration for real-time calendar syncing.
5. **Twilio**: Executes SIP/PSTN warm transfers to human agents.

---

## ✨ Features

- **🗣️ Voice Conversation** — Natural speech via Deepgram STT, GPT-4o reasoning, ElevenLabs TTS
- **📅 Appointment Booking** — Check availability, book, reschedule, or cancel via voice
- **🧠 Intent Detection** — Automatically detects booking, complaint, billing, and transfer intents
- **📞 Warm Transfer** — Dials a human agent via Twilio, speaks a summary, handles accept/decline
- **📡 Live Monitoring** — Real-time transcript, agent state, intent, and action tracking
- **⏸️ Take-Over** — Watcher can pause the AI and speak directly to the caller
- **⚡ Barge-in Support** — Caller can interrupt the agent mid-sentence
- **📝 Post-Call Summary** — GPT-4o generates a summary when the call ends
- **🔗 Cal.com Integration** — Optional real calendar scheduling (falls back to local DB)

---

## 🔑 Getting API Keys

### LiveKit
1. Sign up at [livekit.io](https://livekit.io)
2. Create a project in the dashboard
3. Copy your `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`

### OpenAI
1. Go to [platform.openai.com](https://platform.openai.com)
2. Create an API key under Settings → API Keys
3. Copy your `OPENAI_API_KEY`

### Deepgram
1. Sign up at [deepgram.com](https://deepgram.com)
2. Create an API key in the dashboard
3. Copy your `DEEPGRAM_API_KEY`

### ElevenLabs
1. Sign up at [elevenlabs.io](https://elevenlabs.io)
2. Go to Profile → API Keys
3. Copy your `ELEVENLABS_API_KEY`

### Twilio
1. Sign up at [twilio.com](https://www.twilio.com) (free trial includes credits)
2. Get your `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` from the console
3. Get a phone number — this is your `TWILIO_FROM_NUMBER`
4. Set `HUMAN_AGENT_PHONE` to the number you want transfers routed to

### Cal.com (Optional)
1. Sign up at [cal.com](https://cal.com)
2. Go to Settings → Developer → API Keys
3. Create a key and copy it as `CAL_API_KEY`
4. Create an Event Type and note its ID as `CAL_EVENT_TYPE_ID`

---

## 🛠️ Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- npm

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Copy and fill in your API keys
cp .env.example .env
```

### Frontend

```bash
cd frontend
npm install
```

### Environment Variables

Create `backend/.env` with:

```env
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_key
LIVEKIT_API_SECRET=your_secret

OPENAI_API_KEY=sk-...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...

# Optional: Cal.com scheduling
CAL_API_KEY=cal_live_...
CAL_EVENT_TYPE_ID=123456

# Twilio warm transfer
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1...
HUMAN_AGENT_PHONE=+1...
```

---

## 🚀 Running Locally

### Start the backend (two processes)

```bash
# Terminal 1: FastAPI server
cd backend
source venv/bin/activate
python main.py

# Terminal 2: LiveKit agent worker
cd backend
source venv/bin/activate
python agent.py dev
```

### Start the frontend

```bash
# Terminal 3
cd frontend
npm run dev
```

### Access the application

- **Caller UI**: http://localhost:3000
- **Monitor Dashboard**: http://localhost:3000/monitor
- **API**: http://localhost:8080

---

## 📖 Workflows

### Appointment Booking
1. Caller connects and is greeted by Alex (AI receptionist)
2. Caller requests an appointment
3. Agent collects: name, reason, preferred date/time, contact number
4. Agent calls `check_availability` to verify the slot
5. Agent calls `book_appointment` to confirm and save
6. Agent reads back the full booking confirmation
7. Booking is stored in SQLite (and Cal.com if configured)

### Live Monitoring
1. Open `/monitor` in a separate browser tab
2. The dashboard connects via WebSocket to the backend
3. Real-time updates show: transcript, agent state, detected intent, current action
4. Appointment data fields populate as the agent collects them
5. Call status timeline shows: connected → transferring → ended

### Take-Over
1. Watcher clicks "Take Over Call" on the monitor dashboard
2. Backend pauses the AI agent
3. Watcher's browser microphone connects to the LiveKit room
4. Watcher speaks directly to the caller
5. Clicking "Release Control" resumes the AI agent

### Warm Transfer
1. Caller says something like "I need to talk to a person" or mentions billing/complaints
2. Agent detects the transfer intent and calls `transfer_to_human`
3. Backend dials the human agent's phone via Twilio
4. A TwiML summary of the conversation is played to the human
5. Human presses 1 to accept or 2 to decline
6. **Accept**: Caller is connected to the human, AI exits gracefully
7. **Decline**: AI returns to the caller and apologizes

---

## 📁 Project Structure

```text
VoiceDesk/
├── backend/
│   ├── agent.py            # LiveKit voice agent with VoicePipelineAgent
│   ├── main.py             # FastAPI server (token, appointments, WebSocket)
│   ├── tools.py            # Function tools for the LLM
│   ├── db.py               # SQLite appointment storage
│   ├── cal_service.py      # Cal.com API wrapper (optional)
│   ├── twilio_transfer.py  # Warm transfer via Twilio
│   ├── monitoring.py       # Real-time event bus
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── page.tsx        # Caller UI
│   │   ├── monitor/
│   │   │   └── page.tsx    # Monitoring dashboard
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/
│   │   ├── Transcript.tsx
│   │   ├── AgentStatus.tsx
│   │   ├── TakeOverButton.tsx
│   │   └── CallSummary.tsx
│   └── package.json
└── README.md
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Voice Agent** | LiveKit Agents SDK (Python) |
| **LLM** | OpenAI GPT-4o / Groq (Llama 3.3) |
| **Speech-to-Text** | Deepgram Nova-3 |
| **Text-to-Speech** | ElevenLabs |
| **Telephony** | Twilio |
| **Calendar** | Cal.com (optional) & SQLite |
| **Backend API** | FastAPI + Uvicorn |
| **Frontend** | Next.js 14 (App Router) |
| **Real-time** | WebSocket + LiveKit WebRTC |
