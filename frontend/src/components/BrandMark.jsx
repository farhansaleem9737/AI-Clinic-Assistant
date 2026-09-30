import { Plus } from "lucide-react";

// The Clinic AI Assistant logo mark, used in the sidebar and on the sign-in pages.
export default function BrandMark({ size = 38 }) {
  return (
    <span className="brand-mark" style={{ width: size, height: size, borderRadius: size * 0.26 }} aria-hidden="true">
      <Plus size={size * 0.58} strokeWidth={3} />
    </span>
  );
}
