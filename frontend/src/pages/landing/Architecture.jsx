import { useState } from "react";
import { ArrowDown } from "lucide-react";
import { ARCH_LAYERS, LIFECYCLES } from "./content";
import { moveTab } from "./tabs";

const MODULES = ARCH_LAYERS.flatMap((layer) => layer.modules);

/**
 * Three stacked layers of modules. Hovering or focusing a module highlights
 * the modules it talks to; choosing one shows what it does in the panel. The
 * same text is in the panel for keyboard, touch and screen-reader users.
 */
export default function Architecture() {
  const [selected, setSelected] = useState("fastapi");
  const [hovered, setHovered] = useState(null);
  const [flow, setFlow] = useState(LIFECYCLES[0].id);
  const active = MODULES.find((m) => m.id === (hovered ?? selected));
  const current = MODULES.find((m) => m.id === selected);
  const lifecycle = LIFECYCLES.find((l) => l.id === flow);

  return (
    <>
      <div className="lp-arch">
        <div className="lp-arch-diagram">
          {ARCH_LAYERS.map((layer, i) => (
            <div key={layer.id} className="lp-arch-layer-wrap">
              {i > 0 && (
                <div className="lp-arch-flow" aria-hidden="true">
                  <ArrowDown size={16} /> requests · <ArrowDown size={16} style={{ transform: "rotate(180deg)" }} /> responses
                </div>
              )}
              <div className={`lp-arch-layer layer-${layer.id}`}>
                <h3>
                  <span>Layer {i + 1}</span> {layer.title}
                </h3>
                <div className="lp-arch-modules">
                  {layer.modules.map(({ id, icon: Icon, name }) => {
                    const linked = active && active.id !== id && active.links.includes(id);
                    const state = id === selected ? " selected" : active?.id === id ? " active" : linked ? " linked" : "";
                    return (
                      <button
                        key={id}
                        type="button"
                        className={`lp-arch-module${state}`}
                        aria-pressed={id === selected}
                        onClick={() => setSelected(id)}
                        onMouseEnter={() => setHovered(id)}
                        onMouseLeave={() => setHovered(null)}
                        onFocus={() => setHovered(id)}
                        onBlur={() => setHovered(null)}
                      >
                        <Icon size={18} aria-hidden="true" />
                        {name}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          ))}
        </div>
        <aside className="lp-arch-detail" aria-live="polite">
          <span className="lp-eyebrow">Module</span>
          <h3>{current.name}</h3>
          <p>{current.detail}</p>
          <p className="lp-arch-links">
            <strong>Talks to:</strong> {current.links.map((id) => MODULES.find((m) => m.id === id).name).join(", ")}
          </p>
        </aside>
      </div>

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
