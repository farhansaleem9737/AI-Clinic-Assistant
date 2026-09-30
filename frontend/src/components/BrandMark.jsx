import logo from "../assets/logo.png";

/**
 * The Clinic AI Assistant logo. Every place the brand appears (sidebar,
 * sign-in and create-account cards) renders this component, so the logo is
 * changed in one file: src/assets/logo.png.
 *
 * It is always shown next to the written name, so it is decorative for
 * screen readers (empty alt) rather than announced twice.
 */
export default function BrandMark({ size = 38 }) {
  return <img className="brand-mark" src={logo} alt="" width={size} height={size} />;
}
