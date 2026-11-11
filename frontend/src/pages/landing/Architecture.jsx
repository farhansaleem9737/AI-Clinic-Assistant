import { useState } from "react";
import { LIFECYCLES } from "./content";
import { moveTab } from "./tabs";

/** How a request travels through the system, one tab per lifecycle. */
export default function Architecture() {
  const [flow, setFlow] = useState(LIFECYCLES[0].id);
  const lifecycle = LIFECYCLES.find((l) => l.id === flow);

  return (
    <>
      <div className="lp-flows">
        <div className="lp-tabs" role="tablist" aria-label="Request lifecycles">
          {LIFECYCLES.map(({ id, title }) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`lp-flow-tab-${id}`}
              aria-selected={flow === id}
              aria-controls="lp-flow-panel"
              tabIndex={flow === id ? 0 : -1}
              className={flow === id ? "lp-tab active" : "lp-tab"}
              onClick={() => setFlow(id)}
              onKeyDown={(event) => moveTab(event, LIFECYCLES, flow, setFlow, "lp-flow-tab-")}
            >
              {title}
            </button>
          ))}
        </div>
        <ol id="lp-flow-panel" role="tabpanel" aria-labelledby={`lp-flow-tab-${flow}`} className="lp-flow-steps" key={flow}>
          {lifecycle.steps.map((step, i) => (
            <li key={step}>
              <span className="lp-step-num" aria-hidden="true">
                {i + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
        {flow === "ai" && (
          <p className="lp-note">
            Questions (“who is free on Thursday?”) are answered straight away. Anything that changes data — booking,
            cancelling, moving a visit — is only proposed until you confirm it.
          </p>
        )}
      </div>
    </>
  );
}
