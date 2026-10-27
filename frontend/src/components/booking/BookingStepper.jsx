import { Check } from "lucide-react";

const BOOKING_STEPS = ["Select Doctor", "Date & Time", "Confirm"];

/**
 * Select Doctor → Date & Time → Confirm. `current` is 1-based; a value past
 * the last step (after booking) marks every step complete.
 */
export default function BookingStepper({ current }) {
  return (
    <ol className="booking-stepper" aria-label="Booking progress">
      {BOOKING_STEPS.map((label, index) => {
        const number = index + 1;
        const state = number < current ? "done" : number === current ? "current" : "upcoming";
        return (
          <li key={label} className={state} aria-current={state === "current" ? "step" : undefined}>
            <span className="step-dot" aria-hidden="true">
              {state === "done" ? <Check size={16} strokeWidth={3} /> : number}
            </span>
            <span className="step-label">
              {label}
              {state === "done" && <span className="sr-only"> (completed)</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
