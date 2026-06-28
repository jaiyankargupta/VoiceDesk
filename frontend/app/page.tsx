"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Room,
  RoomEvent,
  Track,
  RemoteTrackPublication,
  RemoteParticipant,
  ConnectionState,
} from "livekit-client";
import styles from "./page.module.css";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface TranscriptEntry {
  role: "user" | "agent";
  text: string;
  ts: number;
}

export default function CallPage() {
  const [connectionState, setConnectionState] = useState<"idle" | "connecting" | "connected" | "disconnected">("idle");
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [agentState, setAgentState] = useState<string>("idle");
  const roomRef = useRef<Room | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(scrollToBottom, [transcript, scrollToBottom]);

  const connectMonitor = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    const wsUrl = API_BASE.replace(/^http/, "ws");
    const ws = new WebSocket(`${wsUrl}/ws/monitor`);

    ws.onopen = () => {
      setTranscript([]); // clear transcript on connect because backend sends full history
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      console.log("WebSocket event received on CallPage:", msg);
      if (msg.type === "transcript") {
        setTranscript((prev) => [...prev, { ...msg.data, ts: msg.ts }]);
      }
      if (msg.type === "agent_state") {
        setAgentState(msg.data.state);
      }
    };

    ws.onclose = () => {
      if (wsRef.current === ws) {
        setTimeout(connectMonitor, 2000);
      }
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connectMonitor();
    return () => {
      if (wsRef.current) {
        const ws = wsRef.current;
        wsRef.current = null;
        ws.close();
      }
    };
  }, [connectMonitor]);

  const startCall = async () => {
    setConnectionState("connecting");

    try {
      const res = await fetch(`${API_BASE}/api/token?identity=caller`, { method: "POST" });
      const { token, url } = await res.json();

      const room = new Room();
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrackPublication["track"]) => {
        if (track && track.kind === Track.Kind.Audio) {
          const el = track.attach();
          document.body.appendChild(el);
        }
      });

      room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
        if (state === ConnectionState.Disconnected) {
          setConnectionState("disconnected");
        }
      });

      await room.connect(url, token);
      await room.localParticipant.setMicrophoneEnabled(true);

      setConnectionState("connected");
    } catch (err) {
      console.error("Failed to connect:", err);
      setConnectionState("idle");
    }
  };

  const endCall = async () => {
    if (roomRef.current) {
      await roomRef.current.disconnect();
      roomRef.current = null;
    }
    setConnectionState("disconnected");
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.logo}>
          <div className={styles.logoIcon}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" fill="url(#g1)" />
              <path d="M9 9l3 3-3 3" stroke="white" strokeWidth="2" strokeLinecap="round" />
              <path d="M15 9v6" stroke="white" strokeWidth="2" strokeLinecap="round" />
              <defs>
                <linearGradient id="g1" x1="2" y1="2" x2="22" y2="22">
                  <stop stopColor="#6366f1" />
                  <stop offset="1" stopColor="#8b5cf6" />
                </linearGradient>
              </defs>
            </svg>
          </div>
          <span>VoiceDesk</span>
        </div>
        <a href="/monitor" className={styles.monitorLink}>
          Open Monitor →
        </a>
      </header>

      <main className={styles.main}>
        <div className={styles.callSection}>
          <div className={styles.agentAvatar}>
            <div className={`${styles.avatarRing} ${connectionState === "connected" ? styles.active : ""}`} />
            <div className={styles.avatarInner}>
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
                <path d="M12 2a3 3 0 00-3 3v6a3 3 0 006 0V5a3 3 0 00-3-3z" fill="currentColor" opacity="0.8" />
                <path d="M19 10v1a7 7 0 01-14 0v-1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <line x1="12" y1="19" x2="12" y2="22" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </div>
            {connectionState === "connected" && (
              <span className={`badge ${agentState === "speaking" ? "badge-indigo" : agentState === "thinking" ? "badge-amber" : "badge-green"}`} style={{ position: "absolute", bottom: "-8px" }}>
                {agentState}
              </span>
            )}
          </div>

          <h2 className={styles.agentName}>Alex — VoiceDesk Health</h2>
          <p className={styles.agentDesc}>AI Receptionist</p>

          {connectionState === "idle" && (
            <button className="btn btn-primary" onClick={startCall} style={{ marginTop: 24, padding: "14px 40px", fontSize: 16 }}>
              Start Call
            </button>
          )}
          {connectionState === "connecting" && (
            <button className="btn btn-primary" disabled style={{ marginTop: 24 }}>
              Connecting...
            </button>
          )}
          {connectionState === "connected" && (
            <button className="btn btn-danger" onClick={endCall} style={{ marginTop: 24 }}>
              End Call
            </button>
          )}
          {connectionState === "disconnected" && (
            <div className={styles.endedBanner}>
              <p>Call ended</p>
              <button className="btn btn-outline" onClick={() => { setConnectionState("idle"); setTranscript([]); }}>
                New Call
              </button>
            </div>
          )}
        </div>

        <div className={`card ${styles.transcriptPanel}`}>
          <div className={styles.panelHeader}>
            <h3>Live Transcript</h3>
            <span className={styles.entryCount}>{transcript.length} messages</span>
          </div>
          <div className={styles.transcriptBody}>
            {transcript.length === 0 && (
              <p className={styles.emptyState}>
                {connectionState === "connected" ? "Waiting for conversation..." : "Start a call to see the transcript"}
              </p>
            )}
            {transcript.map((entry, i) => (
              <div key={i} className={`${styles.entry} ${styles[entry.role]} animate-fade-in`}>
                <span className={styles.entryRole}>{entry.role === "agent" ? "Alex" : "Caller"}</span>
                <p className={styles.entryText}>{entry.text}</p>
              </div>
            ))}
            <div ref={transcriptEndRef} />
          </div>
        </div>
      </main>
    </div>
  );
}
