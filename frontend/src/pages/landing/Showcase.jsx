import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import aiAvatar from "../../assets/clinic-ai-avatar.png";
import Avatar from "../../components/Avatar";
import { SHOWCASE } from "./content";
import { moveTab } from "./tabs";

/** One tab per workspace, each with a small demo-data preview and a real next step. */
export default function Showcase() {
  const [tab, setTab] = useState(SHOWCASE[0].id);
  const item = SHOWCASE.find((s) => s.id === tab);
  return (
    <div className="lp-showcase">
      <div className="lp-tabs" role="tablist" aria-label="Workspaces">
        {SHOWCASE.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`lp-show-tab-${id}`}
            aria-selected={tab === id}
            aria-controls="lp-show-panel"
            tabIndex={tab === id ? 0 : -1}
            className={tab === id ? "lp-tab active" : "lp-tab"}
            onClick={() => setTab(id)}
            onKeyDown={(event) => moveTab(event, SHOWCASE, tab, setTab, "lp-show-tab-")}
          >
            {label}
          </button>
        ))}
      </div>
      <div id="lp-show-panel" role="tabpanel" aria-labelledby={`lp-show-tab-${tab}`} className="lp-show-panel" key={tab}>
        <div className="lp-show-copy">
          <h3>{item.title}</h3>
          <p>{item.text}</p>
          <Link to={item.cta.to} className="lp-btn primary">
            {item.cta.label} <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
        <div className="lp-show-window" aria-hidden="true">
          <span className="lp-demo-tag">Demo data</span>
          <div className="lp-window-bar">
            <i />
            <i />
            <i />
          </div>
          {item.chat ? (
            <div className="lp-show-chat">
              {item.chat.map(([who, text]) => (
                <div key={text} className={`lp-bubble ${who}`}>
                  {who === "assistant" && <img src={aiAvatar} alt="" width={26} height={26} />}
                  <span>{text}</span>
                </div>
              ))}
            </div>
          ) : (
            <>
              <div className="lp-show-stats">
                {item.stats.map(([label, value]) => (
                  <div key={label}>
                    <small>{label}</small>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              {item.rows.map(([name, meta, status]) => (
                <div key={name} className="lp-dash-row lp-show-row">
                  <Avatar name={name} size={30} role={name.startsWith("Dr.") ? "doctor" : undefined} />
                  <span className="lp-dash-who">
                    {name}
                    <small>{meta}</small>
                  </span>
                  <span className={`lp-pill ${/Active|Confirmed|Checked/.test(status) ? "ok" : status === "Pending" || status === "Waiting" ? "warn" : "info"}`}>
                    {status}
                  </span>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
