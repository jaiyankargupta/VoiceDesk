"use client";

import styles from "./AgentStatus.module.css";

interface AgentStatusProps {
  state: string;
  intent: string | null;
  action: string | null;
}

const STATE_CONFIG: Record<string, { label: string; color: string; className: string }> = {
  listening: { label: "Listening", color: "var(--accent-green)", className: "listening" },
  thinking: { label: "Thinking", color: "var(--accent-amber)", className: "thinking" },
  speaking: { label: "Speaking", color: "var(--accent-indigo)", className: "speaking" },
  paused: { label: "Paused", color: "var(--accent-rose)", className: "paused" },
  idle: { label: "Idle", color: "var(--text-muted)", className: "idle" },
};

export default function AgentStatus({ state, intent, action }: AgentStatusProps) {
  const config = STATE_CONFIG[state] || STATE_CONFIG.idle;

  return (
    <div className={styles.container}>
      <div className={styles.stateRow}>
        <div className={`${styles.indicator} ${styles[config.className]}`}>
          <div className={styles.dot} style={{ background: config.color }} />
          {state === "listening" && <div className={styles.pulseRing} style={{ borderColor: config.color }} />}
          {state === "thinking" && <div className={styles.spinner} />}
          {state === "speaking" && (
            <div className={styles.waveGroup}>
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className={styles.waveBar} style={{ animationDelay: `${i * 0.1}s` }} />
              ))}
            </div>
          )}
        </div>
        <span className={styles.stateLabel} style={{ color: config.color }}>{config.label}</span>
      </div>

      {intent && (
        <div className={styles.field}>
          <span className={styles.fieldLabel}>Intent</span>
          <span className={`badge ${intent === "transfer_request" ? "badge-rose" : "badge-indigo"}`}>{intent}</span>
        </div>
      )}

      {action && (
        <div className={styles.field}>
          <span className={styles.fieldLabel}>Action</span>
          <span className={styles.actionText}>{action}</span>
        </div>
      )}
    </div>
  );
}
