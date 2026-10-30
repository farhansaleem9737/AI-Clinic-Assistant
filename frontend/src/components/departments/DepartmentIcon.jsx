import { Activity, Baby, Bone, Brain, Ear, Eye, HeartPulse, Hospital, Microscope, Pill, ScanFace, Smile, Stethoscope, Syringe } from "lucide-react";
import { COLORS, departmentLook } from "../../utils/departments";

const ICONS = {
  "heart-pulse": HeartPulse,
  stethoscope: Stethoscope,
  brain: Brain,
  bone: Bone,
  baby: Baby,
  ear: Ear,
  eye: Eye,
  "scan-face": ScanFace,
  activity: Activity,
  pill: Pill,
  microscope: Microscope,
  syringe: Syringe,
  smile: Smile,
  hospital: Hospital,
};

/** The department's coloured icon, round or (cards) a rounded square. Decorative: the name is beside it. */
export default function DepartmentIcon({ department, size = 52, square = false }) {
  const { icon, color } = departmentLook(department);
  const Icon = ICONS[icon] ?? Hospital;
  const palette = COLORS[color] ?? COLORS.blue;
  return (
    <span className={`dept-icon${square ? " square" : ""}`} style={{ width: size, height: size, color: palette.fg, background: palette.bg }} aria-hidden="true">
      <Icon size={Math.round(size * 0.48)} />
    </span>
  );
}
