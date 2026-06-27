"use client";

import styles from "./CallSummary.module.css";

interface CallSummaryProps {
  summary: string | null;
  appointmentData: Record<string, string> | null;
}

export default function CallSummary({ summary, appointmentData }: CallSummaryProps) {
  if (!summary && !appointmentData) return null;

  return (
    <div className={`${styles.container} animate-slide-up`}>
      {appointmentData && appointmentData.status && (
        <div className={styles.section}>
          <h4 className={styles.sectionTitle}>Appointment Details</h4>
          <div className={styles.fields}>
            {appointmentData.name && (
              <div className={styles.field}>
                <span className={styles.label}>Name</span>
                <span className={styles.value}>{appointmentData.name}</span>
              </div>
            )}
            {appointmentData.reason && (
              <div className={styles.field}>
                <span className={styles.label}>Reason</span>
                <span className={styles.value}>{appointmentData.reason}</span>
              </div>
            )}
            {appointmentData.date_time && (
              <div className={styles.field}>
                <span className={styles.label}>Date/Time</span>
                <span className={styles.value}>{appointmentData.date_time}</span>
              </div>
            )}
            {appointmentData.contact && (
              <div className={styles.field}>
                <span className={styles.label}>Contact</span>
                <span className={styles.value}>{appointmentData.contact}</span>
              </div>
            )}
            {appointmentData.booking_id && (
              <div className={styles.field}>
                <span className={styles.label}>Booking ID</span>
                <span className={styles.value}>#{appointmentData.booking_id}</span>
              </div>
            )}
            <div className={styles.field}>
              <span className={styles.label}>Status</span>
              <span className={`badge ${appointmentData.status === "confirmed" ? "badge-green" : appointmentData.status === "cancelled" ? "badge-rose" : "badge-amber"}`}>
                {appointmentData.status}
              </span>
            </div>
          </div>
        </div>
      )}

      {summary && (
        <div className={styles.section}>
          <h4 className={styles.sectionTitle}>Call Summary</h4>
          <p className={styles.summaryText}>{summary}</p>
        </div>
      )}
    </div>
  );
}
