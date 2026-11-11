import { useRef } from "react";

/**
 * A 6-digit one-time code as six boxes (D127). Typing moves to the next box,
 * Backspace on an empty box goes back, arrows move, and pasting (or the phone's
 * "from Messages/Mail" suggestion into the first box) fills them all.
 * `value` is the digits so far ("" to "123456"); `onChange` gets the new string.
 * `onComplete(code)` runs when the sixth digit is entered.
 */
export default function OtpInput({ id, value, onChange, onComplete, length = 6, disabled, invalid, describedBy, autoFocus, label }) {
  const boxes = useRef([]);
  const digits = Array.from({ length }, (_, i) => value[i] ?? "");

  const focus = (index) => {
    const box = boxes.current[Math.max(0, Math.min(index, length - 1))];
    box?.focus();
    box?.select();
  };

  const set = (next, focusAt) => {
    const code = next.replace(/\D/g, "").slice(0, length);
    onChange(code);
    if (focusAt !== undefined) focus(focusAt);
    if (code.length === length && value.length < length) onComplete?.(code);
  };

  const type = (index, raw) => {
    const typed = raw.replace(/\D/g, "");
    if (!typed) return;
    if (typed.length >= length) return set(typed, length - 1); // the phone's autofill of the whole code
    const chars = digits.slice();
    chars[index] = typed.slice(-1); // a key typed next to an existing digit replaces it
    // Boxes fill left to right: a digit typed past the end lands in the first empty one.
    const joined = chars.join("").slice(0, length);
    set(joined, Math.min(joined.length, length - 1));
  };

  const keyDown = (index, event) => {
    if (event.key === "Backspace") {
      event.preventDefault();
      if (digits[index]) set(value.slice(0, index) + value.slice(index + 1), index);
      else if (index > 0) set(value.slice(0, index - 1) + value.slice(index), index - 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      focus(index - 1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      focus(index + 1);
    }
  };

  const paste = (event) => {
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "");
    if (!pasted) return;
    event.preventDefault();
    set(pasted, Math.min(pasted.length, length - 1));
  };

  return (
    <div className={`otp-input${invalid ? " invalid" : ""}`} role="group" aria-label={label} aria-describedby={describedBy}>
      {digits.map((digit, index) => (
        <input
          key={index}
          id={index === 0 ? id : `${id}-${index + 1}`}
          ref={(el) => (boxes.current[index] = el)}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          maxLength={index === 0 ? length : 1}
          aria-label={`Digit ${index + 1} of ${length}`}
          aria-invalid={invalid || undefined}
          autoFocus={autoFocus && index === 0}
          value={digit}
          disabled={disabled}
          onChange={(e) => type(index, e.target.value)}
          onKeyDown={(e) => keyDown(index, e)}
          onPaste={paste}
          onFocus={(e) => e.target.select()}
        />
      ))}
    </div>
  );
}
