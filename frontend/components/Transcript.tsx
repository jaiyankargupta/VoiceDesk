"use client";

import { useRef, useEffect } from "react";
import styles from "./Transcript.module.css";

interface TranscriptEntry {
  role: "user" | "agent";
  text: string;
  ts: number;
}

interface TranscriptProps {
  entries: TranscriptEntry[];
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function Transcript({ entries }: TranscriptProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  return (
    <div className={styles.container}>
      {entries.length === 0 && (
        <p className={styles.empty}>No conversation yet</p>
      )}
      {entries.map((entry, i) => (
        <div key={i} className={`${styles.message} ${styles[entry.role]} animate-fade-in`}>
          <div className={styles.meta}>
            <span className={styles.speaker}>{entry.role === "agent" ? "Alex" : "Caller"}</span>
            <span className={styles.time}>{formatTime(entry.ts)}</span>
          </div>
          <p className={styles.text}>{entry.text}</p>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
