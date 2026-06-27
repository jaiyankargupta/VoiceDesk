"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Transcript from "@/components/Transcript";
import AgentStatus from "@/components/AgentStatus";
import TakeOverButton from "@/components/TakeOverButton";
import CallSummary from "@/components/CallSummary";
import styles from "./monitor.module.css";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

interface TranscriptEntry {
  role: "user" | "agent";
  text: string;
  ts: number;
}

export default function MonitorPage() {
  const [connected, setConnected] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [agentState, setAgentState] = useState("idle");
  const [callStatus, setCallStatus] = useState("waiting");
  const [intent, setIntent] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [appointmentData, setAppointmentData] = useState<Record<string, string> | null>(null);
  const [callSummary, setCallSummary] = useState<string | null>(null);
  const [takeoverActive, setTakeoverActive] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const connectWebSocket = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    const wsUrl = API_BASE.replace(/^http/, "ws");
    const ws = new WebSocket(`${wsUrl}/ws/monitor`);

    ws.onopen = () => {
      setConnected(true);
      setTranscript([]); // clear transcript on connect because backend sends full history
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      console.log("Monitor WebSocket event received:", msg);

      switch (msg.type) {
        case "transcript":
          setTranscript((prev) => [...prev, { ...msg.data, ts: msg.ts }]);
          break;
        case "agent_state":
          setAgentState(msg.data.state);
          break;
        case "call_status":
          setCallStatus(msg.data.status);
          break;
        case "intent_detected":
          setIntent(msg.data.intent);
          break;
        case "action_update":
          setAction(msg.data.action);
          break;
        case "appointment_data":
          setAppointmentData((prev) => ({ ...prev, ...msg.data }));
          break;
        case "call_summary":
          setCallSummary(msg.data.summary);
          break;
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (wsRef.current === ws) {
        setTimeout(connectWebSocket, 2000);
      }
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) {
        const ws = wsRef.current;
        wsRef.current = null;
        ws.close();
      }
    };
  }, [connectWebSocket]);

  const statusColor = {
    waiting: "var(--text-muted)",
    connected: "var(--accent-green)",
    transferring: "var(--accent-amber)",
    transferred: "var(--accent-teal)",
    ended: "var(--text-muted)",
  }[callStatus] || "var(--text-muted)";

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <a href="/" className={styles.backLink}>← Back</a>
          <h1 className={styles.title}>Live Monitor</h1>
        </div>
        <div className={styles.headerRight}>
          <div className={styles.wsStatus}>
            <div className={styles.wsDot} style={{ background: connected ? "var(--accent-green)" : "var(--accent-rose)" }} />
            <span>{connected ? "Connected" : "Reconnecting..."}</span>
          </div>
          <div className={styles.callStatusBadge} style={{ borderColor: statusColor, color: statusColor }}>
            {callStatus}
          </div>
        </div>
      </header>

      <main className={styles.grid}>
        <div className={`card ${styles.transcriptCard}`}>
          <div className={styles.cardHeader}>
            <h2>Transcript</h2>
            <span className={styles.count}>{transcript.length}</span>
          </div>
          <Transcript entries={transcript} />
        </div>

        <div className={styles.sidebar}>
          <div className={`card ${styles.statusCard}`}>
            <div className={styles.cardHeader}>
              <h2>Agent Status</h2>
            </div>
            <AgentStatus state={agentState} intent={intent} action={action} />
          </div>

          <div className={`card ${styles.controlCard}`}>
            <div className={styles.cardHeader}>
              <h2>Controls</h2>
            </div>
            <div className={styles.controlBody}>
              <TakeOverButton
                roomName="voicedesk-room"
                onStateChange={setTakeoverActive}
              />
              {takeoverActive && (
                <p className={styles.takeoverNotice}>
                  You are speaking directly to the caller. The AI agent is paused.
                </p>
              )}
            </div>
          </div>

          <div className={`card ${styles.dataCard}`}>
            <div className={styles.cardHeader}>
              <h2>Call Data</h2>
            </div>
            <CallSummary summary={callSummary} appointmentData={appointmentData} />
            {!callSummary && !appointmentData && (
              <p className={styles.emptyData}>Data will appear as the conversation progresses</p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
