"use client";

import { useState, useRef, useCallback } from "react";
import { Room, RoomEvent, Track } from "livekit-client";
import styles from "./TakeOverButton.module.css";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

interface TakeOverButtonProps {
  roomName: string;
  onStateChange: (active: boolean) => void;
}

export default function TakeOverButton({ roomName, onStateChange }: TakeOverButtonProps) {
  const [active, setActive] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const roomRef = useRef<Room | null>(null);

  const activate = useCallback(async () => {
    setConnecting(true);
    try {
      await fetch(`${API_BASE}/api/takeover`, { method: "POST" });

      const res = await fetch(`${API_BASE}/api/token?identity=watcher&room=${roomName}`, { method: "POST" });
      const { token, url } = await res.json();

      const room = new Room();
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track && track.kind === Track.Kind.Audio) {
          const el = track.attach();
          document.body.appendChild(el);
        }
      });

      await room.connect(url, token);
      await room.localParticipant.setMicrophoneEnabled(true);

      setActive(true);
      onStateChange(true);
    } catch (err) {
      console.error("Takeover failed:", err);
    } finally {
      setConnecting(false);
    }
  }, [roomName, onStateChange]);

  const deactivate = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/api/release`, { method: "POST" });
      if (roomRef.current) {
        await roomRef.current.disconnect();
        roomRef.current = null;
      }
      setActive(false);
      onStateChange(false);
    } catch (err) {
      console.error("Release failed:", err);
    }
  }, [onStateChange]);

  if (active) {
    return (
      <button className={`${styles.button} ${styles.active}`} onClick={deactivate}>
        <span className={styles.liveDot} />
        Release Control
      </button>
    );
  }

  return (
    <button className={styles.button} onClick={activate} disabled={connecting}>
      {connecting ? "Connecting..." : "Take Over Call"}
    </button>
  );
}
